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
    pacing_signal: dict[str, Any] | None = None,
    stated_facts: list[str] | None = None,
) -> list[dict[str, str]]:
    """Ordered open concerns for the cafe flashback (top = current intent)."""
    done = {str(x) for x in (completed or [])}
    beats = max(0, int(flash_beats or 0))
    pacing_mode = str((pacing_signal or {}).get("mode") or "neutral").strip() or "neutral"
    facts = [str(x) for x in (stated_facts or []) if str(x).strip()]
    if "RP4" in done:
        if pacing_mode == "close":
            return [
                {
                    "id": "farewell",
                    "text": "玩家已经给出离场信号；平常道别，不重宣托付",
                    "band": "close",
                }
            ]
        return [
            {
                "id": "post_entrust_chat",
                "text": "正事已经交代完；玩家若继续聊，就回到朋友之间的当下，顺着对方话题，不复读托付，也不主动催离",
                "band": "idle",
            }
        ]
    if "RP3" in done:
        if any("挂坠已明确递出" in f or "等待对方回应" in f for f in facts):
            return [
                {
                    "id": "await_pendant_response",
                    "text": "挂坠已经明确递到对方面前；顺着对方这一拍回应，不重复递、不催收，也不要替对方决定收不收",
                    "band": "pendant",
                }
            ]
        return [
            {
                "id": "offer_pendant",
                "text": "先用一句人话明确点出这枚挂坠是给对方的临别礼物，再把它递到对方这边；不要只写动作，不要擅自塞进对方手里。说完停住，等对方回应",
                "band": "pendant",
            }
        ]
    # Director owns timing: a joking/deflecting player line may not be promoted
    # into a serious entrust merely because the beat counter is high.
    if pacing_mode == "hold" and "RP2" not in done:
        return [
            {
                "id": "hold_banter",
                "text": "先接住对方这一拍的轻口吻或回避；别把玩笑当认真邀请，正事最多挪近一小步",
                "band": "deepen" if beats >= 2 else "idle",
            },
            {
                "id": "deepen",
                "text": "等对方真的给出认真说事的空间，再把话题往临走前那件事挪",
                "band": "deepen",
            },
        ]

    # Care portraits already spoken but ban/MH lag → only push 禁名 or 交坠, never re-list.
    # (Caller may pass stated via attach; here we only have completed.)
    if "RP2" in done:
        return [
            {
                "id": "entrust",
                "text": "说清托付与禁名（先张尘、再折原修哉全名；勿传龙也之名）——若已点过名，本拍只补禁名，勿重念画像",
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
    pendant_disposition: str = "",
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
    pendant = str(pendant_disposition or "").strip()
    if pendant == "accepted":
        thought = "对方已经明确收下挂坠；去向已由世界收据结算，分别照常聊，不再重复递交。"
    elif pendant == "declined":
        thought = "对方已经明确不收挂坠；别追着再塞，也别把拒绝改写成接受，先回到正常谈话。"
    elif pendant == "deferred":
        thought = "对方暂时没有收下挂坠；先把这件事放下，别追问、别替对方决定后续去向。"
    elif "RP4" in done:
        thought = "RP4 已有兼容进度标记，但挂坠去向没有可引用的世界收据；不要自行补成已交付。"
    elif "RP3" in done:
        thought = "托付说清了；挂坠若要赠与，只能明确递出后等对方回应，不能替对方收下，也不要重宣托付。"
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
        if kind == "pendant_offer" and not any("挂坠已明确递出" in f for f in facts):
            facts.append("账本已记：挂坠已明确递出，正在等待对方回应；勿重复递交。")
        if kind == "pendant" and not any("挂坠" in f for f in facts):
            facts.append("账本已记：挂坠去向已结算。")
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
    pacing_signal: dict[str, Any] | None = None,
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
        concerns = ryuya_prologue_concerns(
            flash_beats=flash_beats,
            completed=completed,
            pacing_signal=pacing_signal,
            stated_facts=stated_facts,
        )
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
                if "已当面提过" in joined or "账本已记：托付" in joined:
                    top = {
                        "id": "no_reannounce",
                        "text": "托付已出口；禁止换皮重宣画像；只补禁名（若未说）或交挂坠",
                        "band": "pendant" if "RP3" in done_set else "entrust",
                    }
                else:
                    top = {
                        "id": "no_reannounce",
                        "text": "照顾已出口；禁止换皮重宣，接禁名或交挂坠",
                        "band": "entrust",
                    }
                concerns = [top, *concerns]
    elif want:
        concerns = [{"id": "want", "text": want, "band": "scene"}]

    decide = decide_from_concerns(concerns, want_now=want, participation_mode=mode)
    packet["cog_loop"] = {
        "decide": decide,
        "reflect": packet.get("cog_loop", {}).get("reflect") if isinstance(packet.get("cog_loop"), dict) else None,
    }
    if pacing_signal:
        packet["cog_loop"]["pacing_signal"] = dict(pacing_signal)
        contract = dict(contract)
        contract["pacing_signal"] = dict(pacing_signal)
        packet["conversation_contract"] = contract
    if stated_facts:
        packet["cog_loop"]["stated_public_facts"] = list(stated_facts)
        contract = dict(contract)
        contract["stated_public_facts"] = list(stated_facts)
        packet["conversation_contract"] = contract
    # Soft cafe anchors: rotate a tiny subset so the same four motifs are not
    # re-injected every beat. These are reference anchors, never lines to copy.
    if "ryuya" in cons and ("prologue" in str(scene_id).lower() or "OPENING_RYUYA" in str(scene_id)):
        anchor_catalog = [
            "雨夜咖啡馆",
            "靠窗旧桌",
            "初遇泼袖赔一杯",
            "两年偶遇熟人",
        ]
        anchor_sets = (
            ("雨夜咖啡馆", "初遇泼袖赔一杯"),
            ("靠窗旧桌", "两年偶遇熟人"),
            ("初遇泼袖赔一杯", "两年偶遇熟人"),
        )
        packet["cog_loop"]["shared_past_anchor_catalog"] = anchor_catalog
        packet["cog_loop"]["shared_past_anchors"] = list(
            anchor_sets[max(0, int(flash_beats or 0)) % len(anchor_sets)]
        )
    if isinstance(inner, dict):
        inner = dict(inner)
        inner["pending_concerns"] = list(decide.get("pending_concerns") or [])
        inner["top_concern"] = decide.get("top_concern")
        packet.setdefault("self_state", {})["inner_state"] = inner
    if prior_reflect:
        inject_prior_reflect(packet, prior_reflect)
    return packet

