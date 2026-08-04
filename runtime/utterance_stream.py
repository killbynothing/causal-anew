# -*- coding: utf-8 -*-
"""One visible utterance at a time; hold on typing; barge-in on public say/do."""
from __future__ import annotations

import copy
from typing import Any

from runtime import social_participation as soc

_STREAM_ROLES = frozenset({"npc", "bridge", "narrate"})


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
    return out


def synthesize_companion_backchannel(
    cons: str,
    card: dict[str, Any],
    *,
    turn_no: int,
) -> dict[str, Any] | None:
    personas = card.get("persona_cards") if isinstance(card.get("persona_cards"), dict) else {}
    persona = personas.get(cons) if isinstance(personas.get(cons), dict) else {}
    name = str(persona.get("name") or cons)
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
            "participation_mode": "backchannel",
        },
        turn_no=turn_no,
    )


def enrich_turns_with_companion_queue(
    turns: list[dict[str, Any]],
    speaker_plan: dict[str, Any] | None,
    card: dict[str, Any],
    *,
    turn_no: int,
) -> list[dict[str, Any]]:
    """If LLM did not speak for backchannel-eligible cons, add a short synthetic line."""
    out = [dict(t) for t in turns if isinstance(t, dict)]
    spoken_cons: set[str] = set()
    for item in out:
        c = str(item.get("cons") or item.get("speaker_cons") or "").strip()
        if c:
            spoken_cons.add(c)
    for row in speaker_plan.get("backchannel_actors") or []:
        if not isinstance(row, dict):
            continue
        cons = str(row.get("cons") or "").strip()
        if not cons or cons in spoken_cons:
            continue
        synth = synthesize_companion_backchannel(cons, card, turn_no=turn_no)
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
) -> dict[str, Any]:
    q = list(queue or [])
    return {
        "queue_remaining": len(q),
        "stream_hold": bool(hold),
        "generation": int(generation or 0),
        "awaiting_player": len(q) == 0,
        "can_advance": bool(q) and not hold,
    }
