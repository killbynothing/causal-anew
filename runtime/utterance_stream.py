# -*- coding: utf-8 -*-
"""Dual-lane utterance stream: floor (player-facing) + companion (HOLD side/backchannel)."""
from __future__ import annotations

import copy
from typing import Any

from runtime import social_participation as soc

_STREAM_ROLES = frozenset({"npc", "bridge", "narrate"})
_COMPANION_MODES = frozenset({"backchannel", "side"})


def is_stream_visible_turn(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    role = str(item.get("role") or "")
    if role not in _STREAM_ROLES:
        return False
    if item.get("player_visible") is False:
        return False
    return bool(str(item.get("text") or "").strip() or str(item.get("stage") or "").strip())


def normalize_stream_turn(item: dict[str, Any], *, turn_no: int) -> dict[str, Any]:
    out = copy.deepcopy(item)
    out.setdefault("role", "npc")
    out["turn"] = int(turn_no)
    out.setdefault("stream", True)
    mode = str(out.get("participation_mode") or "").strip()
    lane = str(out.get("stream_lane") or "").strip()
    if not lane:
        lane = "companion" if mode in _COMPANION_MODES else "floor"
    out["stream_lane"] = lane
    if mode:
        out["participation_mode"] = mode
    return out


def lane_of_turn(item: dict[str, Any], speaker_plan: dict[str, Any] | None = None) -> str:
    if not isinstance(item, dict):
        return "floor"
    explicit = str(item.get("stream_lane") or "").strip()
    if explicit in ("floor", "companion"):
        return explicit
    mode = str(item.get("participation_mode") or "").strip()
    if mode in _COMPANION_MODES:
        return "companion"
    slot = str(item.get("response_slot") or "").strip()
    if slot in ("backchannel", "side"):
        return "companion"
    cons = str(item.get("cons") or item.get("speaker_cons") or "").strip()
    if cons and speaker_plan:
        companion_cons = {
            str(row.get("cons") or "")
            for key in ("backchannel_actors", "side_actors", "companion_actors")
            for row in (speaker_plan.get(key) or [])
            if isinstance(row, dict)
        }
        if cons in companion_cons:
            return "companion"
    return "floor"


def route_turns_by_lane(
    turns: list[dict[str, Any]],
    speaker_plan: dict[str, Any] | None = None,
    *,
    turn_no: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    floor: list[dict[str, Any]] = []
    companion: list[dict[str, Any]] = []
    for raw in turns:
        if not is_stream_visible_turn(raw):
            continue
        item = normalize_stream_turn(raw, turn_no=turn_no)
        lane = lane_of_turn(item, speaker_plan)
        item["stream_lane"] = lane
        if lane == "companion":
            companion.append(item)
        else:
            floor.append(item)
    return floor, companion


def synthesize_companion_line(
    cons: str,
    card: dict[str, Any],
    *,
    turn_no: int,
    participation_mode: str = "backchannel",
) -> dict[str, Any] | None:
    personas = card.get("persona_cards") if isinstance(card.get("persona_cards"), dict) else {}
    persona = personas.get(cons) if isinstance(personas.get(cons), dict) else {}
    name = str(persona.get("name") or cons)
    mode = str(participation_mode or "backchannel").strip()
    if mode == "side":
        samples = {
            "C.xiuzai.WMAIN": ("行了行了，别把人吓跑。", "你那单反又闯祸了吧。"),
            "C.akito.WMAIN": ("我、我不是故意的……", "修哉你别拆台。"),
            "C.kakashi.WMAIN": ("……", "嗯。"),
        }
    else:
        style = soc.participation_style(cons)
        if style not in ("backchannel_preferred", "mixed"):
            return None
        samples = {
            "C.kakashi.WMAIN": ("嗯。", "没事吧。"),
            "C.xiuzai.WMAIN": ("行了行了。", "别闹。"),
            "C.akito.WMAIN": ("啊……", "不好意思。"),
        }
    text = samples.get(cons, ("嗯。",))[0]
    return normalize_stream_turn(
        {
            "role": "npc",
            "speaker": name,
            "cons": cons,
            "text": text,
            "stage": "",
            "participation_mode": mode,
            "stream_lane": "companion",
            "synthetic_fallback": True,
        },
        turn_no=turn_no,
    )


def synthesize_companion_backchannel(
    cons: str,
    card: dict[str, Any],
    *,
    turn_no: int,
) -> dict[str, Any] | None:
    return synthesize_companion_line(cons, card, turn_no=turn_no, participation_mode="backchannel")


def enrich_turns_with_companion_queue(
    turns: list[dict[str, Any]],
    speaker_plan: dict[str, Any] | None,
    card: dict[str, Any],
    *,
    turn_no: int,
) -> list[dict[str, Any]]:
    """LLM-first companion fill; synthetic only if planned companion cons stayed silent."""
    out = [dict(t) for t in turns if isinstance(t, dict)]
    spoken_cons: set[str] = set()
    for item in out:
        c = str(item.get("cons") or item.get("speaker_cons") or "").strip()
        if c:
            spoken_cons.add(c)
        # Stamp lane if missing.
        if not item.get("stream_lane"):
            item["stream_lane"] = lane_of_turn(item, speaker_plan)

    plan = speaker_plan or {}
    companion_rows = list(plan.get("companion_actors") or [])
    if not companion_rows:
        companion_rows = list(plan.get("side_actors") or []) + list(plan.get("backchannel_actors") or [])

    for row in companion_rows:
        if not isinstance(row, dict):
            continue
        cons = str(row.get("cons") or "").strip()
        if not cons or cons in spoken_cons:
            continue
        mode = str(row.get("participation_mode") or row.get("response_slot") or "backchannel")
        # Prefer silent LLM path; synthetic is last-resort degradation only.
        synth = synthesize_companion_line(cons, card, turn_no=turn_no, participation_mode=mode)
        if synth:
            out.append(synth)
            spoken_cons.add(cons)
            break  # at most one synthetic companion line per step
    return out


def split_for_stream(
    turns: list[dict[str, Any]],
    *,
    turn_no: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    visible = [normalize_stream_turn(t, turn_no=turn_no) for t in turns if is_stream_visible_turn(t)]
    if not visible:
        return None, []
    return visible[0], visible[1:]


def stream_status(
    queue: list[dict[str, Any]] | None,
    *,
    hold: bool,
    generation: int,
    companion_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    q = list(queue or [])
    cq = list(companion_queue or [])
    return {
        "queue_remaining": len(q),
        "floor_queue_remaining": len(q),
        "companion_queue_remaining": len(cq),
        "stream_hold": bool(hold),
        "generation": int(generation or 0),
        "awaiting_player": len(q) == 0,
        "can_advance": bool(q) and not hold,
        "dual_lane": True,
    }
