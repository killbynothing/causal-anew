"""Declarative beat→evidence registry for Resolver-A (evidence-first accounting).

The director never reports must_happen completion; only visible evidence does.
Each registered beat maps to a deterministic predicate over a plain evidence
context that the production path packs (history / turns / branch_progress /
receipts / precomputed evidence flags). Beats without a registered predicate
fall back to the legacy model-hint path until they are registered.

Pure module: no Session or live refs, no import of free_stage_prototype. The
production path computes the strong existing checks (``turns_cover_ryuya_entrust``
etc.) and passes them in ``evidence_flags`` so the registry cannot drift from the
hand-tuned gates that already run.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

EvidenceFn = Callable[[Mapping[str, Any]], bool]


def _blob(rows: Any) -> str:
    parts: list[str] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("text") or ""))
        parts.append(str(item.get("stage") or ""))
    return re.sub(r"\s+", "", "".join(parts))


def _flag(ctx: Mapping[str, Any], key: str, default: Any = False) -> Any:
    flags = ctx.get("evidence_flags")
    if isinstance(flags, dict):
        return flags.get(key, default)
    return default


def _npcs_mention(ctx: Mapping[str, Any], tokens: tuple[str, ...]) -> bool:
    blob = _blob(list(ctx.get("history") or []) + list(ctx.get("turns") or []))
    return bool(blob) and any(token in blob for token in tokens)


# --- predicates ---------------------------------------------------------

def _rp1_chatted(ctx: Mapping[str, Any]) -> bool:
    """开场闲聊已发生：至少一拍玩家已接话（引擎已驱动）。"""
    return bool(_flag(ctx, "rp1_chatted", False)) or bool(ctx.get("history"))


def _rp2_toward_entrust(ctx: Mapping[str, Any]) -> bool:
    """谈话已自然转向放不下的事：托付已出口 / 话题接口命中 / 闲聊已两拍。"""
    if _flag(ctx, "rp3_entrust", False) or _flag(ctx, "topic_interface", False) or _flag(ctx, "rp2_nudged", False):
        return True
    return bool(_flag(ctx, "flash_beats", 0) or 0) >= 2


def _rp3_entrust(ctx: Mapping[str, Any]) -> bool:
    """当面托付已说清（全名 + 照顾 + 禁名），只认可见台词。"""
    return bool(_flag(ctx, "rp3_entrust", False))


def _tm1_played(ctx: Mapping[str, Any]) -> bool:
    """开场声场已建立（引擎驱动的开幕，场景已开口）。"""
    return bool(_flag(ctx, "tm1_played", False)) or bool(ctx.get("history"))


def _tm2_video(ctx: Mapping[str, Any]) -> bool:
    """借视频请求或“没有录到”已落在可见层。"""
    return bool(_flag(ctx, "tm2_visible", False))


def _tm3_intro(ctx: Mapping[str, Any]) -> bool:
    """修哉全名已落到玩家可见层。"""
    return bool(_flag(ctx, "tm3_intro", False))


def _tm4_aquarium(ctx: Mapping[str, Any]) -> bool:
    """秋人已提出海洋馆这一可选去处（可见台词）。"""
    if _flag(ctx, "tm4_aquarium", False):
        return True
    return _npcs_mention(ctx, ("海洋馆", "海族馆", "水族馆"))


BEAT_EVIDENCE: dict[str, EvidenceFn] = {
    "RP1": _rp1_chatted,
    "RP2": _rp2_toward_entrust,
    "RP3": _rp3_entrust,
    "TM1": _tm1_played,
    "TM2": _tm2_video,
    "TM3": _tm3_intro,
    "TM4": _tm4_aquarium,
}


def after_map(card: Mapping[str, Any] | None) -> dict[str, set[str]]:
    """Read the card's ``must_happen[*].after`` prerequisites. Plain data."""
    out: dict[str, set[str]] = {}
    if not isinstance(card, dict):
        return out
    for item in card.get("must_happen", []) or []:
        if not isinstance(item, dict):
            continue
        beat = str(item.get("id") or "").strip()
        if not beat:
            continue
        out[beat] = {
            str(x or "").strip()
            for x in (item.get("after") or [])
            if str(x or "").strip()
        }
    return out


def resolve_completions(
    ctx: Mapping[str, Any],
    *,
    allowed: set[str] | None = None,
    completed: set[str] | None = None,
    after: Mapping[str, set[str]] | None = None,
) -> list[str]:
    """Beats whose evidence holds, not completed, and prerequisites done.

    A later beat's evidence also implies its ``after`` prerequisites are done
    (e.g. the entrust being said implies the conversation already turned toward
    it), so those prereqs are completed too rather than leaving a gap in the
    ledger. Order is deterministic: BEAT_EVIDENCE registration order.
    """
    done = set(completed or ())
    gates = dict(after) if after is not None else after_map(ctx.get("card"))
    ordered: list[str] = []
    for beat, predicate in BEAT_EVIDENCE.items():
        if allowed is not None and beat not in allowed:
            continue
        if beat in done or beat in ordered:
            continue
        prereq = gates.get(beat) or set()
        if prereq - (done | set(ordered)):
            continue
        try:
            if predicate(ctx):
                ordered.append(beat)
        except Exception:
            continue
    # Implied prerequisites: later-beat evidence implies earlier beats happened.
    result: list[str] = list(ordered)
    for beat in list(ordered):
        for prereq in gates.get(beat, set()):
            if allowed is not None and prereq not in allowed:
                continue
            if prereq not in done and prereq not in result:
                result.append(prereq)
    order_index = {b: i for i, b in enumerate(BEAT_EVIDENCE)}
    result.sort(key=lambda b: order_index.get(b, len(order_index)))
    return result
