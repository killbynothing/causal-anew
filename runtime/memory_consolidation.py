# -*- coding: utf-8 -*-
"""
runtime/memory_consolidation.py —— Loop X2「记忆链救活」配套逻辑

背景（见 STATUS 2026-07-06 续10 归因）：
`call_memory_consolidator` 的输出 schema 曾经没有强制要求 `inner_state`；
兜底代码用 `setdefault` 把缺失字段全部填成同一句恒定常量
（"观察并推进当下对话" / "未知心结" / "中性"），
防空转判定又直接拿这批恒定常量互相比较，于是三个 NPC 的 inner_state
必然"看起来一模一样"，判定为空转，导致**每次转场都整体回退到
`template_fallback`**——角色私有记忆恒空、固化四字段千篇一律。

本文件把两块可复用逻辑从冻结单体 `free_stage_prototype.py`
（3500+ 行，按项目纪律只做必要接线改动）里拆出来，新增逻辑一律落在这里：

- `resolve_inner_state_field_fallback`：字段级降级取值——单个 inner_state
  字段缺失/为空时，优先回退「上一场真实值」，其次回退
  `project_initial_inner_state` 的开场投影值，最后才落到兜底常量；
  不再让"回退值"和"防空转判定的默认哨兵"共用同一批魔法字符串。
- `inner_state_stagnated`：防空转判定改为直接比较真实字段内容，
  不再对任何常量字符串做特判；只有确实存在「可比较的上一场记录」
  （非开场投影占位）时才参与判定。
- `deterministic_chain_memory_consolidator`：仅供 selftest / 确定性链
  自测使用的记忆固化桩，按 `target_scene_id` 与 `source_scene`
  演化 inner_state / mood 文本，确保连续两场以上转场时
  `structured_memories` 不会退化成恒定常量。
  真实 caller 路径完全不经过这个函数——`fixed_memory_consolidator`
  （free_stage_prototype.py 内既有、供既有测试做精确字符串断言用）
  保持不变，不在本文件覆盖范围内。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


def player_display_name(
    player_profile: dict[str, Any] | None,
    source_card: dict[str, Any] | None = None,
) -> str:
    if isinstance(player_profile, dict):
        name = str(player_profile.get("name") or "").strip()
        if name:
            return name
    if source_card:
        present = set(source_card.get("present") or [])
        aline_trio = {"C.akito.WMAIN", "C.xiuzai.WMAIN", "C.kakashi.WMAIN"}
        if present.intersection(aline_trio):
            return "阿七"
        keys = set(npc_slug_keys(source_card))
        if keys and keys <= {"akito", "xiuzai", "kakashi"}:
            return "阿七"
    return "玩家"


def npc_slug_keys(card: dict[str, Any] | None) -> list[str]:
    keys: list[str] = []
    for cons in (card or {}).get("persona_cards") or {}:
        slug = str(cons).split(".")[1] if "." in str(cons) else str(cons)
        if slug and slug not in keys:
            keys.append(slug)
    if keys:
        return keys
    return ["akito", "xiuzai", "kakashi"]


def cons_for_npc_slug(card: dict[str, Any] | None, slug: str) -> str:
    persona_cards = (card or {}).get("persona_cards") or {}
    for cons in persona_cards:
        part = str(cons).split(".")[1] if "." in str(cons) else str(cons)
        if part == slug:
            return str(cons)
    legacy = {
        "akito": "C.akito.WMAIN",
        "xiuzai": "C.xiuzai.WMAIN",
        "kakashi": "C.kakashi.WMAIN",
        "zhangchen": "C.zhangchen.WMAIN",
        "banbo": "C.banbo.WMAIN",
        "yuxuan": "C.yuxuan.WMAIN",
        "weichu": "C.weichu.WMAIN",
    }
    return legacy.get(slug, slug)


def npc_display_name(card: dict[str, Any] | None, slug: str) -> str:
    cons = cons_for_npc_slug(card, slug)
    persona = ((card or {}).get("persona_cards") or {}).get(cons)
    if isinstance(persona, dict):
        name = str(persona.get("name") or "").strip()
        if name:
            return name
    try:
        from runtime.name_book import entry

        full = entry(cons).get("full")
        if full:
            return str(full)
    except Exception:
        pass
    return slug


def _default_relation_for_scene(source_card: dict[str, Any], npc_slug: str) -> str:
    scene_id = str(source_card.get("scene_id", "")).lower()
    if "highway" in scene_id:
        return {
            "akito": "生死盟友",
            "xiuzai": "患难搭档",
            "kakashi": "生死之交",
        }.get(npc_slug, "萍水相逢")
    if any(x in scene_id for x in ("aquarium", "dolphin")):
        return {
            "akito": "熟络旅伴",
            "xiuzai": "投缘同伴",
            "kakashi": "同行之人",
        }.get(npc_slug, "萍水相逢")
    return "萍水相逢"


def _generic_inner_state() -> dict[str, str]:
    return {
        "want_now": "观察并推进当下对话",
        "knot": "未知心结",
        "unsaid": "",
        "stance_to_player": "中性",
    }


def _default_mood_for_slug(npc_slug: str) -> str:
    return {
        "akito": "欣慰",
        "xiuzai": "散漫",
        "kakashi": "沉思",
        "zhangchen": "尴尬",
        "banbo": "警惕",
        "yuxuan": "拘谨",
    }.get(npc_slug, "平静")


def build_template_fallback_skeleton(
    source_card: dict[str, Any],
    target_card: dict[str, Any],
    completed: list[str],
    reason: str,
    player_profile: dict[str, Any] | None = None,
    make_degradation: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按本场 persona 与玩家模板构造记忆固化模板骨架（不含 A 线硬编码三人）。"""
    player_name = player_display_name(player_profile, source_card)
    source_scene = source_card.get("scene", "上一场")
    npc_keys = npc_slug_keys(source_card)

    events_summary = []
    for mh in source_card.get("must_happen", []):
        if mh.get("id") in completed:
            desc = str(mh.get("desc", "")).strip()
            if desc:
                events_summary.append(desc)
    target_scene = str(target_card.get("scene", "随后地点")).strip() or "随后地点"
    safe_events = []
    for raw in events_summary:
        if any(w in raw for w in ["系统", "游戏", "AI", "模型", "枪击"]):
            continue
        clean = raw.replace("★★★", "").strip()
        clean = clean.replace("玩家", player_name)
        clean = clean.replace("下一场", "随后").replace("下一步", "随后")
        clean = clean.replace("下一站", target_scene)
        safe_events.append(clean)
    if safe_events:
        context_desc = f"【上一场固化】在{source_scene}，完成了以下事件：" + "；".join(safe_events)
    else:
        context_desc = f"【上一场固化】在{source_scene}，{player_name}和在场的人一起把场面往前推了一步。"
    scene_facts = [
        {
            "fact": event,
            "source": "verified_scene_event",
            "confidence": "confirmed",
        }
        for event in safe_events[:6]
    ] or [
        {
            "fact": f"{player_name}在{source_scene}停留并参与了现场。",
            "source": "visible_transcript_fallback",
            "confidence": "confirmed",
        }
    ]
    director_summary = (
        f"{source_scene}这一场已经落下。{context_desc.removeprefix('【上一场固化】')}"
    )

    structured_memories: dict[str, Any] = {}
    per_npc_first_person: dict[str, list[str]] = {}
    for slug in npc_keys:
        relation = _default_relation_for_scene(source_card, slug)
        display = npc_display_name(source_card, slug)
        structured_memories[slug] = {
            "summary": f"在{source_scene}，我和{player_name}一起行动，对彼此多了些印象。",
            "mood": _default_mood_for_slug(slug),
            "relation": relation,
            "unresolved": "",
            "inner_state": dict(_generic_inner_state()),
        }
        per_npc_first_person[slug] = [
            f"我记得{source_scene}发生的事，{player_name}也在场（{display}视角）。"
        ]

    degradations: list[dict[str, Any]] = []
    if make_degradation is not None:
        degradations.append(
            make_degradation(
                "memory_consolidator",
                "template_fallback",
                "记忆固化回退到模板骨架",
                detail=reason,
            )
        )

    return {
        "scene_facts": scene_facts,
        "director_summary": director_summary,
        "context_memory": [context_desc],
        "relationship_memory": [
            f"【上一场固化】在{source_scene}的同行经历，让{player_name}和在场者之间的关系又往前走了一点。"
        ],
        "per_npc_first_person": per_npc_first_person,
        "structured_memories": structured_memories,
        "player_visible_change": {
            "player_identity": player_name,
            "relation_delta": f"在{source_scene}的交流使信任感有所变化。",
            "world_delta": "因果世界线基本平稳，无剧烈偏离。",
            "key_action_recorded": f"{player_name}在场推进了场面。",
        },
        "source_scene_id": source_card.get("scene_id", ""),
        "source_scene": source_scene,
        "target_scene_id": target_card.get("scene_id", ""),
        "target_ch_anchor": target_card.get("ch_anchor", 0),
        "mode": "template_fallback",
        "fallback_reason": reason,
        "degradations": degradations,
    }


def build_consolidator_system_prompt(npc_keys: list[str], player_name: str) -> str:
    npc_json_lines = ",\n".join(f'    "{k}": []' for k in npc_keys)
    struct_lines = ",\n".join(
        f'    "{k}": {{"summary": "", "mood": "", "relation": "", "unresolved": "", '
        f'"inner_state": {{"want_now": "", "knot": "", "unsaid": "", "stance_to_player": ""}}}}'
        for k in npc_keys
    )
    return (
        "你是一个因果世界线记忆固化整合器。请根据上一场历史、完成事件和分支进度（branch_progress），固化各角色的记忆。\n"
        "特别提醒：如果 branch_progress 中包含了玩家的因果行为（例如：choiceA_brace 表示扑救了晴明，B1_dog 表示提前示警，bp_invited 表示同行的邀请，tiananmen_aquarium_declined 表示拒绝同行），"
        "请在生成的 context_memory 或是 structured_memories 的 summary/unresolved/mood 字段中对这些关键因果进行物理与情感上的细节固化体现，不要遗漏玩家的因果选择。"
        "玩家明确拒绝时，固化不得写成同意/同行/收下；只能写拒绝本身与现场后果。\n"
        f"本场玩家身份（player_identity）必须写为「{player_name}」，不得写成其他周目玩家。\n"
        "你需要输出一个精确的 JSON，包含：\n"
        "1. scene_facts: 丙式结构事实列表；每项含 fact/source/confidence，只写现场确实发生且可追溯的事实；source 使用 visible_transcript 或 verified_scene_event。\n"
        "2. director_summary: 乙偏丙的一段导演摘要；可以有温度，但不得添加 scene_facts 之外的新事实。\n"
        "3. context_memory: 字符串列表，用于注入下一场的背景描述（旁白）。\n"
        "4. relationship_memory: 字符串列表，用于记录伙伴们关系的变化。\n"
        f"5. per_npc_first_person: 包含 {', '.join(npc_keys)} 列表的字典，记录每个角色内心的一人称私语/感触。\n"
        f"6. structured_memories: 包含 {', '.join(npc_keys)} 的字典，每个角色拥有：\n"
        "   - summary: 事件摘要（第一人称简述）\n"
        "   - mood: 情绪残留（一两个词，如“欣慰”、“警惕”）\n"
        "   - relation: 关系变化（当前对玩家的信任关系词）\n"
        "   - unresolved: 未了话头（上场遗留的未尽讨论或话茬）\n"
        "   - inner_state: 字典，包含如下角色当下内心细分状态：\n"
        "     * want_now: 角色此刻最想推动或得到的事物（第一人称，10-25字，必须动态具体更新，禁用空泛词，禁止套用常数模板）\n"
        "     * knot: 角色当下的内心纠结或心结（第一人称，10-25字）\n"
        "     * unsaid: 角色心里明白但未对玩家说透的话（第一人称，10-30字）\n"
        "     * stance_to_player: 对玩家的态度倾向（一两个词，如“友好”、“警惕”、“探寻”）\n"
        "7. player_visible_change: 字典，记录本场玩家所带来的可见偏差，包含：\n"
        f"   * player_identity: 必须为「{player_name}」\n"
        "   * relation_delta: 玩家与角色关系产生的微观信任起伏描述（限一句话）\n"
        "   * world_delta: 玩家动作引起的因果偏离/打破因果的潜在线索描述（限一句话）\n"
        "   * key_action_recorded: 玩家本场最关键的动作/选择记录（限一句话）\n\n"
        "请只输出符合如下结构的有效 JSON，禁止包含任何 markdown 标记或额外解释词：\n"
        "{\n"
        '  "scene_facts": [{"fact": "", "source": "visible_transcript|verified_scene_event", "confidence": "confirmed"}],\n'
        '  "director_summary": "",\n'
        '  "context_memory": [],\n'
        '  "relationship_memory": [],\n'
        f'  "per_npc_first_person": {{\n{npc_json_lines}\n  }},\n'
        f'  "structured_memories": {{\n{struct_lines}\n  }},\n'
        '  "player_visible_change": {\n'
        f'    "player_identity": "{player_name}",\n'
        '    "relation_delta": "",\n'
        '    "world_delta": "",\n'
        '    "key_action_recorded": ""\n'
        "  }\n"
        "}"
    )


def enforce_player_identity(
    payload: dict[str, Any],
    player_profile: dict[str, Any] | None,
    source_card: dict[str, Any] | None = None,
) -> list[str]:
    """以 session player_profile 校正固化结果中的玩家身份；返回降级说明。"""
    player_name = player_display_name(player_profile, source_card)
    notes: list[str] = []
    p_visible = payload.setdefault("player_visible_change", {})
    old = str(p_visible.get("player_identity") or "").strip()
    if old and old != player_name:
        notes.append(f"player_identity:{old}->{player_name}")
    p_visible["player_identity"] = player_name

    profile_id = str((player_profile or {}).get("id") or "").strip()
    if profile_id == "atang" and "阿七" in json.dumps(payload, ensure_ascii=False):
        notes.append("cross_line_leak:阿七_in_c_line_memory")
    return notes


def resolve_inner_state_field_fallback(
    cons: str,
    field: str,
    prev_inner: dict[str, Any] | None,
    project_fn: Callable[[str, int], dict[str, Any]],
    target_ch_anchor: int,
    generic_default: str,
) -> tuple[str, str]:
    """单个 inner_state 字段的降级取值优先级：

    1. 上一场（source_card 对应 NPC）真实的 inner_state 字段值；
    2. `project_initial_inner_state(cons, target_ch_anchor)` 的投影值；
    3. 兜底常量（骨架默认文案）。

    返回 (取值, 来源标签)；来源标签写进 degradations 详情，
    供观测台 / 复盘追溯这一次降级到底用了哪一层回退。
    """
    if isinstance(prev_inner, dict):
        prev_val = prev_inner.get(field)
        if isinstance(prev_val, str) and prev_val.strip():
            return prev_val, "prev_scene"

    if cons:
        try:
            projected = project_fn(cons, target_ch_anchor) or {}
        except Exception:
            projected = {}
        proj_val = projected.get(field)
        if isinstance(proj_val, str) and proj_val.strip():
            return proj_val, "projection"

    return generic_default, "generic"


def inner_state_stagnated(
    prev_inner: dict[str, Any] | None,
    new_inner: dict[str, Any] | None,
    fields: tuple[str, ...] = ("want_now", "unsaid", "knot"),
) -> bool:
    """基于真实字段内容比较的单 NPC 防空转判定。

    不对任何"常量哨兵字符串"做特判——判定完全基于内容是否发生变化。
    只有存在可比较的真实上一场记录时才参与判定：
    - 上一场记录不存在或为空：视为不可比较，不计入空转；
    - 上一场记录是开场投影占位（`_from_opening`）：同样不计入空转
      （第一次转场时"投影值与新固化值一致"是正常现象，不代表 LLM 偷懒）。
    """
    if not isinstance(prev_inner, dict) or not prev_inner:
        return False
    if prev_inner.get("_from_opening"):
        return False
    if not isinstance(new_inner, dict):
        return False
    return all(prev_inner.get(f) == new_inner.get(f) for f in fields)


_NPC_FLAVORS: dict[str, dict[str, list[str]]] = {
    "akito": {"mood_pool": ["欣慰", "期待", "振奋", "感慨"], "stance_pool": ["友好", "热络", "支持"]},
    "xiuzai": {"mood_pool": ["散漫", "专注", "警惕", "放松"], "stance_pool": ["中性", "探寻", "漠然"]},
    "kakashi": {"mood_pool": ["沉思", "戒备", "平和", "留意"], "stance_pool": ["礼貌中立", "克制", "观察"]},
    "weichu": {"mood_pool": ["紧绷", "疲惫", "冷淡", "酸楚"], "stance_pool": ["公事公办", "别扭", "防备"]},
    "zhangchen": {"mood_pool": ["尴尬", "松弛", "机警", "自嘲"], "stance_pool": ["玩笑挡开", "礼貌", "试探"]},
}


def _deterministic_seq(*parts: str) -> int:
    """跨进程稳定的确定性演化因子（不依赖 PYTHONHASHSEED 的 hash()）。"""
    digest = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest, 16) % 997


def deterministic_chain_memory_consolidator(**kwargs: Any) -> str:
    """仅供 selftest / 确定性链自测使用的记忆固化桩。

    与 `free_stage_prototype.fixed_memory_consolidator`（其 generic 分支为
    精确的恒定 inner_state 文本，专为既有测试的字符串断言服务，不能改）不同，
    这个桩会按 `target_scene_id` + `source_scene` 演化 inner_state / mood，
    用于验证 Loop X2 的收口断言：
    - selftest 链跑两次以上转场，固化 fallback_rate=0；
    - 同一 NPC 连续两场 structured_memories 内容不完全相同（非恒定常量）。

    真实 caller 路径（LLM 或真实业务 memory_caller）不经过这个函数。
    """
    request = json.loads(kwargs["user_content"])
    source_scene = request.get("source_scene") or "上一场"
    target_scene = request.get("target_scene") or request.get("target_scene_id") or "后续地点"
    target_scene_id = str(request.get("target_scene_id") or "NEXT_SCENE")
    npc_keys = list(request.get("npc_keys") or []) or ["akito", "xiuzai", "kakashi"]
    player_name = player_display_name(request.get("player_profile"))
    if player_name == "玩家" and set(npc_keys) <= {"akito", "xiuzai", "kakashi"}:
        player_name = "阿七"
    seq = _deterministic_seq(source_scene, target_scene_id)

    structured_memories: dict[str, Any] = {}
    per_npc_first_person: dict[str, list[str]] = {}
    for idx, npc in enumerate(npc_keys):
        flavor = _NPC_FLAVORS.get(npc, {"mood_pool": ["平静"], "stance_pool": ["中性"]})
        pick = seq + idx
        mood = flavor["mood_pool"][pick % len(flavor["mood_pool"])]
        stance = flavor["stance_pool"][pick % len(flavor["stance_pool"])]
        structured_memories[npc] = {
            "summary": f"在{source_scene}之后，{player_name}和我们朝着{target_scene}继续前进，第{pick}轮的心绪又变了一些。",
            "mood": mood,
            "relation": "同行伙伴",
            "unresolved": "",
            "inner_state": {
                "want_now": f"想在到{target_scene}前把话说清楚（第{pick}轮演化）",
                "knot": f"心里还挂着{source_scene}没聊完的事（编号{pick}）",
                "unsaid": f"其实想问{player_name}接下来打算怎么办（第{pick}次犹豫）",
                "stance_to_player": stance,
            },
        }
        per_npc_first_person[npc] = [
            f"我记得{source_scene}发生的事，{player_name}也在场（第{pick}轮）。"
        ]

    return json.dumps(
        {
            "context_memory": [
                f"【上一场固化】在{source_scene}，{player_name}和大家一起把事情推进到了{target_scene}（第{seq}轮）。"
            ],
            "relationship_memory": ["【上一场固化】同行的关系又往前走了一步。"],
            "per_npc_first_person": per_npc_first_person,
            "structured_memories": structured_memories,
            "player_visible_change": {
                "player_identity": player_name,
                "relation_delta": "关系持续推进。",
                "world_delta": "因果世界线平稳前进。",
                "key_action_recorded": "继续跟随队伍行动。",
            },
        },
        ensure_ascii=False,
    )
