# -*- coding: utf-8 -*-
"""Player thought → director-only delta / run observation ledger (NPCs do not hear)."""
from __future__ import annotations

import re
from typing import Any

from runtime import name_book as nb
from runtime.run_observation_ledger import append_observation

_REALIZATION_MARKERS = (
    "原来", "意识到", "才明白", "没想到", "懂了", "理解了", "察觉", "忽然想",
    "会不会", "难道", "可疑", "不对劲", "有问题",
)

_PERSON_WEIGHT_MARKERS = (
    ("龙也", "ryuya", 8),
    ("修哉", "xiuzai", 7),
    ("张尘", "zhangchen", 7),
    ("秋人", "akito", 5),
    ("晴明", "kakashi", 6),
    ("卡卡西", "kakashi", 6),
    ("真纪", "maki", 5),
    ("挂坠", "pendant", 8),
    ("项链", "pendant", 7),
    ("托付", "entrust", 9),
    ("因果", "causal", 6),
    ("组织", "org_hint", 7),
)

_TRUST_MARKERS = ("信任", "怀疑", "重要", "危险", "会死人", "不能信", "可以信")


def _clip(text: str, n: int = 120) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    return t[:n] + ("…" if len(t) > n else "")


def ingest_player_thought(
    thought: str,
    *,
    ledger: list[dict[str, Any]] | None,
    turn: int,
    scene_id: str = "",
    session_id: str = "",
    run_id: int | str = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (updated_ledger, delta_rows_for_director)."""
    text = str(thought or "").strip()
    if not text:
        return list(ledger or []), []
    out = list(ledger or [])
    director_rows: list[dict[str, Any]] = []
    base = _clip(text, 200)

    if any(m in text for m in _REALIZATION_MARKERS):
        out = append_observation(
            out,
            kind="player_realization",
            fact_text=f"【玩家内心·觉察】{base}",
            turn=turn,
            scene_id=scene_id,
            session_id=session_id,
            run_id=run_id,
            extra={"channel": "player_thought", "visibility": "director_only"},
        )
        director_rows.append({"kind": "player_realization", "text": base})

    for token, kind, imp in _PERSON_WEIGHT_MARKERS:
        if token in text:
            out = append_observation(
                out,
                kind=kind,
                fact_text=f"【玩家内心·权重】提到「{token}」：{base}",
                turn=turn,
                scene_id=scene_id,
                session_id=session_id,
                run_id=run_id,
                extra={
                    "channel": "player_thought",
                    "visibility": "director_only",
                    "importance0": imp,
                    "importance": imp,
                },
            )
            director_rows.append({"kind": kind, "token": token, "importance": imp})

    if any(m in text for m in _TRUST_MARKERS):
        out = append_observation(
            out,
            kind="player_stance",
            fact_text=f"【玩家内心·立场】{base}",
            turn=turn,
            scene_id=scene_id,
            session_id=session_id,
            run_id=run_id,
            extra={"channel": "player_thought", "visibility": "director_only"},
        )
        director_rows.append({"kind": "player_stance", "text": base})

    # Name-book cons hint for director graph (no NPC leak).
    for cons in ("C.ryuya.W1", "C.xiuzai.WMAIN", "C.akito.WMAIN", "C.kakashi.WMAIN"):
        for alias in nb.all_aliases(cons):
            if alias and len(alias) >= 2 and alias in text:
                out = append_observation(
                    out,
                    kind="player_focus",
                    fact_text=f"【玩家内心·关注】{alias}（{cons}）",
                    turn=turn,
                    scene_id=scene_id,
                    session_id=session_id,
                    run_id=run_id,
                    extra={"channel": "player_thought", "cons": cons, "visibility": "director_only"},
                )
                break

    if not director_rows:
        out = append_observation(
            out,
            kind="player_thought",
            fact_text=f"【玩家内心】{base}",
            turn=turn,
            scene_id=scene_id,
            session_id=session_id,
            run_id=run_id,
            extra={"channel": "player_thought", "visibility": "director_only"},
        )
        director_rows.append({"kind": "player_thought", "text": base})

    return out, director_rows
