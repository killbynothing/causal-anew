# -*- coding: utf-8 -*-
"""Actor cognitive loop (Generative-Agents-inspired) for narrative free_stage.

Only the character half: Perceive/Retrieve stay in packet assembly;
this module adds Decide → (Enact via LLM) → Reflect writeback.
Town/maze/daily schedule are intentionally absent.
"""
from __future__ import annotations

from typing import Any


def ryuya_prologue_concerns(
    *,
    flash_beats: int,
    completed: list[str] | set[str] | None = None,
) -> list[dict[str, str]]:
    """Ordered open concerns for the cafe flashback (top = current intent)."""
    done = {str(x) for x in (completed or [])}
    beats = max(0, int(flash_beats or 0))
    if "RP4" in done:
        return [
            {
                "id": "farewell",
                "text": "平常道别，收束这场见面",
                "band": "close",
            }
        ]
    if "RP3" in done:
        return [
            {
                "id": "hand_pendant",
                "text": "当面把挂坠交到对方手里，再道别",
                "band": "pendant",
            },
            {
                "id": "farewell",
                "text": "交完再道别",
                "band": "close",
            },
        ]
    if "RP2" in done or beats >= 4:
        return [
            {
                "id": "entrust",
                "text": "说清托付与禁名（修哉/张尘全名；勿传龙也之名）",
                "band": "entrust",
            },
            {
                "id": "hand_pendant",
                "text": "说完再交挂坠",
                "band": "pendant",
            },
        ]
    if beats >= 2:
        return [
            {
                "id": "deepen",
                "text": "把话题往『临走前有件事』挪一小步",
                "band": "deepen",
            },
            {
                "id": "entrust",
                "text": "稍后才说清托付",
                "band": "entrust",
            },
        ]
    if beats >= 1:
        return [
            {
                "id": "banter",
                "text": "接住对方；可轻渗初遇泼袖或开档近况，勿编共史、勿急托付",
                "band": "idle",
            },
            {
                "id": "deepen",
                "text": "别原地复读近况太久",
                "band": "deepen",
            },
        ]
    return [
        {
            "id": "presence",
            "text": "平日见面；可轻轻带初遇泼袖或开档身份，勿简历式复述",
            "band": "idle",
        }
    ]


def decide_from_concerns(
    concerns: list[dict[str, str]],
    *,
    want_now: str = "",
    participation_mode: str = "speak",
) -> dict[str, Any]:
    """Produce a Decide receipt (maps to observer + instruction)."""
    top = concerns[0] if concerns else {
        "id": "observe",
        "text": "观察并自然接话",
        "band": "idle",
    }
    pending = concerns[1:]
    mode = str(participation_mode or "speak").strip() or "speak"
    return {
        "top_concern_id": top.get("id"),
        "top_concern": top.get("text"),
        "band": top.get("band"),
        "pending_concerns": [c.get("text") for c in pending if c.get("text")],
        "participation_mode": mode,
        "intention": str(want_now or top.get("text") or "").strip(),
        "rule": "单拍只服务顶格 concern；禁止一次勾完 pending",
    }


def attach_cog_loop_to_packet(
    packet: dict[str, Any],
    *,
    scene_id: str = "",
    flash_beats: int = 0,
    completed: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Stamp cog_loop.decide onto an actor packet (prologue-aware)."""
    cons = str(packet.get("actor_cons") or "")
    contract = packet.get("conversation_contract") if isinstance(packet.get("conversation_contract"), dict) else {}
    mode = str(contract.get("participation_mode") or "speak").strip() or "speak"
    want = ""
    inner = ((packet.get("self_state") or {}).get("inner_state") or {})
    if isinstance(inner, dict):
        want = str(inner.get("want_now") or "").strip()

    concerns: list[dict[str, str]] = []
    if "ryuya" in cons and ("prologue" in str(scene_id).lower() or "OPENING_RYUYA" in str(scene_id)):
        concerns = ryuya_prologue_concerns(flash_beats=flash_beats, completed=completed)
    elif want:
        concerns = [{"id": "want", "text": want, "band": "scene"}]

    decide = decide_from_concerns(concerns, want_now=want, participation_mode=mode)
    packet["cog_loop"] = {
        "decide": decide,
        "reflect": packet.get("cog_loop", {}).get("reflect") if isinstance(packet.get("cog_loop"), dict) else None,
    }
    # Surface pending for observer / future RelState without checklisting want_now.
    if isinstance(inner, dict):
        inner = dict(inner)
        inner["pending_concerns"] = list(decide.get("pending_concerns") or [])
        inner["top_concern"] = decide.get("top_concern")
        packet.setdefault("self_state", {})["inner_state"] = inner
    return packet


def build_reflect_thought(
    *,
    cons_id: str,
    decide: dict[str, Any] | None,
    spoken_texts: list[str],
    player_speech: str = "",
    completed_after: list[str] | set[str] | None = None,
) -> dict[str, Any] | None:
    """Minimal reflection: one private conclusion when the beat moved."""
    done = {str(x) for x in (completed_after or [])}
    decide = decide or {}
    band = str(decide.get("band") or "")
    player = str(player_speech or "").strip()
    refused = any(k in player for k in ("不", "拒绝", "不要", "算了", "没空"))
    spoken = " / ".join(t for t in spoken_texts if t)[:160]

    thought = ""
    if "RP4" in done:
        thought = "挂坠已经交出去了；分别要像平常一样，别拖成仪式。"
    elif "RP3" in done:
        thought = "托付说清了；下一拍必须把挂坠交到对方手里。"
    elif "RP2" in done:
        thought = "托付的口已经开了；还要看对方是否接住禁名与照顾的事。"
    elif refused and band in ("entrust", "pendant", "deepen"):
        thought = "对方这一拍在回避；不要纠缠，可换轻松话题，临别前再试。"
    elif spoken and band in ("entrust", "pendant"):
        thought = f"这一拍我推的是「{decide.get('top_concern') or band}」；对方反应还要再看。"
    if not thought:
        return None
    return {
        "cons_id": cons_id,
        "thought": thought,
        "band": band,
        "top_concern_id": decide.get("top_concern_id"),
        "evidence": spoken[:120],
    }


def stamp_reflect_on_packet(packet: dict[str, Any], reflect: dict[str, Any] | None) -> None:
    if not reflect:
        return
    loop = packet.get("cog_loop") if isinstance(packet.get("cog_loop"), dict) else {}
    loop = dict(loop)
    loop["reflect"] = reflect
    packet["cog_loop"] = loop
