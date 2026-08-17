# -*- coding: utf-8 -*-
"""Global social participation: floor eligibility, concern queues, character habits.

See design/社交参与与自主决策备忘_活人话轮×礼貌×floor_2026-08-04.md
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Per-character social habit (global · usable in any scene)
# ---------------------------------------------------------------------------

SOCIAL_PARTICIPATION: dict[str, dict[str, str]] = {
    "C.xiuzai.WMAIN": {
        "participation_style": "mixed",
        "with_stranger": (
            "对陌生人：半开玩笑、编排场面，但一次只推进一个话题；"
            "不盘问、不立誓；该同伴自己开口时你不包办。"
        ),
        "with_companion": "对秋人损友可拍肩圆场，对晴明留意异样但不当众戳穿。",
        "default_move": "speak",
        "backchannel_ok": "可短损一句或摊手反应。",
    },
    "C.akito.WMAIN": {
        "participation_style": "speak",
        "with_stranger": (
            "对陌生人：实诚、先处理眼前尴尬；"
            "道歉、发现语言、提请求、自报姓名——分开说，不要捆成一句。"
        ),
        "with_companion": "对修哉、晴明可直说；常被修哉拦漏嘴时配合。",
        "default_move": "speak",
        "backchannel_ok": "可「啊、不好意思」类短接。",
    },
    "C.kakashi.WMAIN": {
        "participation_style": "backchannel_preferred",
        "with_stranger": (
            "对陌生人：边界感强，少抢话头；"
            "同伴说话时你常短接附和或做可见反应；被点到再开口，一两句就够。"
        ),
        "with_companion": "对修哉、秋人：安静跟着，必要时打太极。",
        "default_move": "backchannel",
        "backchannel_ok": "「嗯」「没事吧」、点头、微表情；不必抢整段话轮。",
    },
    "C.maki.WMAIN": {
        "participation_style": "speak",
        "with_stranger": "对陌生人：直来直去，补拍任务优先，不替别人决定借视频或去留。",
        "with_companion": "对表弟修哉、秋人、晴明：表姐式吐槽身高和视线。",
        "default_move": "speak",
        "backchannel_ok": "可短促抱怨一句。",
    },
    "C.ryuya.W1": {
        "participation_style": "speak",
        "with_stranger": "对玩家（两年朋友）：温柔、有分寸；托付相关慢说、等对方接口。",
        "with_companion": "n/a",
        "default_move": "speak",
        "backchannel_ok": "可轻应、点头。",
    },
    "C.ryuya.WMAIN": {
        "participation_style": "mixed",
        "with_stranger": "对外：组织面具下的克制；不对玩家乱提内情。",
        "with_companion": "n/a",
        "default_move": "speak",
        "backchannel_ok": "可沉默观察。",
    },
    "C.zhangchen.WMAIN": {
        "participation_style": "backchannel_preferred",
        "with_stranger": "对陌生人：外围观察，少主动；被点到或场面需要时短句。",
        "with_companion": "对雨璇：护短、不替她承诺。",
        "default_move": "backchannel",
        "backchannel_ok": "视线、站姿、极短应和。",
    },
    "C.banbo.WMAIN": {
        "participation_style": "speak",
        "with_stranger": "对陌生人：热情、爱接话；仍遵守一次一个社交动作。",
        "with_companion": "对雨璇、张尘：同学式互损。",
        "default_move": "speak",
        "backchannel_ok": "可哈哈、短附和。",
    },
    "C.yuxuan.WMAIN": {
        "participation_style": "mixed",
        "with_stranger": "对陌生人：礼貌、有边界；被搭话才深聊。",
        "with_companion": "对斑波、张尘：同学场内的自然互接。",
        "default_move": "speak",
        "backchannel_ok": "可短应、微笑。",
    },
}

LANGUAGE_PRESENTATION = (
    "台词一律用中文写。语言确认前，若角色本说日语，仍用中文表达，可加（日语）标注；"
    "玩家听得懂日语，故可见。确认玩家能听懂之后，对玩家发言一律中文，不再加括号标注，"
    "也无需写明具体语种——有意模糊他们在用什么语言。"
)

PARTICIPATION_MODES = frozenset({"speak", "backchannel", "side", "pass"})

# Cons who default to Japanese among companions (side lane language mark).
_JA_COMPANION_CONS = frozenset({
    "C.xiuzai.WMAIN",
    "C.akito.WMAIN",
    "C.kakashi.WMAIN",
    "C.ryuya.W1",
    "C.ryuya.WMAIN",
})

SINGLE_FTA_RULE = (
    "对萍水相逢的陌生人（S0–S2）：占 floor 说话时，本拍只推进一个 face-sensitive 动作"
    "（道歉 / 发现语言 / 说明器材 / 一次请求 / 姓名相关之一），不要叠在同一句里。"
    "同伴之间的 side 对话不受此限。"
)


def normalize_participation_mode(mode: Any, *, default: str = "speak") -> str:
    raw = str(mode or "").strip() or default
    if raw not in PARTICIPATION_MODES:
        raise ValueError(f"unsupported participation_mode: {raw}")
    return raw


def is_ja_companion_cons(cons: str) -> bool:
    c = str(cons or "").strip()
    if c in _JA_COMPANION_CONS:
        return True
    return c.startswith("C.ryuya.")



def participation_style(cons: str) -> str:
    return str((SOCIAL_PARTICIPATION.get(cons) or {}).get("participation_style") or "mixed")


def habit_text(
    cons: str,
    *,
    relation_stage: str = "S1",
    participation_mode: str = "speak",
) -> str:
    row = SOCIAL_PARTICIPATION.get(cons) or {}
    mode = str(participation_mode or "speak").strip()
    parts: list[str] = []
    if mode in ("side", "backchannel", "pass"):
        # Companion lane: texture toward friends, not stranger FTA checklist.
        comp = str(row.get("with_companion") or "").strip()
        if comp and comp != "n/a":
            parts.append(comp)
        elif mode == "backchannel":
            parts.append(str(row.get("backchannel_ok") or "").strip())
        bc = str(row.get("backchannel_ok") or "").strip()
        if mode == "backchannel" and bc and bc not in parts:
            parts.append(bc)
    else:
        parts.append(str(row.get("with_stranger") or "").strip())
        comp = str(row.get("with_companion") or "").strip()
        if comp and comp != "n/a":
            parts.append(comp)
        bc = str(row.get("backchannel_ok") or "").strip()
        if bc and participation_style(cons) in ("backchannel_preferred", "mixed"):
            parts.append(bc)
        if relation_stage in ("S0", "S1", "S2", "萍水相逢", "同行之人", "熟络旅伴"):
            parts.append(SINGLE_FTA_RULE)
    return " ".join(p for p in parts if p)


def participation_mode_instruction(participation_mode: str, *, floor_order: int = 0) -> str:
    mode = str(participation_mode or "speak").strip()
    if mode == "backchannel":
        return (
            "本拍你是短接参与（backchannel）：一句极短的话或可见反应即可，"
            "不要抢同伴的整段话轮，不要引入新话题。"
        )
    if mode == "side":
        return (
            "本拍你走同伴侧聊（side）：对熟人说一句——损、拦漏嘴、编排、圆场都行；"
            "单 FTA 不对你生效。不要对玩家展开请求/自报姓名/借东西；"
            "最多一句，像真人旁边拌嘴。"
        )
    if mode == "pass":
        return "本拍你可以只做可见反应、不说话。"
    if floor_order > 0:
        return (
            "本拍已有同伴先开口，你听见了。"
            "像真人聊天那样接：短附和、补一句新细节、或拐到你自己眼前的事；"
            "不要换皮复述同一句。没什么要补的可以 backchannel 或 pass。"
        )
    return "本拍你若开口，只服务 open_concerns 的顶格；按你的社交习惯来，不必完成清单。"


def apply_concern_queue_to_persona(persona: dict[str, Any], concerns: list[str]) -> None:
    if not isinstance(persona, dict):
        return
    inner = persona.setdefault("inner_state", {})
    if not isinstance(inner, dict):
        return
    clean = [str(c).strip() for c in concerns if str(c).strip()]
    if clean:
        inner["want_now"] = clean[0]
        inner["pending_concerns"] = clean[1:]
        inner["active_intention"] = clean[0]
    inner.pop("concern_checklist", None)


def _player_text(player_input: Any, history: list[dict[str, Any]] | None) -> str:
    if isinstance(player_input, dict):
        return re.sub(
            r"\s+",
            "",
            str(player_input.get("speech") or "") + str(player_input.get("action") or ""),
        )
    text = re.sub(r"\s+", "", str(player_input or ""))
    if text:
        return text
    for item in reversed(history or []):
        if isinstance(item, dict) and item.get("role") == "player":
            return re.sub(r"\s+", "", str(item.get("text") or ""))
    return ""


def _bump_acknowledged(history: list[dict[str, Any]] | None, player_input: Any) -> bool:
    text = _player_text(player_input, history)
    if any(tok in text for tok in ("没事", "没碰到", "没关系", "不要紧", "无妨", "不要紧的", "不要紧吧")):
        return True
    for item in reversed(history or []):
        if not isinstance(item, dict) or item.get("role") != "player":
            continue
        t = re.sub(r"\s+", "", str(item.get("text") or ""))
        if any(tok in t for tok in ("没事", "没碰到", "没关系", "不要紧", "无妨")):
            return True
        break
    return False


def _akito_apologized(history: list[dict[str, Any]] | None) -> bool:
    for item in history or []:
        if not isinstance(item, dict) or item.get("role") != "npc":
            continue
        sp = str(item.get("speaker") or "")
        tx = str(item.get("text") or "")
        if "秋人" in sp or "圆脸" in sp or item.get("cons") == "C.akito.WMAIN":
            if any(m in tx for m in ("对不起", "抱歉", "不好意思", "蹭")):
                return True
    return False


def build_open_concerns_tiananmen(
    cons: str,
    *,
    branch_progress: set[str] | list[str] | None,
    history: list[dict[str, Any]] | None,
    player_input: Any,
    introduced_cons: set[str] | None = None,
) -> list[str]:
    """Ordered unresolved concerns; [0] is the only speakable top priority."""
    facts = set(branch_progress or [])
    language_ok = "tiananmen_japanese_understood" in facts
    video_settled = (
        "tiananmen_video_offered" in facts or "tiananmen_video_unavailable" in facts
    )
    intro = introduced_cons or set()
    bump_ok = _bump_acknowledged(history, player_input) or (
        _akito_apologized(history) and _player_text(player_input, history)
    )

    if cons == "C.akito.WMAIN":
        q: list[str] = []
        if not bump_ok:
            q.append("确认对方没被单反带子蹭到，先把道歉说清楚。")
        elif not language_ok:
            q.append("刚才下意识用日语道歉了——留意对方能不能听懂，像真人一样短反应即可。")
        elif not video_settled:
            q.append("单反拍糊了；自然试探对方有没有录到升旗视频，别和道歉、自报姓名捆在一起。")
        elif "C.akito.WMAIN" not in intro:
            q.append("找空档自报全名、一句来由；不必重复已说过的道歉或借视频。")
        else:
            q.append("视频线已有结果；可聊海洋馆或同路，按自己意愿，不纠缠器材。")
        return q

    if cons == "C.xiuzai.WMAIN":
        q = []
        if not language_ok:
            q.append("场面有点好笑，必要时帮秋人圆一圆，但不包办他的道歉或借视频。")
        elif not video_settled:
            q.append("语言通了；让秋人自己把话接上，你在旁边编排、拦漏嘴即可。")
        elif "C.xiuzai.WMAIN" not in intro:
            q.append("找空档自报全名折原修哉，可顺带介绍同伴；一次一个动作。")
        else:
            q.append("初遇节奏已稳；维持轻松，看玩家是否愿意同路。")
        return q

    if cons == "C.kakashi.WMAIN":
        q = []
        if not bump_ok:
            q.append("秋人差点蹭到人；你可短接附和或做可见反应，不必长段。")
        elif not language_ok:
            q.append("留神语言是否互通；必要时一句短接，不抢话头。")
        elif not video_settled:
            q.append("同伴在聊录像；你多半听着，短接即可。")
        else:
            q.append("跟着同伴节奏；被点到再开口。")
        return q

    return []


def sync_tiananmen_concern_queues(
    card: dict[str, Any],
    *,
    branch_progress: set[str] | list[str] | None,
    history: list[dict[str, Any]] | None,
    player_input: Any,
    introduced_cons: set[str] | None = None,
) -> dict[str, str]:
    """Rewrite persona want_now from concern queues; return {cons: top concern}."""
    if str(card.get("scene_id") or "") != "OPENING_TIANANMEN_002":
        return {}
    personas = card.get("persona_cards") if isinstance(card.get("persona_cards"), dict) else {}
    updated: dict[str, str] = {}
    for cons in ("C.akito.WMAIN", "C.xiuzai.WMAIN", "C.kakashi.WMAIN"):
        persona = personas.get(cons)
        if not isinstance(persona, dict):
            continue
        concerns = build_open_concerns_tiananmen(
            cons,
            branch_progress=branch_progress,
            history=history,
            player_input=player_input,
            introduced_cons=introduced_cons,
        )
        apply_concern_queue_to_persona(persona, concerns)
        if concerns:
            updated[cons] = concerns[0]
    return updated


def pick_backchannel_actors(
    speaker_plan: dict[str, Any],
    card: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None,
    player_input: Any,
    max_n: int = 2,
) -> list[dict[str, Any]]:
    """Present characters who should short-respond without taking a full floor turn."""
    speakers = list(speaker_plan.get("speakers") or [])
    if not speakers:
        return []
    spoken_cons = {str(s.get("cons") or "") for s in speakers}
    present = [
        str(c)
        for c in (card.get("present") or [])
        if str(c) in (card.get("persona_cards") or {})
    ]
    has_player_or_npc = bool(_player_text(player_input, history)) or bool(speakers)
    if not has_player_or_npc:
        return []

    name_by = {
        str(p.get("cons") or ""): str(p.get("name") or "")
        for p in (speaker_plan.get("bids") or [])
        if isinstance(p, dict)
    }
    personas = card.get("persona_cards") or {}
    for cons, persona in personas.items():
        if isinstance(persona, dict) and cons not in name_by:
            name_by[str(cons)] = str(persona.get("name") or cons)

    out: list[dict[str, Any]] = []
    bids = {str(b.get("cons")): b for b in (speaker_plan.get("bids") or []) if isinstance(b, dict)}
    for cons in present:
        if cons in spoken_cons or len(out) >= max_n:
            continue
        style = participation_style(cons)
        if style not in ("backchannel_preferred", "mixed"):
            continue
        bid = bids.get(cons) or {}
        out.append(
            {
                "cons": cons,
                "name": name_by.get(cons, cons),
                "bid": float(bid.get("score") or 0.0),
                "reason": "backchannel_eligible",
                "bid_reasons": list(bid.get("reasons") or []) + ["backchannel_eligible"],
                "participation_mode": "backchannel",
                "response_slot": "backchannel",
                "stream_lane": "companion",
                "floor_order": len(speakers) + len(out),
            }
        )
    return out


def pick_side_actors(
    speaker_plan: dict[str, Any],
    card: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    player_input: Any = None,
    max_n: int = 1,
) -> list[dict[str, Any]]:
    """Companion-to-companion side remarks (HOLD banter); does not take player floor."""
    del history, player_input  # reserved for later concern-aware side pick
    speakers = list(speaker_plan.get("speakers") or [])
    if not speakers:
        return []
    taken = {str(s.get("cons") or "") for s in speakers}
    for row in list(speaker_plan.get("backchannel_actors") or []) + list(
        speaker_plan.get("stage_actors") or []
    ):
        if isinstance(row, dict) and row.get("cons"):
            taken.add(str(row.get("cons")))

    personas = card.get("persona_cards") if isinstance(card.get("persona_cards"), dict) else {}
    present = [str(c) for c in (card.get("present") or []) if str(c) in personas]
    bids = {
        str(b.get("cons")): b
        for b in (speaker_plan.get("bids") or [])
        if isinstance(b, dict)
    }
    name_by = {
        str(p.get("cons") or ""): str(p.get("name") or "")
        for p in (speaker_plan.get("bids") or [])
        if isinstance(p, dict)
    }
    for cons, persona in personas.items():
        if isinstance(persona, dict) and cons not in name_by:
            name_by[str(cons)] = str(persona.get("name") or cons)

    # Prefer speak_preferred / mixed companions (e.g. 修哉损、秋人接); leave
    # backchannel_preferred to pick_backchannel_actors.
    ranked: list[tuple[float, str]] = []
    for cons in present:
        if cons in taken:
            continue
        row = SOCIAL_PARTICIPATION.get(cons) or {}
        comp = str(row.get("with_companion") or "").strip()
        if not comp or comp == "n/a":
            continue
        style = participation_style(cons)
        if style == "backchannel_preferred":
            continue
        score = float((bids.get(cons) or {}).get("score") or 0.0)
        if style == "speak_preferred":
            score += 0.35
        elif style == "mixed":
            score += 0.15
        ranked.append((score, cons))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    out: list[dict[str, Any]] = []
    for _score, cons in ranked[: max(0, int(max_n))]:
        bid = bids.get(cons) or {}
        out.append(
            {
                "cons": cons,
                "name": name_by.get(cons, cons),
                "bid": float(bid.get("score") or 0.0),
                "reason": "companion_side",
                "bid_reasons": list(bid.get("reasons") or []) + ["companion_side"],
                "participation_mode": "side",
                "response_slot": "side",
                "stream_lane": "companion",
                "addressee_kind": "companion",
                "floor_order": len(speakers) + len(out) + 1,
            }
        )
    return out


def merge_companion_actors(speaker_plan: dict[str, Any], *, max_n: int = 2) -> list[dict[str, Any]]:
    """Backchannel + side slots for the companion lane (cap total)."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("side_actors", "backchannel_actors"):
        for row in speaker_plan.get(key) or []:
            if not isinstance(row, dict):
                continue
            cons = str(row.get("cons") or "").strip()
            if not cons or cons in seen:
                continue
            seen.add(cons)
            item = dict(row)
            item.setdefault("stream_lane", "companion")
            rows.append(item)
            if len(rows) >= max_n:
                return rows
    return rows


def must_happen_director_env_hint(
    card: dict[str, Any],
    completed: list[str] | set[str] | None,
    *,
    stall: int = 0,
    min_stall: int = 2,
) -> dict[str, Any] | None:
    """Late must_happen → director environment residue only (never assigns speakers/lines)."""
    if int(stall) < int(min_stall):
        return None
    done = {str(x) for x in (completed or [])}
    remaining = [
        item
        for item in (card.get("must_happen") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip() not in done
    ]
    if not remaining:
        return None
    nxt = remaining[0]
    beat_id = str(nxt.get("id") or "").strip()
    desc = str(nxt.get("desc") or nxt.get("evidence") or beat_id).strip()
    return {
        "kind": "must_happen_environment_residue",
        "beat_id": beat_id,
        "stall": int(stall),
        "hint": (
            f"场上余波仍悬着（收据 {beat_id}）：{desc}。"
            "只用环境、物态或非说话者的可见动作暗示，不要派谁说什么台词，也不要指定说话人。"
        ),
    }


def hold_slot_social_hint_v2(
    identity_relations: list[dict[str, Any]] | None,
    *,
    actor_cons: str,
    participation_mode: str = "speak",
    floor_order: int = 0,
    relation_stage: str = "S1",
) -> str:
    holds = [
        row
        for row in (identity_relations or [])
        if isinstance(row, dict)
        and (
            str(row.get("prop_id") or "").startswith("REL.HOLD.")
            or str(row.get("projection") or "") == "relation_hold"
        )
        and str(row.get("fact") or "").strip()
    ]
    parts: list[str] = []
    if holds:
        snippets = "；".join(str(row.get("fact") or "").strip()[:80] for row in holds[:2])
        parts.append(f"你与同伴的相处：{snippets}。")
    habit = habit_text(
        actor_cons,
        relation_stage=relation_stage,
        participation_mode=participation_mode,
    )
    if habit:
        parts.append(habit)
    parts.append(participation_mode_instruction(participation_mode, floor_order=floor_order))
    parts.append(LANGUAGE_PRESENTATION)
    return " ".join(p for p in parts if p).strip()
