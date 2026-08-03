# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = ROOT / "runtime" / "spoiler_defense" / "spoiler_lexicon.json"


@lru_cache(maxsize=1)
def load_spoiler_lexicon() -> dict[str, Any]:
    data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    return {
        "S": [str(item).strip() for item in data.get("S", []) if str(item).strip()],
        "A": [str(item).strip() for item in data.get("A", []) if str(item).strip()],
        "fallbacks": dict(data.get("fallbacks", {})),
    }


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def find_spoiler_hits(text: str) -> list[dict[str, str]]:
    normalized = _normalize(text)
    if not normalized:
        return []
    hits: list[dict[str, str]] = []
    lexicon = load_spoiler_lexicon()
    for tier in ("S", "A"):
        for term in lexicon[tier]:
            needle = _normalize(term)
            if needle and needle in normalized:
                hits.append({"tier": tier, "term": term})
    return hits


def spoiler_error_label(hits: list[dict[str, str]]) -> str:
    ordered = [f"{hit['tier']}:{hit['term']}" for hit in hits]
    return ", ".join(ordered[:6])


def make_spoiler_degradation(channel: str, hits: list[dict[str, str]]) -> dict[str, str]:
    tiers = "/".join(sorted({hit["tier"] for hit in hits})) or "A"
    return {
        "component": "spoiler_gate",
        "mode": "hard_gate",
        "reason": f"{channel} 可见层命中 {tiers} 级语义泄露闸",
        "detail": spoiler_error_label(hits),
    }


def safe_fallback_text(channel: str) -> str:
    lexicon = load_spoiler_lexicon()
    fallbacks = lexicon.get("fallbacks", {})
    return str(fallbacks.get(channel) or fallbacks.get("bridge") or "")


def guard_visible_text(text: str, channel: str) -> tuple[str, list[dict[str, str]]]:
    hits = find_spoiler_hits(text)
    if not hits:
        return str(text or ""), []
    return safe_fallback_text(channel), [make_spoiler_degradation(channel, hits)]


def guard_turns(turns: list[dict[str, Any]], channel: str = "actor") -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    hits: list[dict[str, str]] = []
    for item in turns:
        text = str(item.get("text", "") or "")
        stage = str(item.get("stage", "") or "")
        hits.extend(find_spoiler_hits(text))
        hits.extend(find_spoiler_hits(stage))
    if not hits:
        return turns, []

    fallback = {
        "speaker": "旁白",
        "text": safe_fallback_text(channel),
        "stage": "",
    }
    return [fallback], [make_spoiler_degradation(channel, hits)]
