from __future__ import annotations

import copy
import json
import threading
import time
from typing import Any
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import SSLError


def chat_request_options(config: dict[str, Any] | None) -> dict[str, Any]:
    """Provider-local extras (e.g. disable thinking) copied from ignored config."""
    raw = config.get("chat_request_options", {}) if isinstance(config, dict) else {}
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def apply_chat_request_options(
    body: dict[str, Any],
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Mutate and return body with provider options merged in."""
    body.update(chat_request_options(config))
    return body


_SHARED_SESSION: requests.Session | None = None
_SESSION_LOCK = threading.Lock()
_DEFAULT_POOL_SIZE = 8
_RETRYABLE_ERRORS = {
    "timeout",
    "ssl_eof",
    "ssl_error",
    "connection_reset",
    "connection_error",
}
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
NON_RETRYABLE_HTTP_STATUS = {400, 401, 403, 404, 422}

_ADAPTIVE_LOCK = threading.Lock()
_ADAPTIVE_MAX_WORKERS = 4


def _usage_int(value: Any) -> int | None:
    """Return a non-negative usage counter without accepting provider junk."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def context_usage_receipt(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Project provider token evidence into a stable, prompt-free receipt.

    OpenAI-compatible providers disagree about cache field names.  We retain only
    numeric counters and the field paths that actually appeared.  Missing cache
    evidence remains ``unknown``: a connection reuse is never treated as a cache
    hit.
    """
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {
            "observable": False,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "cached_tokens": None,
            "cache_status": "unknown",
            "provider_usage_fields": [],
        }

    fields: list[str] = []

    def first_counter(candidates: list[tuple[str, Any]]) -> int | None:
        for path, value in candidates:
            parsed = _usage_int(value)
            if parsed is not None:
                fields.append(path)
                return parsed
        return None

    prompt_tokens = first_counter([
        ("prompt_tokens", usage.get("prompt_tokens")),
        ("input_tokens", usage.get("input_tokens")),
    ])
    completion_tokens = first_counter([
        ("completion_tokens", usage.get("completion_tokens")),
        ("output_tokens", usage.get("output_tokens")),
    ])
    total_tokens = first_counter([("total_tokens", usage.get("total_tokens"))])
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    cached_tokens = first_counter([
        ("cached_tokens", usage.get("cached_tokens")),
        ("prompt_cache_hit_tokens", usage.get("prompt_cache_hit_tokens")),
        ("prompt_tokens_details.cached_tokens", prompt_details.get("cached_tokens")),
        ("input_tokens_details.cached_tokens", input_details.get("cached_tokens")),
        ("cache_read_input_tokens", usage.get("cache_read_input_tokens")),
    ])
    return {
        "observable": True,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cache_status": "unknown" if cached_tokens is None else ("hit" if cached_tokens > 0 else "miss"),
        "provider_usage_fields": sorted(fields),
    }


def build_session(pool_size: int = _DEFAULT_POOL_SIZE) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=0,
        pool_block=False,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_shared_session() -> requests.Session:
    global _SHARED_SESSION
    with _SESSION_LOCK:
        if _SHARED_SESSION is None:
            _SHARED_SESSION = build_session()
        return _SHARED_SESSION


def reset_shared_session_for_tests():
    global _SHARED_SESSION
    with _SESSION_LOCK:
        if _SHARED_SESSION is not None:
            _SHARED_SESSION.close()
        _SHARED_SESSION = None
    reset_adaptive_concurrency_for_tests()


def reset_adaptive_concurrency_for_tests(value: int = 4) -> None:
    global _ADAPTIVE_MAX_WORKERS
    with _ADAPTIVE_LOCK:
        _ADAPTIVE_MAX_WORKERS = max(1, int(value))


def note_provider_pressure(status_code: int | None) -> None:
    """429 后临时降并发；成功响应再缓慢抬回。"""
    global _ADAPTIVE_MAX_WORKERS
    if status_code is None:
        return
    with _ADAPTIVE_LOCK:
        if int(status_code) == 429:
            _ADAPTIVE_MAX_WORKERS = 1
        elif 200 <= int(status_code) < 300:
            _ADAPTIVE_MAX_WORKERS = min(4, _ADAPTIVE_MAX_WORKERS + 1)


def current_max_workers(requested: int) -> int:
    with _ADAPTIVE_LOCK:
        return max(1, min(int(requested), _ADAPTIVE_MAX_WORKERS))


def http_status_from_exc(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None) if response is not None else None
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def retry_after_seconds(exc: Exception, fallback: float) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return float(fallback)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return float(fallback)


def classify_request_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError):
        code = http_status_from_exc(exc)
        if code is not None:
            return f"http_{code}"
        return "http_error"
    if isinstance(exc, requests.Timeout):
        return "timeout"
    if isinstance(exc, SSLError):
        text = f"{exc!r} {exc}".lower()
        if "unexpected eof while reading" in text or "ssl eof" in text or "eof" in text:
            return "ssl_eof"
        return "ssl_error"
    if isinstance(exc, requests.ConnectionError):
        text = str(exc).lower()
        if "unexpected eof while reading" in text or "ssl eof" in text:
            return "ssl_eof"
        if "connection reset" in text or "broken pipe" in text:
            return "connection_reset"
        return "connection_error"
    if isinstance(exc, json.JSONDecodeError):
        return "json_error"
    return "unexpected_error"


def is_retryable_error(error: str | None) -> bool:
    if not error:
        return False
    if error in _RETRYABLE_ERRORS:
        return True
    if error.startswith("http_"):
        try:
            code = int(error.split("_", 1)[1])
        except (IndexError, ValueError):
            return False
        if code in NON_RETRYABLE_HTTP_STATUS:
            return False
        return code in RETRYABLE_HTTP_STATUS
    return False


def post_json(
    api_url: str,
    api_key: str,
    body: dict[str, Any],
    timeout: float,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    sess = session or get_shared_session()
    response = sess.post(
        api_url,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def post_json_with_retry(
    api_url: str,
    api_key: str,
    body: dict[str, Any],
    attempt_plan: list[tuple[str, float, float]],
    session: requests.Session | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    request_kind: str = "llm",
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    errors: list[str] = []
    timeout_trace: list[float] = []
    backoff_trace: list[float] = []
    status_trace: list[int | None] = []
    latency_ms: list[float] = []
    for idx, (label, timeout, backoff_s) in enumerate(attempt_plan):
        timeout_trace.append(timeout)
        started = time.monotonic()
        try:
            payload = post_json(api_url, api_key, body, timeout=timeout, session=session)
            elapsed = (time.monotonic() - started) * 1000.0
            latency_ms.append(round(elapsed, 1))
            status_trace.append(200)
            note_provider_pressure(200)
            return payload, {
                "ok": True,
                "attempts": idx + 1,
                "timeouts": timeout_trace,
                "backoffs": backoff_trace,
                "status_codes": status_trace,
                "latency_ms": latency_ms,
                "request_kind": request_kind,
                "last_error": errors[-1] if errors else None,
                "resolved_after": label,
                "usage": context_usage_receipt(payload),
            }
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            latency_ms.append(round(elapsed, 1))
            status_code = http_status_from_exc(exc)
            status_trace.append(status_code)
            note_provider_pressure(status_code)
            error = classify_request_error(exc)
            errors.append(f"{error}_{label}")
            if idx >= len(attempt_plan) - 1 or not is_retryable_error(error):
                break
            wait_s = retry_after_seconds(exc, backoff_s) if status_code == 429 else backoff_s
            if wait_s > 0:
                backoff_trace.append(wait_s)
                sleep_fn(wait_s)
    return None, {
        "ok": False,
        "attempts": len(timeout_trace),
        "timeouts": timeout_trace,
        "backoffs": backoff_trace,
        "status_codes": status_trace,
        "latency_ms": latency_ms,
        "request_kind": request_kind,
        "last_error": errors[-1] if errors else "unexpected_error",
        "errors": errors,
        "usage": context_usage_receipt(None),
    }
