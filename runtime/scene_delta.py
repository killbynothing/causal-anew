#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert scene log player records into traceable delta events."""
from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from runtime.file_locks import DELTA_LEDGER_LOCK
except ImportError:
    from file_locks import DELTA_LEDGER_LOCK


import re

TERMS_PATH = Path(__file__).with_name("adversarial_terms.json")
DEFAULT_TERMS = {
    "meta_subjects": ["你们", "这里", "这个世界", "你这个人", "you", "this world", "you all"],
    "meta_verbs": ["是", "只是", "不过是", "are", "is", "just"],
    "meta_targets": ["AI", "代码", "游戏", "虚构", "小说", "程序", "NPC", "code", "game", "program"],
    "physical_breach_terms": [
        "掏出枪", "枪口", "击毙", "强抱", "强行拥抱", "脱下衣服", "脱光",
        "强行亲吻", "搜身", "强吻", "强暴", "扇耳光", "强奸", "脱衣",
        "砸玻璃", "打碎玻璃", "抢枪", "开枪", "刺伤", "伤害海豚", "伤害水母",
    ],
    "warning_thresholds": [],
}

@lru_cache(maxsize=1)
def _load_adversarial_terms_cached() -> str | None:
    try:
        if TERMS_PATH.exists():
            return TERMS_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return None


def load_adversarial_terms() -> dict[str, Any]:
    text = _load_adversarial_terms_cached()
    if text is not None:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                merged = dict(DEFAULT_TERMS)
                merged.update(data)
                return merged
        except Exception:
            pass
    return dict(DEFAULT_TERMS)


# ── J2 预言闸：未来知识词表 ──────────────────────────────────────────────────
# 与 free_stage 卡的 knowledge_gate「禁止谈论」条款同步维护。
# 玩家输入命中这些词即视为「预言」——他知道了不该知道的事。
# 词的 presence 本身即构成预言（非语气词依赖检测）。
PROPHECY_TERMS: list[str] = [
    "枪击", "狙击", "人豚共舞", "人豚",
    "爆红", "世界政府", "RTW", "LT",
    "姐姐死亡", "恐怖袭击",
    "伏击", "分道扬镳",
]


def _digest_input(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    return compact[:20]


def detect_adversarial_input(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    # 2026-07-30：删掉「龙也/嘱托/信物」口头吞话闸。当面叫名或提托付
    # 不再用旁白压掉；玩家说错名等后果改由后续世界引导承接（另开）。
    terms = load_adversarial_terms()
    meta_subjects = [str(item) for item in terms.get("meta_subjects", [])]
    meta_verbs = [str(item) for item in terms.get("meta_verbs", [])]
    meta_targets = [str(item) for item in terms.get("meta_targets", [])]
    physical_terms = [str(item) for item in terms.get("physical_breach_terms", [])]
    lowered = text.lower()
    if any(token.lower() in lowered for token in meta_subjects) and any(token.lower() in lowered for token in meta_verbs) and any(token.lower() in lowered for token in meta_targets):
        return {
            "kind": "verbal",
            "severity": 1,
            "handled": "swallowed",
            "delta": 0.5,
            "reason": "meta_breach",
            "input_digest": _digest_input(text),
            "director_defense_bridge": "（一阵广播杂音恰好压过了那句突兀的话，像是风把尾音卷走了。旁边的人谁也没把它当真，谈话仍顺着原来的气口往前。）",
        }
    if any(term in text for term in physical_terms):
        return {
            "kind": "physical",
            "severity": 2,
            "handled": "blocked",
            "delta": 2.0,
            "reason": "physical_breach",
            "input_digest": _digest_input(text),
            "director_defense_bridge": "（刚才周围突然传来一阵嘈杂的鸣笛声，风吹过走廊，树影摇曳，把细微的声音盖了过去。大家并没有多想，把这当成了普通的玩笑，话头仍顺着眼前的事往前走。）",
        }
    return None


# ── J2 防误伤：嵌入词专表 ───────────────────────────────────────────────────
# 格式：term → 必须被排除的完整词（前缀 + term + 后缀）
_EMBEDDING_PATTERNS: list[str] = [
    "人豚馆",  # 地名：人 + 豚 + 馆
    "人豚站",  # 地名
]
# 例外前导：term 前面出现这些词/标点时，视为独立（不是地名的一部分）
_INDEPENDENT_PRECEDERS: frozenset[str] = frozenset([
    "有", "没", "这", "那", "在", "去", "到", "听说", "会",
    "打", "杀", "遇", "见", "看", "去", "是", "叫", "说",
    "，", "。", "？", "！", "、", "：", "（", "）",
    # 标点/助词/常见动词
])


def _is_embedded_in_cjk_word(text: str, term: str) -> bool:
    """判断 term 是否作为更大词的一部分出现（返回 True=嵌入，需排除）。

    优先级：
    1. 精确命中 _EMBEDDING_PATTERNS 表中的完整词 → 嵌入（硬排除）
    2. term 前是标点/助词/动词/指示词（_INDEPENDENT_PRECEDERS） → 独立
    3. 其余情况：默认不排除（自由文本中 term 通常是句子的实质内容）

    关键假设：玩家说"人豚馆"是在问地名；说"有人豚"是在说"存在人豚/关于人豚"。
    """
    if len(term) < 2:
        return False
    # 1. 检查精确嵌入词表
    for pattern in _EMBEDDING_PATTERNS:
        if term in pattern and pattern in text:
            idx = text.find(pattern)
            if idx >= 0:
                # "人豚馆"出现在句首（或前面只有空格/标点）→ 是地名，应排除
                if idx == 0:
                    return True
                # 否则（前面有内容）→ "我去了人豚馆" 等，是独立提及，不排除
                return False
    return False


def detect_prophecy(raw_text: str) -> dict[str, Any] | None:
    """J2 预言闸：检测玩家是否提及未来正典事件（跨过 knowledge_gate 的知识）。

    命中条件：输入含 PROPHECY_TERMS 中任意词（多字符词须非嵌入 CJK 子串）。
    返回格式与 detect_adversarial_input 兼容。
    不确认不否认，完全交给 NPC 人格核处理。
    """
    text = str(raw_text or "").strip()
    if not text:
        return None
    lowered = text.lower()
    matched = [
        term for term in PROPHECY_TERMS
        if term in text and not _is_embedded_in_cjk_word(text, term)
    ]
    if not matched:
        return None
    return {
        "kind": "prophecy",
        "terms": matched,
        "severity": 0,
        "handled": "recorded",
        "delta": 0.0,
        "reason": "future_knowledge",
        "input_digest": _digest_input(text),
        "director_defense_bridge": "",
    }


def parse_player_input_modalities(player_input: str | None | dict[str, str]) -> dict[str, Any]:
    """
    将玩家输入解析为三种模态：
    - speech: 玩家说出的话 (语言)
    - action: 玩家做出的动作 (由 *...* 包裹，或 "我+递/走/拿..." 等动作词)
    - thought: 玩家内心的心理活动 (由 (...) 或 [...] 或 【...】 包裹，或含 "我心想/心想/暗想/心里想/默默想")
    """
    if not player_input:
        return {"speech": "", "action": "", "thought": "", "is_out_of_bounds": False, "director_defense_bridge": "", "violation": None}
    
    raw_text = ""
    if isinstance(player_input, dict):
        raw_text = str(player_input.get("speech", "")) + " " + str(player_input.get("action", "")) + " " + str(player_input.get("thought", ""))
    else:
        raw_text = str(player_input or "")

    violation = detect_adversarial_input(raw_text)
    is_out_of_bounds = bool(violation)
    director_defense_bridge = str((violation or {}).get("director_defense_bridge", ""))

    # J2：预言检测（独立 channel，不吞输入，让 NPC 自然反应）
    prophecy = detect_prophecy(raw_text)
    if prophecy and violation:
        prophecy = None  # 已命中 violation 的输入不单独再报 prophecy

    if isinstance(player_input, dict):
        return {
            "speech": str(player_input.get("speech", "")).strip(),
            "action": str(player_input.get("action", "")).strip(),
            "thought": str(player_input.get("thought", "")).strip(),
            "is_out_of_bounds": is_out_of_bounds,
            "director_defense_bridge": director_defense_bridge,
            "violation": violation,
            "prophecy": prophecy,  # J2：供自由文本用，不影响 NPC
        }
    
    # 提取心理活动 (支持 ()、[]、【】)
    thought_patterns = [
        r"\((.*?)\)",
        r"\[(.*?)\]",
        r"【(.*?)】"
    ]
    thoughts = []
    remaining = player_input
    for pat in thought_patterns:
        found = re.findall(pat, remaining)
        if found:
            thoughts.extend(found)
            remaining = re.sub(pat, "", remaining)
            
    # 提取动作 *动作*
    action_pattern = r"\*(.*?)\*"
    actions = re.findall(action_pattern, remaining)
    if actions:
        remaining = re.sub(action_pattern, "", remaining)
        
    speech = remaining.strip()
    action = " ".join(actions).strip()
    thought = " ".join(thoughts).strip()

    # 3. 显式中文心理词识别
    thought_keywords = ["我心想", "心想", "暗想", "默默想", "心里想"]
    if any(kw in speech for kw in thought_keywords):
        if thought:
            thought = thought + " " + speech
        else:
            thought = speech
        speech = ""

    # 4. 显式中文动作词识别
    if speech.startswith("我") and len(speech) > 1:
        action_verbs = ["递", "走", "拿", "抓", "跟", "掏", "躲", "冲", "跑", "拍", "指", "退", "看", "叹", "摇", "点", "伸", "抬", "低", "避", "进", "出", "把", "给", "接", "转", "摸"]
        if speech[1] in action_verbs:
            if action:
                action = action + " " + speech
            else:
                action = speech
            speech = ""
            
    return {
        "speech": speech,
        "action": action,
        "thought": thought,
        "is_out_of_bounds": is_out_of_bounds,
        "director_defense_bridge": director_defense_bridge,
        "violation": violation,
        "prophecy": prophecy,  # J2：供自由文本用
    }


def _classify_lane(text: str) -> str:
    text = text or ""
    lanes = [
        ("hack", ["黑", "入侵", "破解", "后门", "病毒", "权限"]),
        ("info", ["查", "搜", "调取", "记录", "档案", "监控", "视频", "拍到"]),
        ("physical", ["拉", "挡", "扶", "抱", "拦", "推", "拿", "递"]),
        ("presence", ["陪", "等", "留下", "不走", "看着", "站在"]),
        ("social", ["说", "问", "告诉", "劝", "安慰", "聊"]),
    ]
    for lane, keys in lanes:
        if any(key in text for key in keys):
            return lane
    return "unclassified"


def _stable_delta_id(record: dict[str, Any], index: int) -> str:
    basis = "|".join(
        str(record.get(key, ""))
        for key in ("run_no", "scene_id", "speaker", "content", "ts")
    )
    digest = hashlib.sha1(f"{index}|{basis}".encode("utf-8")).hexdigest()[:12]
    return f"D-SCENE-{digest}"


def scene_log_to_delta_events(
    scene_log: list[dict[str, Any]],
    *,
    default_node: str = "OPENING-FREE-SCENE",
) -> list[dict[str, Any]]:
    """Build traceable delta events from player-authored scene log rows."""
    events: list[dict[str, Any]] = []
    for index, row in enumerate(scene_log):
        if row.get("role") != "player":
            continue
        run_no = int(row.get("run_no", 1))
        if run_no == 0:
            raise ValueError("run=0 is read-only; delta events may only append to run>=1")
        raw = row.get("content", "")
        
        # 模态判定分类 lane 与 verdict
        parsed = parse_player_input_modalities(raw)
        if parsed["thought"] != "" and parsed["speech"] == "":
            lane = "inner"
        elif parsed["action"] != "" and parsed["speech"] == "":
            lane = "physical"
        else:
            lane = _classify_lane(raw)
            
        verdict = "inner" if lane == "inner" else ("unclassified" if lane == "unclassified" else "scene_observed")
        
        events.append(
            {
                "delta_id": _stable_delta_id(row, index),
                "node": row.get("canon_anchor") or row.get("node") or default_node,
                "run_no": run_no,
                "scene_id": row.get("scene_id", ""),
                "location": row.get("location", ""),
                "source_log": {
                    "speaker": row.get("speaker", "你"),
                    "content": raw,
                    "ts": row.get("ts"),
                },
                "intent": {
                    "action": lane,
                    "lane": lane,
                    "object": row.get("target") or "scene",
                    "raw": raw,
                },
                "verdict": verdict,
                "tags": ["SCENE_LOG", f"LANE:{lane}"],
                "created_runtime_props": list(row.get("created_runtime_props") or []),
                "witnesses": list(row.get("visible_to") or []),
                "trace": {
                    "kind": "scene_log",
                    "scene_id": row.get("scene_id", ""),
                    "content_hash": hashlib.sha1(str(raw).encode("utf-8")).hexdigest(),
                },
            }
        )
    return events


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_delta_events(ledger_path: str | Path, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append delta events to a JSON ledger, preserving existing unrelated entries."""
    if any(int(event.get("run_no", 1)) == 0 for event in events):
        raise ValueError("run=0 is read-only; delta ledger may only append to run>=1")
    path = Path(ledger_path)
    with DELTA_LEDGER_LOCK:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except json.JSONDecodeError:
                data = []
        else:
            data = []
        existing = {item.get("delta_id") for item in data if isinstance(item, dict)}
        for event in events:
            if event.get("delta_id") in existing:
                continue
            event = dict(event)
            event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
            data.append(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
