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
                "text": "当面把挂坠交到对方手里，再道别——不要再复读照顾",
                "band": "pendant",
            },
            {
                "id": "farewell",
                "text": "交完平常道别，收束这场",
                "band": "close",
            },
        ]
    if "RP2" in done or beats >= 4:
        return [
            {
                "id": "entrust",
                "text": "说清托付与禁名（先张尘、再折原修哉全名；勿传龙也之名）",
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
                "text": "把话题往『临走前有件事』挪一小步（心里更重的是张尘）",
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
            "text": "你先开口：可调侃雨/天气、初遇泼袖或开档身份，口语短接；勿编共史、勿托付、勿交坠",
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
        "rule": "单拍只服务顶格 concern；禁止一次勾完 pending；须承接 prior_reflect 与已说出口的事实",
    }


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
    marriage_cue = any(k in player for k in ("定情", "信物", "结婚", "老婆", "妻子", "婚"))

    thought = ""
    if "RP4" in done:
        thought = "挂坠已经交出去了；分别要像平常一样，别拖成仪式。"
    elif "RP3" in done:
        thought = "托付说清了；下一拍必须把挂坠交到对方手里——不要再把托付重宣一遍。"
    elif "RP2" in done:
        thought = "托付的口已经开了；还要看对方是否接住禁名与照顾的事。"
    elif marriage_cue:
        thought = "对方在拿信物/婚姻开玩笑；我心里有妻子，可淡说已婚，不提名字，用玩笑拨开，别卖惨。"
    elif refused and band in ("entrust", "pendant", "deepen"):
        thought = "对方这一拍在回避；不要纠缠，可换轻松话题，临别前再试。"
    elif spoken and band in ("entrust", "pendant"):
        thought = f"这一拍我推的是「{decide.get('top_concern') or band}」；对方反应还要再看。"
    elif spoken and band in ("idle", "deepen"):
        thought = "这一拍仍是熟人闲聊；别编没写过的共史，心里那件事先压着。"
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


def inject_prior_reflect(
    packet: dict[str, Any],
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    """Close the loop: last beat's private conclusion enters this beat's Decide fuel."""
    if not isinstance(packet, dict) or not isinstance(prior, dict):
        return packet
    thought = str(prior.get("thought") or "").strip()
    if not thought:
        return packet
    loop = packet.get("cog_loop") if isinstance(packet.get("cog_loop"), dict) else {}
    loop = dict(loop)
    loop["prior_reflect"] = {
        "thought": thought,
        "band": prior.get("band"),
        "top_concern_id": prior.get("top_concern_id"),
        "turn_no": prior.get("turn_no"),
    }
    packet["cog_loop"] = loop
    contract = packet.get("conversation_contract") if isinstance(packet.get("conversation_contract"), dict) else {}
    contract = dict(contract)
    contract["prior_reflect_thought"] = thought
    packet["conversation_contract"] = contract
    inner = ((packet.get("self_state") or {}).get("inner_state") or {})
    if isinstance(inner, dict):
        inner = dict(inner)
        inner["prior_reflect"] = thought
        packet.setdefault("self_state", {})["inner_state"] = inner
    return packet


def prologue_stated_public_facts(
    history: list[dict[str, Any]],
    *,
    ledger: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Facts this actor already said aloud — soft continuity, not a hard gate.

    Broader than RP3 receipt: partial「照顾」also sticks, so the loop stops
    re-announcing before both full names + ban land in one beat.
    """
    facts: list[str] = []
    blob = ""
    care_count = 0
    for item in history or []:
        if not isinstance(item, dict) or item.get("role") != "npc":
            continue
        speaker = str(item.get("speaker") or "")
        cons = str(item.get("speaker_cons") or item.get("cons") or "")
        if "龙也" not in speaker and "ryuya" not in cons:
            continue
        text = str(item.get("text") or "")
        blob += text
        care_count += text.count("照顾")
    has_xiuzai = ("折原修哉" in blob) or ("修哉" in blob and "弟" in blob)
    has_zhang = "张尘" in blob
    if has_xiuzai and has_zhang:
        facts.append("已当面提过：张尘与折原修哉——照顾一下；勿再当第一次介绍。")
    elif (has_xiuzai or has_zhang) and ("照顾" in blob or "拜托" in blob):
        facts.append("已提起过照顾对象；勿换皮重宣同一句，补全未说清的全名/禁名或转交坠。")
    if care_count >= 2:
        facts.append("「照顾」已出口多次；禁止再复读，推进禁名收据或交挂坠。")
    if any(k in blob for k in ("名字不能说", "不要把", "会有危险", "会死人", "别告诉")):
        facts.append("已当面说过禁名：不要把龙也的名字告诉他们。")
    if any(k in blob for k in ("挂坠", "项链", "临别")):
        facts.append("挂坠话题已出口或在交涉中。")
    if any(k in blob for k in ("结婚", "已婚", "老婆", "妻子", "好女孩")):
        facts.append("已婚一事已淡提过；勿反复卖惨。")
    for row in ledger or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        if kind == "entrust" and not any("已当面提过" in f for f in facts):
            facts.append("账本已记：托付口径已当面说过；勿再当第一次介绍。")
        if kind == "name_ban_warning" and not any("禁名" in f for f in facts):
            facts.append("账本已记：禁名警告已说出。")
        if kind == "pendant" and not any("挂坠" in f for f in facts):
            facts.append("账本已记：挂坠已交付或在交涉中。")
    return facts


def attach_cog_loop_to_packet(
    packet: dict[str, Any],
    *,
    scene_id: str = "",
    flash_beats: int = 0,
    completed: list[str] | set[str] | None = None,
    prior_reflect: dict[str, Any] | None = None,
    stated_facts: list[str] | None = None,
    player_speech: str = "",
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
        # Soft cue: marriage joke → insert a touch concern above idle chatter.
        if any(k in str(player_speech or "") for k in ("定情", "信物", "结婚", "老婆", "妻子")):
            concerns = [
                {
                    "id": "married_soft",
                    "text": "可淡提已婚并玩笑拨开，不提妻名、不卖惨",
                    "band": "idle",
                },
                *concerns,
            ]
        if stated_facts:
            # If entrust / care already spoken, stop re-checklist even if MH lagging.
            joined = "\n".join(stated_facts)
            done_set = {str(x) for x in (completed or [])}
            care_stuck = any(
                k in joined
                for k in ("已当面提过", "已提起过照顾", "照顾」已出口", "账本已记：托付")
            )
            if care_stuck and "RP4" not in done_set:
                concerns = [
                    {
                        "id": "no_reannounce",
                        "text": "照顾/托付已出口；禁止换皮重宣，接禁名或交挂坠",
                        "band": "pendant" if "RP3" in done_set or "已当面提过" in joined else "entrust",
                    },
                    *concerns,
                ]
    elif want:
        concerns = [{"id": "want", "text": want, "band": "scene"}]

    decide = decide_from_concerns(concerns, want_now=want, participation_mode=mode)
    packet["cog_loop"] = {
        "decide": decide,
        "reflect": packet.get("cog_loop", {}).get("reflect") if isinstance(packet.get("cog_loop"), dict) else None,
    }
    if stated_facts:
        packet["cog_loop"]["stated_public_facts"] = list(stated_facts)
        contract = dict(contract)
        contract["stated_public_facts"] = list(stated_facts)
        packet["conversation_contract"] = contract
    # Soft cafe anchors (not a hard invent gate): feed Decide/instruction.
    if "ryuya" in cons and ("prologue" in str(scene_id).lower() or "OPENING_RYUYA" in str(scene_id)):
        packet["cog_loop"]["shared_past_anchors"] = [
            "雨夜咖啡馆",
            "靠窗旧桌",
            "初遇泼袖赔一杯",
            "两年偶遇熟人",
        ]
    if isinstance(inner, dict):
        inner = dict(inner)
        inner["pending_concerns"] = list(decide.get("pending_concerns") or [])
        inner["top_concern"] = decide.get("top_concern")
        packet.setdefault("self_state", {})["inner_state"] = inner
    if prior_reflect:
        inject_prior_reflect(packet, prior_reflect)
    return packet

