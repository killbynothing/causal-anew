# -*- coding: utf-8 -*-
"""旧存档入场铺陈 role 迁移：bridge → narrate（R5 口径）。

转场 bridge 保留 role=bridge；仅「每场首个旁白铺陈」改为 narrate。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

NARRATOR_SPEAKERS = {"旁白", "导演"}


def _fix_segment_opening(history: list[dict[str, Any]], start: int, notes: list[str]) -> None:
    for j in range(start, len(history)):
        item = history[j]
        if item.get("role") == "npc" and item.get("speaker") not in NARRATOR_SPEAKERS:
            return
        if item.get("speaker") in NARRATOR_SPEAKERS:
            if item.get("role") == "bridge":
                item["role"] = "narrate"
                notes.append(f"history[{j}]: bridge→narrate")
            return


def fix_opening_roles(history: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """把每场开场铺陈从 bridge 改为 narrate；返回 (新 history, 变更说明)。"""
    if not history:
        return [], []
    out = deepcopy(history)
    notes: list[str] = []
    _fix_segment_opening(out, 0, notes)
    for i, item in enumerate(out):
        if item.get("role") == "bridge":
            _fix_segment_opening(out, i + 1, notes)
    return out, notes


def migrate_session_data(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """迁移单个 session dict；不改正文，只调 role。"""
    payload = deepcopy(data)
    history = list(payload.get("history") or [])
    new_history, notes = fix_opening_roles(history)
    if notes:
        payload["history"] = new_history
    return payload, notes
