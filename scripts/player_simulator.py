# -*- coding: utf-8 -*-
"""
player_simulator.py —— 生成式玩家模拟器（阶段7）

给定场景上下文，现场生成一句玩家台词（不复读、不出系统内部字段）。
复用 exp.call_deepseek，不新起调用方式。

使用方式：
    from player_simulator import simulate_player_turn
    player_input = simulate_player_turn(scene_context, playstyle_persona, recent_turns, config)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "scripts" / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import test_scene_experience as exp

# ── Prompt 模板 ──────────────────────────────────────────────
# 原则：不泄漏 path_id / 触发词 / exit_state / branch_gate 等内部字段
# 玩家只应看到场景旁白 + NPC 台词 + 自身的人设描述

PLAYER_SYSTEM_PROMPT = """你是《存在的意义：因果之外》的玩家角色模拟器。

你扮演的玩家是一个真实的人——有直觉、有情绪、有戒备、也有配合的一面。
你只说这个人**此刻**最自然的一句话，不做作、不背诵、不出戏。

规则：
1. 输出严格只是一句玩家台词，不要引号、不要解释、不要前缀。
2. 不要提到系统层概念（path_id、exit_state、触发词、branch、分支、canon_locked）。
3. 不要复读最近 player_input 里已经出现过的词汇或表达方式。
4. 贴合当前场景的氛围，台词和场景的情绪一致（比如紧张场景不要说轻松话）。
5. 如果这是一个需要玩家决策的暂停点，让台词体现玩家的倾向；如果只是跟进对话，说一句自然的跟进话。
6. 语言为中文，符合这个玩家的说话习惯（不一定要完整句子，可以是动作描写+短句）。

当前场景信息：
{scene_narration}

最近几次玩家说过的话（请避免复读这些）：
{recent_inputs}

玩家人设：
{persona_desc}

请输出玩家接下来要说的一句话："""

PLAYERSTOPHEMAS = ["输出严格只是一句", "不要引号", "不要解释", "不要前缀"]
ERROR_PREFIXES = ("[ERROR:", "ERROR:", "http_error_", "timeout", "Timeout")


def _build_scene_narration(last_messages: list[dict[str, Any]], place: str) -> str:
    """从最近的 NPC 台词提取场景氛围描述，用作 prompt 的 scene_narration。"""
    lines = []
    # 场景名作为锚点
    if place:
        lines.append(f"【场景】{place}")
    # 取最近 6 条消息，提取角色名+核心台词片段（去 inner/overhear）
    for msg in last_messages[-6:]:
        role = msg.get("role", "")
        if role not in ("npc", "director", "narration"):
            continue
        name = msg.get("name", "???")
        content = msg.get("content", "")
        lang_tag = msg.get("lang", "")
        if lang_tag == "ja":
            continue  # 不让玩家看见日语台词片段
        if content and len(content) > 2:
            lines.append(f"{name}：{content[:80]}")
    if not lines:
        lines.append("（场景安静，没有人说话）")
    return "\n".join(lines)


def simulate_player_turn(
    scene_context: dict[str, Any],
    playstyle_persona: str,
    recent_player_inputs: list[str],
    config: dict[str, Any],
) -> str:
    """
    生成一句贴合场景的即时玩家台词。

    参数：
        scene_context:  {
            "place": str,          # 场景名称
            "last_messages": list, # 最近 NPC/director/narration 消息
            "current_beat_hint": str,  # 当前 beat 的简短描述（可空）
        }
        playstyle_persona: str   # 玩法简短人设，如"你是一个配合型玩家……"
        recent_player_inputs: list[str]  # 玩家最近说过的话（去重）
        config: dict[str, Any]   # API 配置（同 exp.call_deepseek）

    返回：
        str：一句玩家台词。
    """
    place = scene_context.get("place", "未知地点")
    last_msgs = scene_context.get("last_messages", [])
    scene_narration = _build_scene_narration(last_msgs, place)

    # 避免复读：倒序取最近 3 条玩家发言的核心词（取前10字）
    recent_str = ""
    if recent_player_inputs:
        deduped = list(dict.fromkeys(recent_player_inputs))[-3:]
        recent_str = "\n".join(f"  - {s[:40]}" for s in deduped)

    prompt = PLAYER_SYSTEM_PROMPT.format(
        scene_narration=scene_narration,
        recent_inputs=recent_str or "  （无）",
        persona_desc=playstyle_persona,
    )

    result = exp.call_deepseek(
        prompt=("你是一个严格的创意写作助手。\n"
                "用户会给你一段玩家台词生成任务的描述，"
                "你必须严格遵守其中所有规则，不得输出规则禁止的内容。"),
        user_content=prompt,
        config=config,
        temperature=0.7,
        max_tokens=128,
    )

    # 清理：去首尾空白、可能的引号
    text = str(result).strip().strip("""""'""").strip()
    # 安全兜底：若 LLM 返回明显异常，回退。错误文本绝不能进入戏内上下文。
    if (
        not text
        or len(text) < 2
        or text.startswith("玩家台词：")
        or text.startswith(ERROR_PREFIXES)
        or "http_error" in text
    ):
        text = "我先跟着看看。"
    return text
