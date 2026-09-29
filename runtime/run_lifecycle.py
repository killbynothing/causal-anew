"""P1b run/session lifecycle contract.

The lifecycle state owns whether a writable run is open, waiting for durable
close, or fully closed. ended remains a compatibility projection only.
"""
from __future__ import annotations

from typing import Any, Mapping

OPEN = "open"
CLOSING = "closing"
CLOSED = "closed"
VALID_STATES = frozenset({OPEN, CLOSING, CLOSED})

_ALLOWED = {
    OPEN: frozenset({OPEN, CLOSING}),
    CLOSING: frozenset({CLOSING, CLOSED}),
    CLOSED: frozenset({CLOSED}),
}


def validate_state(state: str) -> str:
    value = str(state or "").strip()
    if value not in VALID_STATES:
        raise ValueError(f"invalid lifecycle state: {value!r}")
    return value


def validate_transition(before: str, after: str) -> None:
    src = validate_state(before)
    dst = validate_state(after)
    if dst not in _ALLOWED[src]:
        raise ValueError(f"illegal lifecycle transition: {src} -> {dst}")


def derive_state(raw: Mapping[str, Any] | None) -> str:
    """Recover legacy ended-without-receipt as closing instead of reviving it."""
    data = dict(raw or {})
    if data.get("run_receipt") or data.get("run_closed"):
        return CLOSED
    explicit = str(data.get("lifecycle_state") or "").strip()
    if explicit in VALID_STATES:
        if explicit == CLOSED and not data.get("run_receipt"):
            return CLOSING
        return explicit
    if bool(data.get("ended", False)):
        return CLOSING
    return OPEN
