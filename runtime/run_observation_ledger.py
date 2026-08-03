# -*- coding: utf-8 -*-
"""Run-scoped director observation ledger (not world_truth.db).

Append-only facts with seed importance; later causal links boost importance.
Silent recording — never a "please record this beat" actor prompt.
"""
from __future__ import annotations

import hashlib
from typing import Any

IMPORTANCE0: dict[str, int] = {
    "video_lent": 8,
    "video_unavailable": 7,
    "japanese_understood": 5,
    "name_bound": 7,
    "entrust": 9,
    "pendant": 9,
    "name_ban_warning": 6,
    "default": 2,
}

KIND_BY_FACT_ID: dict[str, str] = {
    "tiananmen_video_offered": "video_lent",
    "tiananmen_video_unavailable": "video_unavailable",
    "tiananmen_japanese_understood": "japanese_understood",
    "ryuya_pendant_disposition": "pendant",
}


def seed_importance(kind: str) -> int:
    return int(IMPORTANCE0.get(str(kind), IMPORTANCE0["default"]))


def make_observation_id(kind: str, fact_text: str, *, scene_id: str = "") -> str:
    raw = f"{kind}|{scene_id}|{fact_text.strip()}"
    return "obs_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def append_observation(
    ledger: list[dict[str, Any]] | None,
    *,
    kind: str,
    fact_text: str,
    turn: int = 0,
    scene_id: str = "",
    session_id: str = "",
    run_id: int | str = 1,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Idempotent append by observation id. Returns the ledger (mutated copy-safe)."""
    out = list(ledger or [])
    text = str(fact_text or "").strip()
    if not text:
        return out
    kind_s = str(kind or "default").strip() or "default"
    oid = make_observation_id(kind_s, text, scene_id=str(scene_id or ""))
    for row in out:
        if str(row.get("id") or "") == oid:
            return out
    imp0 = seed_importance(kind_s)
    row: dict[str, Any] = {
        "id": oid,
        "turn": int(turn or 0),
        "scene_id": str(scene_id or ""),
        "fact_text": text,
        "kind": kind_s,
        "importance0": imp0,
        "importance": imp0,
        "caused_by": [],
        "session_id": str(session_id or ""),
        "run_id": run_id,
    }
    if isinstance(extra, dict):
        row.update({k: v for k, v in extra.items() if k not in row})
    out.append(row)
    return out


def boost_importance(
    ledger: list[dict[str, Any]] | None,
    obs_id: str,
    amount: int,
    *,
    caused_by_event: str = "",
) -> list[dict[str, Any]]:
    out = [dict(row) for row in (ledger or [])]
    target = str(obs_id or "").strip()
    if not target:
        return out
    for row in out:
        if str(row.get("id") or "") != target:
            continue
        row["importance"] = int(row.get("importance") or row.get("importance0") or 0) + int(amount)
        links = list(row.get("caused_by") or [])
        ev = str(caused_by_event or "").strip()
        if ev and ev not in links:
            links.append(ev)
        row["caused_by"] = links
        break
    return out


def find_by_kind(ledger: list[dict[str, Any]] | None, kind: str) -> list[dict[str, Any]]:
    k = str(kind or "").strip()
    return [dict(row) for row in (ledger or []) if str(row.get("kind") or "") == k]


def high_importance_facts(
    ledger: list[dict[str, Any]] | None,
    *,
    min_importance: int = 6,
) -> list[str]:
    rows = sorted(
        (row for row in (ledger or []) if int(row.get("importance") or 0) >= min_importance),
        key=lambda r: (-int(r.get("importance") or 0), int(r.get("turn") or 0)),
    )
    return [str(r.get("fact_text") or "") for r in rows if str(r.get("fact_text") or "").strip()]


def append_from_branch_fact(
    ledger: list[dict[str, Any]] | None,
    fact_id: str,
    *,
    turn: int = 0,
    scene_id: str = "",
    session_id: str = "",
) -> list[dict[str, Any]]:
    kind = KIND_BY_FACT_ID.get(str(fact_id))
    if not kind:
        return list(ledger or [])
    texts = {
        "video_lent": "玩家已答应提供升旗视频；本场借视频请求已收下。",
        "video_unavailable": "玩家明确说没有录到升旗视频；本场视频线已结束。",
        "japanese_understood": "玩家听得懂日语；语言发现已落地。",
        "pendant": "古铜色挂坠已作为临别礼物交到玩家手上。",
    }
    return append_observation(
        ledger,
        kind=kind,
        fact_text=texts.get(kind, str(fact_id)),
        turn=turn,
        scene_id=scene_id,
        session_id=session_id,
    )
