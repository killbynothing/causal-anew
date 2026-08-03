"""Resolve cross-route opportunities without inventing a destination scene.

`handoff_rules.json` is deliberately only an opportunity graph: it says a
route may become visible, not which card may be force-entered.  A playable
handoff additionally needs a human-approved EntryContext and target frame.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime import world_calendar


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "runtime" / "handoff_rules.json"


def load_handoff_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise ValueError("handoff_rules.json must contain a rules list")
    return raw


def eligible_entries(
    *,
    cursor: dict[str, Any],
    source_line: str,
    location: str,
    rules_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return lit route opportunities, never a fabricated target-card jump."""
    rules_data = rules_data or load_handoff_rules()
    offers: list[dict[str, Any]] = []
    for index, rule in enumerate(rules_data.get("rules", [])):
        if not isinstance(rule, dict):
            continue
        when = rule.get("when") if isinstance(rule.get("when"), dict) else {}
        ch_window = when.get("ch_window")
        if (
            when.get("source_line") != source_line
            or when.get("location") != location
            or not isinstance(ch_window, list)
            or len(ch_window) != 2
        ):
            continue
        ch = int(cursor.get("ch_anchor", 0) or 0)
        if not int(ch_window[0]) <= ch <= int(ch_window[1]):
            continue
        if not world_calendar.entry_lit(cursor, {"ch_anchor_min": int(ch_window[0])}):
            continue
        for target_namespace in rule.get("lights", []):
            target_namespace = str(target_namespace).strip()
            if not target_namespace:
                continue
            offers.append(
                {
                    "entry_id": f"handoff:{source_line}:{target_namespace}:{index}",
                    "source_line": source_line,
                    "target_namespace": target_namespace,
                    "method": str(rule.get("method", "")),
                    "playable": False,
                    "status": "pending_human_entry_context",
                    "reason": "handoff rule lights an opportunity but has no approved target frame or EntryContext",
                }
            )
    return offers
