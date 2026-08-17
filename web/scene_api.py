#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEGACY（2026-07-03 冻结）：逐拍回放管线，不修不删，新能力去 runtime/free_stage_prototype.py；理由见 docs/plans/角色活着_simulation_first_长期计划与工作流重构_2026-07-03.md

scene_api.py -- C1 bridge for Loop B2 group scene runtime.

This is the browser-facing adapter. It keeps the first version deterministic:
no LLM call is required to see the continuous host/NPC/player scene flow.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_RUNTIME = os.path.join(_ROOT, "runtime")
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from scene_runtime import (
    anonymize_text,
    append_scene_log,
    bid_turn_taking,
    build_participant_context,
    build_scene_context,
    check_duplicate_and_progress,
    choose_speakers,
    compose_group_prompt,
    evaluate_gm_pacing,
    load_scene_log,
    validate_director_output,
)
from scene_delta import append_delta_events, scene_log_to_delta_events, parse_player_input_modalities
from runtime_propagation import ingest_created_runtime_props
from scene_contracts import adjudicate_scene_contract, register_branch_progress, resolve_active_exit_state
import llm_transport


_MAP_PATH = os.path.join(_HERE, "opening_map.json")
_SCENE_LOG_PATH = os.path.join(_HERE, "scene_log.jsonl")
_DELTA_LEDGER_PATH = os.path.join(_HERE, "delta_ledger.json")
_RUNTIME_KNOWLEDGE_PATH = os.path.join(_HERE, "runtime_knowledge.json")
_SCHEDULES_PATH = os.path.join(_HERE, "schedules.json")
_PERSONA_CONSTRAINTS_PATH = os.path.abspath(os.path.join(_HERE, "..", "runtime", "persona_constraints.json"))

_PERSONA_CONS_CACHE: dict[str, str] | None = None


def _load_persona_constraints(cons_list: list[str | None]) -> dict[str, str]:
    """读取人格铁律约束卡（cons -> 硬约束串），仅返回在场且有规则的角色。"""
    global _PERSONA_CONS_CACHE
    if _PERSONA_CONS_CACHE is None:
        try:
            with open(_PERSONA_CONSTRAINTS_PATH, "r", encoding="utf-8") as f:
                _PERSONA_CONS_CACHE = json.load(f)
        except Exception:
            _PERSONA_CONS_CACHE = {}
    return {
        c: _PERSONA_CONS_CACHE[c]
        for c in cons_list
        if c and isinstance(_PERSONA_CONS_CACHE.get(c), str)
    }


# soul layer: relational wants + emotional state + kakashi language
_RELATIONAL_WANTS_PATH = os.path.abspath(os.path.join(_HERE, "..", "runtime", "relational_wants.json"))
_RELATIONAL_WANTS_CACHE = None
_KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
_REPEAT_WS_RE = re.compile(r"\s+")
_REPEAT_PUNCT_TRANS = str.maketrans({
    "，": ",",
    "。": ".",
    "！": "!",
    "？": "?",
    "：": ":",
    "；": ";",
    "“": "\"",
    "”": "\"",
    "‘": "'",
    "’": "'",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
})
_ACTOR_SPEAK_PRIMARY_TIMEOUT = 8
_ACTOR_SPEAK_RETRY_TIMEOUT = 6
_ACTOR_SPEAK_TOTAL_BUDGET = 18
_ACTOR_SPEAK_BASE_TEMP = 0.7
_ACTOR_SPEAK_REPEAT_TEMP = 0.9
_ACTOR_SPEAK_RETRY_BACKOFF = 0.75
_ACTOR_SPEAK_MAX_WORKERS = 2


def _load_relational_wants():
    global _RELATIONAL_WANTS_CACHE
    if _RELATIONAL_WANTS_CACHE is None:
        try:
            with open(_RELATIONAL_WANTS_PATH, "r", encoding="utf-8") as f:
                _RELATIONAL_WANTS_CACHE = json.load(f)
        except Exception:
            _RELATIONAL_WANTS_CACHE = {}
    return _RELATIONAL_WANTS_CACHE


def _char_want(cons):
    return (_load_relational_wants().get("characters", {}) or {}).get(cons, {}) or {}


def detect_player_japanese(text):
    return bool(text and _KANA_RE.search(text))


def strip_kana(text):
    if not text:
        return text or ""
    return _KANA_RE.sub("", text)


def _seed_mood(state, cons):
    if state is None:
        return _char_want(cons).get("mood_seed", "neutral")
    if not hasattr(state, "mood") or state.mood is None:
        state.mood = {}
    if cons not in state.mood:
        state.mood[cons] = _char_want(cons).get("mood_seed", "neutral")
    return state.mood[cons]


def _seed_trust(state, cons):
    if state is None:
        return int(_char_want(cons).get("trust_seed", 0))
    if not hasattr(state, "trust_player") or state.trust_player is None:
        state.trust_player = {}
    if cons not in state.trust_player:
        state.trust_player[cons] = int(_char_want(cons).get("trust_seed", 0))
    return state.trust_player[cons]


def update_emotional_state(state, present_cons, turn_type, player_input):
    if state is None:
        return
    jp = detect_player_japanese(player_input)
    for cons in present_cons:
        if not cons:
            continue
        trust = _seed_trust(state, cons)
        mood = _seed_mood(state, cons)
        if turn_type in ("proceed", "grateful", "join") or jp:
            trust = min(3, trust + 1)
            if cons == "C.xiuzai.WMAIN":
                mood = "amused"
            elif cons == "C.akito.WMAIN":
                mood = "warming"
            elif cons == "C.kakashi.WMAIN" and jp:
                mood = "warming"
        elif turn_type in ("deviate", "refuse", "leave"):
            if cons == "C.kakashi.WMAIN":
                trust = max(0, trust - 1)
                mood = "guarded"
            elif cons == "C.xiuzai.WMAIN":
                mood = "irritated"
            elif cons == "C.akito.WMAIN":
                mood = "rebuffed"
        state.trust_player[cons] = trust
        state.mood[cons] = mood
        spark = _player_visible_text(player_input)
        if spark:
            state.last_spark[cons] = spark[:40]


def _fallback_inner(cons, mood):
    m = mood or "neutral"
    table = {
        "C.kakashi.WMAIN": {"guarded": "别被记住，搭句话就走。", "warming": "……这人没恶意，多说两句也无妨。", "default": "礼貌点，别惹注意。"},
        "C.xiuzai.WMAIN": {"irritated": "啧，话真多。", "amused": "有点意思，再逗逗。", "default": "懒得搭理，但顺嘴怼一句。"},
        "C.akito.WMAIN": {"rebuffed": "气氛有点僵，我得赶紧圆回来。", "warming": "聊得挺好，再拉近点。", "default": "想让大家都自在一点。"},
    }
    sub = table.get(cons, {})
    return sub.get(m, sub.get("default", ""))


_ANON_NAMES = {
    "C.kakashi.WMAIN": "银发青年",
    "C.xiuzai.WMAIN": "黑发青年",
    "C.akito.WMAIN": "圆脸青年",
    "C.liuxu.WMAIN": "年轻女子",
}

# 单一来源:runtime/name_book.py(R6 收敛,改名只改名册)
from name_book import API_CAST as _API_CAST, all_aliases as _nb_all_aliases, full_name as _nb_full_name

_REAL_NAMES = {cons: _nb_full_name(cons) for cons in _API_CAST}

_CONS_ALIASES = {cons: [cons] + _nb_all_aliases(cons) for cons in _API_CAST}

_DEFAULT_SCENE = {
    "scene_id": "OPENING_TIANANMEN_001",
    "place": "天安门升旗广场",
    "ch_anchor": 8,
}

_SURFACE_FALLBACKS = {
    "天安门升旗广场": {"scene_label": "升旗后初遇", "time_of_day": "北京清晨"},
    "北京海族馆": {"scene_label": "水母馆偶遇", "time_of_day": "白天"},
    "王府井街道": {"scene_label": "步行街散场", "time_of_day": "傍晚"},
    "街角咖啡厅": {"scene_label": "咖啡厅午后", "time_of_day": "下午"},
}


def _get_git_short_sha() -> str:
    try:
        import subprocess
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT).decode("utf-8").strip()
    except Exception:
        return "unknown"





def is_idle_input(player_input: str | None) -> bool:
    if not player_input:
        return True
    parsed = parse_player_input_modalities(player_input)
    # 心声和动作如果是空的，言语才属于 idle
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5]", "", parsed["speech"]).strip().lower()
    # 如果纯是心理活动 (如 `(这家伙太腹黑了)`，speech和action为空)，我们也认为是 idle 以自然推进
    return cleaned in ("", "在", "的", "了", "然后", "去", "回", "好吧", "go", "next", "continue", "嗯", "好", "继续", "然后呢")


_LEAVE_KEYS = ("再见","先走","回头见","告辞","走了","走啦","拜拜","走吧","我走","该走",
               "不玩了","去咖啡厅","去海洋馆","去王府井","离开","闪了")
# 否定+同意词：必须在 proceed 之前判，命中即"拒绝"
_NEG_AGREE_RE = re.compile(r"(不|别|没|甭|休想|才不|拒绝|不会)(想|要|会|借|给|行|可以|同意|约|帮)")
_REFUSE_MOVE_RE = re.compile(r"(不跟|别跟|才不跟|不一起|不去|不想去|不走)")
_EXACT_AGREE = {"好","行","可以","没问题","同意","好的","行啊","可以啊","没问题啊","嗯好","当然"}
_ACTION_AGREE = ("借给","借你","拿去","给你","可以借","拿去看","给你看","借你们")
_AGREE_SUBSTR = ("可以","好啊","行啊","没问题","同意","当然","拿去","给你")
_FOLLOW_ALONG_SUBSTR = (
    "去看看", "一起走", "一起去", "跟你们走", "跟你走", "我也一起", "那我们也一起",
    "视频发给你们", "发给你们", "发你们", "谢谢你们", "谢谢你", "多谢"
)

def classify_player_turn(player_input: str | None, state=None) -> str:
    """顺序判定，命中即返回：leave > refuse > proceed > deviate。"""
    parsed = parse_player_input_modalities(player_input)
    raw = (parsed["speech"] + " " + parsed["action"]).strip()
    cleaned = re.sub(r"[^\w一-龥]", "", raw).strip()
    if _NEG_AGREE_RE.search(cleaned):          # 修复缺陷①：拒绝优先于同意
        return "refuse"
    if _REFUSE_MOVE_RE.search(cleaned):
        return "refuse"
    
    # 动态匹配：若输入中提及了当前场景的任一出口，则判定为离场 (L3)
    if state and getattr(state, "location", None):
        try:
            map_data = _load_map()
            exits = map_data.get(state.location, {}).get("available_exits", []) or []
            for e in exits:
                p = e.get("place", "")
                if p:
                    p_clean = re.sub(r"[^\w一-龥]", "", p)
                    if p_clean in cleaned or (len(p_clean) >= 2 and p_clean[:2] in cleaned) or (len(p_clean) >= 3 and p_clean[-3:] in cleaned):
                        return "leave"
        except Exception:
            pass

    if any(k in cleaned for k in _LEAVE_KEYS) and not any(w in cleaned for w in _FOLLOW_ALONG_SUBSTR):
        return "leave"
    if is_idle_input(raw):
        return "proceed"
    if cleaned in _EXACT_AGREE:
        return "proceed"
    if any(w in cleaned for w in _ACTION_AGREE):
        return "proceed"
    if any(w in cleaned for w in _FOLLOW_ALONG_SUBSTR):
        return "proceed"
    if len(cleaned) <= 6 and any(w in cleaned for w in _AGREE_SUBSTR):
        return "proceed"
    # 自我介绍模式：含"我是/我叫/叫我/名字是"无论长度均视为正面回应，触发 ack 回环
    if re.search(r"(?:我是|我叫|叫我|名字是)\s*[^\s，。！？,.!?、\)]", cleaned):
        return "proceed"
    # ── G2：示警/危险动作不归 deviate，让语义 condition 有机会判断 ──
    # "快！"、"小心！"、"危险！"、"前面有狗！" 等危险通知类输入
    if any(k in cleaned for k in ("快", "小心", "危险", "有狗", "有车", "注意", "刹车", "闪开", "停车", "前面有", "糟了", "完了", "撞上", "撞了")):
        return "deviate"  # 仍归 deviate，但不在 classify_shortcut 拦截
    return "deviate"


def is_agree_or_proceed_input(player_input: str | None) -> bool:
    return classify_player_turn(player_input) == "proceed"


_COND_CACHE_MAX = 512
_COND_CACHE: OrderedDict[str, bool] = OrderedDict()


def _cond_cache_get(key: str) -> bool | None:
    if key not in _COND_CACHE:
        return None
    value = _COND_CACHE.pop(key)
    _COND_CACHE[key] = value
    return value


def _cond_cache_put(key: str, value: bool) -> None:
    _COND_CACHE[key] = value
    _COND_CACHE.move_to_end(key)
    while len(_COND_CACHE) > _COND_CACHE_MAX:
        _COND_CACHE.popitem(last=False)


def _keyword_rule_match(combined: str, keyword_rules: dict[str, Any] | None) -> bool | None:
    rules = keyword_rules or {}
    negative = tuple(rules.get("negative") or rules.get("deny") or [])
    positive = tuple(rules.get("positive") or rules.get("allow") or [])
    if negative and any(k in combined for k in negative):
        return False
    if positive and any(k in combined for k in positive):
        return True
    return None

def evaluate_condition(
    condition_nl: str | None,
    recent_script: str,
    player_input: str,
    config: dict[str, Any] | None = None,
    path_id: str | None = None,
    keyword_rules: dict[str, Any] | None = None,
) -> bool:
    """G2：新增 path_id 参数作为无条件识别符，替代 condition_nl 中文文本匹配。"""
    if not condition_nl:
        return True

    # 缓存 key 含 path_id 与登记词表，防止跨分支或规则热更新误命中
    keyword_sig = json.dumps(keyword_rules or {}, ensure_ascii=False, sort_keys=True)
    cache_key = f"{player_input} || {condition_nl} || path:{path_id or ''} || kw:{keyword_sig}"
    cached = _cond_cache_get(cache_key)
    if cached is not None:
        return cached

    # 有登记词表的分支必须先由词表裁定。否则“继续观察”这类条件描述中的
    # 普通词会被 classify_player_turn 的 proceed 误当成玩家选择 watch。
    keyword_res = _keyword_rule_match(str(player_input or ""), keyword_rules)
    if keyword_res is not None:
        _cond_cache_put(cache_key, keyword_res)
        return keyword_res
    if keyword_rules and tuple(keyword_rules.get("positive") or keyword_rules.get("allow") or []):
        _cond_cache_put(cache_key, False)
        return False

    turn_type = classify_player_turn(player_input)
    if turn_type == "refuse":
        if any(w in condition_nl for w in ("借", "给", "同意", "答应", "配合", "回答", "自我介绍", "名字")):
            _cond_cache_put(cache_key, False)
            return False
    elif turn_type == "proceed":
        if any(w in condition_nl for w in ("借", "给", "同意", "答应", "配合", "回答", "继续")):
            _cond_cache_put(cache_key, True)
            return True
    elif turn_type == "leave":
        _cond_cache_put(cache_key, False)
        return False

    combined = (recent_script + " " + player_input)
    if path_id == "B1_dog":
        b1_keywords = ("快", "小心", "危险", "有狗", "有车", "前面有", "注意",
                       "糟了", "完了", "撞上", "闪开", "前面出事了")
        b1_neutral = ("发呆", "看着窗外", "不说话", "没反应", "继续听", "先听")
        if any(k in combined for k in b1_keywords):
            _cond_cache_put(cache_key, True)
            return True
        if any(k in combined for k in b1_neutral):
            _cond_cache_put(cache_key, False)
            return False
    if path_id == "choiceA_brace":
        brace_keywords = ("扑", "够", "护", "挡", "抱住", "搂", "护住", "够向", "够到", "拉住")
        non_brace = ("换驾驶", "抢方向盘", "催人上车")
        if any(k in combined for k in non_brace):
            _cond_cache_put(cache_key, False)
            return False
        if any(k in combined for k in brace_keywords):
            _cond_cache_put(cache_key, True)
            return True

    cfg = config or {}
    api_key = (cfg.get("api_key") or "").strip()
    api_url = (cfg.get("api_url") or "").strip()
    model = (cfg.get("model") or "").strip()
    
    if not api_key or not api_url or not model:
        # ── G2 无 API fallback：用 path_id 而非 condition_nl 做无条件识别 ──
        if path_id == "B1_dog":
            _cond_cache_put(cache_key, False)
            return False
        if path_id == "choiceA_brace":
            _cond_cache_put(cache_key, False)
            return False
        if "失眠" in condition_nl or "科普" in condition_nl:
            has_keywords = any(w in combined for w in ("卡卡西", "火影", "漫画", "动漫", "岸本", "助手")) or len(player_input) >= 10
            _cond_cache_put(cache_key, has_keywords)
            return has_keywords
        res = (turn_type == "proceed")
        _cond_cache_put(cache_key, res)
        return res

    parsed = parse_player_input_modalities(player_input)
    player_input_filtered = (parsed["speech"] + " " + parsed["action"]).strip()

    prompt = (
        f"这是目前的剧本：\n"
        f"{recent_script}\n"
        f"玩家刚说：\"{player_input_filtered}\"\n\n"
        f"判断下面这个条件在剧本里是否已满足：\n"
        f"\"{condition_nl}\"\n\n"
        f"只回一个词：YES 或 NO。"
    )

    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {
                "role": "system",
                "content": "你是一个严谨的剧本条件判定器。你只回答 YES 或 NO，不要有任何其他解释字符。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    body.update(llm_transport.chat_request_options(cfg))
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            choices = payload.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip().upper()
                res = "YES" in content
                _cond_cache_put(cache_key, res)
                return res
    except Exception:
        pass

    res = (turn_type == "proceed")
    # 不缓存本地 fallback 结果——它依赖 turn_type，偏离输入不同则结果不同
    return res


def _speaker_to_cons(speaker: str, present: list[dict[str, Any]]) -> str | None:
    for item in present:
        cons = item.get("cons")
        if cons:
            for alias in _CONS_ALIASES.get(cons, []):
                if alias == speaker:
                    return cons
    return None


# ─────────────────────────────────────────────────────────────────
# G1 推进指令隔离
# 纯推进指令不进 NPC/导演可见上下文；在所有 player_input 泄漏到
# LLM 的入口处过滤（_actor_speak_llm_concurrent 的调用点）。
# ═══════════════════════════════════════════════════════════════
_ADVANCE_PATTERNS_G1 = (
    r"^\s*$",
    r"^\s*继续[\s,，。.。]*$",
    r"^\s*下一步(?:\s*[？?。.。]*\s*$|[？?。.。]+$|$)",
    r"^\s*go\s+on\s*$",
    r"^\s*接着(?:\s*[。.。]*\s*$|[。.。]+$|$)",
    r"^\s*然后呢(?:\s*[？?。.。]*\s*$|[？?。.。]+$|$)",
    r"^\s*okay\s*$",
    r"^\s*ok\s*$",
    r"^\s*好的\s*$",
    r"^\s*好\s*$",
    r"^\s*嗯\s*$",
    r"^\s*嗯嗯\s*$",
    r"^\s*行\s*$",
    r"^\s*next\s*$",
    r"^\s*continue\s*$",
)


def is_advance_command_for_api(text: str | None) -> bool:
    """G1：检测 player_input 是否为纯推进指令。"""
    if not text:
        return False
    return any(re.match(p, text.strip(), re.IGNORECASE) for p in _ADVANCE_PATTERNS_G1)


def advance_command_filter(text: str | None) -> str:
    """G1：过滤后的 player_input 进 LLM。纯推进指令返回空字符串（不泄漏）。"""
    if is_advance_command_for_api(text):
        return ""
    return text if text else ""
# ═══════════════════════════════════════════════════════════════


def _check_name_unlock(text: str, state: Any):
    if not text:
        return
    for cons, aliases in _CONS_ALIASES.items():
        real_name = _REAL_NAMES.get(cons)
        if real_name and real_name in text and not state.introduced.get(cons):
            state.introduced[cons] = True
            state.save()


def _reset_introduced_for_scene(state: Any, scene: dict[str, Any]) -> None:
    state.introduced = {
        item["cons"]: False
        for item in scene.get("present_characters", [])
        if item.get("cons")
    }


def _beat_path_ids(beat_data: dict[str, Any] | None) -> list[str]:
    if not isinstance(beat_data, dict):
        return []
    path_ids = []
    single = beat_data.get("path_id")
    if isinstance(single, str) and single.strip():
        path_ids.append(single.strip())
    for key in ("path_ids", "branch_paths"):
        values = beat_data.get(key) or []
        if isinstance(values, list):
            for item in values:
                if isinstance(item, str) and item.strip():
                    path_ids.append(item.strip())
    deduped = []
    for path_id in path_ids:
        if path_id not in deduped:
            deduped.append(path_id)
    return deduped


def _resolve_beat_text(beat_data: dict[str, Any], exit_state: str | None) -> str:
    """从 beat 的 text_variants 里按 exit_state 选文本，没命中则用默认 beat_data['text']"""
    variants = beat_data.get("text_variants", {})
    if not variants:
        return beat_data["text"]
    # exit_state 精确匹配优先，否则 fallback converged/default/无状态
    candidates = [
        exit_state,
        "converged",
        "default",
        None,
    ]
    for key in candidates:
        if key and key in variants:
            return variants[key]
    return beat_data["text"]


def _award_crash_intervention_memory(
    scene: dict[str, Any],
    state: Any,
    active_exit_state: dict[str, Any] | None,
) -> None:
    """Award dynamic memory + trust override for NODE-016-CRASH branch success.
    文案按 activated_paths 组合分化：
      - 仅 B1_dog 命中：玩家觉察到黑影并喊了一声（卡卡西侧：安全带勒痕/修哉侧：黑影轮廓）
      - 仅 choiceA_brace 命中：玩家在撞击瞬间扑向驾驶座（卡卡西侧：玻璃碎屑/修哉侧：爆胎+撞后喘息）
      - 两者皆命中：既喊了也扑了（两条感官锚点叠加）
    """
    if not active_exit_state or active_exit_state.get("id") != "branched_full":
        return
    if scene.get("scene_id") != "OPENING_HIGHWAY_001":
        return

    existing = [
        entry for entry in getattr(state, "dynamic_memory", []) or []
        if entry.get("run_no") == state.run_no
        and entry.get("tag") == "intervention_attempt"
        and entry.get("anchor") == "NODE-016-CRASH:branched_full"
    ]
    if existing:
        return

    activated = set(active_exit_state.get("activated_paths") or [])
    has_dog = "B1_dog" in activated
    has_brace = "choiceA_brace" in activated

    # ── 文案组合（按 path_id 分化） ──
    MEMORY_TABLE = [
        # (描述, 卡卡西侧锚点, 修哉侧锚点, salience_boost)
        (has_dog and not has_brace,
         "撞击前一秒你喊的那声——那不是慌乱，是反应。",
         "卡卡西先看见的不是狗，是你的声音先到了。",
         "你喊的那声比我的反应还快。",
         0.6),
        (not has_dog and has_brace,
         "撞击的瞬间，你整个人扑了过来。",
         "碎玻璃划过去的时候，你已经挡在我和它之间了。",
         "那一下，是你来拉我的。",
         0.6),
        (has_dog and has_brace,
         "你喊了一声，然后整个人扑了过来。",
         "我还没反应过来，你已经把驾驶座那边挡住了。",
         "你先出声，然后整个人冲过来。",
         0.8),
    ]

    for (do_award, kakashi_text, xiuzai_text_k, xiuzai_text_x, salience) in MEMORY_TABLE:
        if not do_award:
            continue
        for cons, text in [("C.kakashi.WMAIN", kakashi_text),
                            ("C.xiuzai.WMAIN", xiuzai_text_x)]:
            state.award_relationship_memory(
                cons_ids=[cons],
                anchor="NODE-016-CRASH:branched_full",
                text=text,
                tag="intervention_attempt",
                salience_boost=salience,
                first_mention_only=True,
            )


def _play_canon_beats(scene: dict[str, Any], state: Any, limit: int = 99, exit_state: str | None = None) -> list[dict[str, Any]]:
    dialogue_flow = scene.get("dialogue_flow", [])
    messages = []
    count = 0
    while state.canon_beat_index < len(dialogue_flow) and count < limit:
        beat_data = dialogue_flow[state.canon_beat_index]

        # 1. 检查是否是玩家选择拍，如果是，跳过它的消息生成，但累加索引并跳出/继续 (L2)
        if beat_data.get("beat_type") == "player_choice":
            if limit > 1:
                # 场景初次加载/自动播放模式：在此处暂停，不要吞掉这一拍，不累加索引，直接跳出
                break
            else:
                # 推进模式：吞掉该选择拍，累加索引并继续播放下一拍
                state.canon_beat_index += 1
                state.save()
                continue

        # 2. 检查是否是自我介绍拍且所有涉及角色都已解锁名字
        if beat_data.get("beat_type") == "introduce":
            introduces = beat_data.get("introduces") or []
            if introduces and all(state.introduced.get(c) for c in introduces):
                # 已经全部介绍过了，直接跳过这一拍，不计入 limit，继续往前
                state.canon_beat_index += 1
                state.save()
                continue

        speaker_cons = _speaker_to_cons(beat_data["speaker"], scene.get("present_characters", []))

        if beat_data.get("beat_type") == "introduce":
            for c in beat_data.get("introduces", []):
                state.introduced[c] = True
            state.save()
            intro_snapshot = dict(state.introduced)
        else:
            intro_snapshot = dict(state.introduced)

        # 按 exit_state 选文本（文案分支核心）
        beat_text = _resolve_beat_text(beat_data, exit_state)

        if speaker_cons:
            msg = {
                "role": "npc",
                "cons": speaker_cons,
                "name": _speaker_name(scene, speaker_cons, state.introduced),
                "stage": beat_data.get("stage", ""),
                "content": beat_text,
                "_introduced_snapshot": intro_snapshot,
            }
            if beat_data.get("beat_type") == "overhear":
                msg["offscreen"] = True
            messages.append(msg)
        else:
            if beat_data["speaker"] in ("导演", "主持人"):
                content_text = beat_text
                if beat_data.get("auto_transition"):
                    import scene_runtime
                    target = scene_runtime._legal_transition_target(scene, _load_map())
                    content_text = _in_world_transition_narration(scene, target)
                messages.append({
                    "role": "director",
                    "name": beat_data["speaker"],
                    "content": content_text,
                    "_introduced_snapshot": intro_snapshot,
                })
            else:
                messages.append({
                    "role": "overhear",
                    "cons": None,
                    "name": beat_data["speaker"],
                    "stage": beat_data.get("stage", ""),
                    "content": beat_text,
                    "_introduced_snapshot": intro_snapshot,
                })

        state.canon_beat_index += 1
        state.save()
        count += 1

        if beat_data.get("beat_type") == "introduce" or beat_data.get("pause_after"):
            break

    return messages


def _load_map() -> dict[str, Any]:
    with open(_MAP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _merged_dialogue_flow(place_info: dict[str, Any], ch_anchor: int) -> list[dict[str, Any]]:
    chapters = place_info.get("chapters", {})
    anchor_flow = chapters.get(str(ch_anchor), {}).get("dialogue_flow", [])
    if len(chapters) <= 1:
        return anchor_flow

    merged_flow: list[dict[str, Any]] = []
    for key in sorted(chapters.keys(), key=lambda value: int(value)):
        chapter_flow = chapters.get(key, {}).get("dialogue_flow", [])
        if isinstance(chapter_flow, list):
            merged_flow.extend(chapter_flow)

    return merged_flow or anchor_flow


def _scene_def(scene_id: str, place: str | None = None, ch_anchor: int | None = None) -> dict[str, Any]:
    place = place or _DEFAULT_SCENE["place"]
    ch_anchor = int(ch_anchor or _DEFAULT_SCENE["ch_anchor"])
    map_data = _load_map()
    if place not in map_data:
        place = _DEFAULT_SCENE["place"]
        ch_anchor = int(_DEFAULT_SCENE["ch_anchor"])
    place_info = map_data.get(place, {})
    chapter_info = place_info.get("chapters", {}).get(str(ch_anchor), {})
    encounter = (chapter_info.get("encounters") or [{}])[0]
    surface_fallback = _SURFACE_FALLBACKS.get(place, {})
    present = [
        {"cons": cons, "name": _ANON_NAMES.get(cons, "陌生青年")}
        for cons in chapter_info.get("present", [])
    ]
    return {
        "scene_id": scene_id,
        "location": place,
        "scene_label": encounter.get("scene_label") or surface_fallback.get("scene_label") or place_info.get("scene_label") or "当前现场",
        "time_of_day": encounter.get("time_of_day") or surface_fallback.get("time_of_day") or place_info.get("time_of_day") or "此刻",
        "current_beat": encounter.get("beat") or place_info.get("blurb", ""),
        "canon_anchor": encounter.get("canon_anchor") or encounter.get("canon_src") or "",
        "ch_anchor": ch_anchor,
        "present_characters": present,
        "dialogue_flow": _merged_dialogue_flow(place_info, ch_anchor),
    }


def _surface(scene: dict[str, Any]) -> dict[str, str]:
    return {
        "location": scene.get("location") or "未知地点",
        "scene_label": scene.get("scene_label") or "当前现场",
        "time_of_day": scene.get("time_of_day") or "此刻",
    }


_FOCUS_STOPWORDS = {
    "我", "我们", "你", "你们", "他", "他们", "这里", "那里", "这个", "那个",
    "一下", "一下子", "真的", "好吧", "好了", "继续", "就是", "什么", "怎么",
    "是不是", "为什么", "然后", "可以", "不要", "不行", "算了",
}


def _player_visible_text(player_input: str | None) -> str:
    parsed = parse_player_input_modalities(player_input or "")
    return " ".join(part for part in (parsed.get("speech"), parsed.get("action")) if part).strip()


def _extract_player_focus(player_input: str | None) -> str:
    text = _player_visible_text(player_input)
    if not text:
        return ""
    normalized = re.sub(r"[“”\"'‘’()（）,，。！？!?：:；;\[\]{}<>《》/\\|]+", " ", text)
    chunks = [chunk.strip() for chunk in normalized.split() if chunk.strip()]
    chunks = [chunk for chunk in chunks if chunk not in _FOCUS_STOPWORDS]
    if not chunks:
        compact = re.sub(r"\s+", "", text)
        return compact[:8]
    chunks.sort(key=len, reverse=True)
    return chunks[0][:12]


def _detect_player_mood(player_input: str | None, refuse: bool = False) -> str:
    text = _player_visible_text(player_input)
    if refuse:
        return "refuse"
    if any(token in text for token in ("假的", "骗人", "不对劲", "有问题", "为什么", "凭什么", "奇怪", "少骗", "骗我", "到底想", "想干嘛", "想干什么", "才不", "不信你", "信你们", "图什么", "什么企图", "别装")):
        return "suspicious"
    if any(token in text for token in ("火星", "外星", "穿越", "造物主", "创造")):
        return "wild"
    if any(token in text for token in ("好吧", "既然", "算了", "随便", "无所谓", "你们这么说")):
        return "reluctant"
    if any(token in text for token in ("谢谢", "多谢", "借我手机", "发给你们")):
        return "grateful"
    if any(token in text for token in ("一起走", "跟你们走", "去看看", "接下来去哪", "下一站")):
        return "join"
    if any(token in text for token in ("不去", "不想", "不要", "走开")):
        return "guarded"
    return "neutral"


def _location_kind(location: str) -> str:
    loc = location or ""
    # A place name alone cannot prove the later shooting has happened.  The
    # legacy API receives bare locations in several callers, so treating every
    # street-corner cafe as post-ambush leaks future canon into a calm scene.
    if "街角咖啡厅" in loc:
        return "cafe"
    if "咖啡" in loc or "鍜栧暋" in loc:
        return "cafe"
    if "海族" in loc or "水母" in loc or "娴锋棌" in loc or "姘存瘝" in loc:
        return "aquarium"
    if "王府井" in loc or "鐜嬪簻浜" in loc:
        return "wangfujing"
    if "天津" in loc or "张尘" in loc or "真纪家" in loc:
        return "tianjin"
    if "十六中" in loc or "校门口" in loc:
        return "school_gate"
    if "医院" in loc or "急救室" in loc:
        return "hospital_wait"
    if "高速" in loc or "京津" in loc or "伏击" in loc:
        return "highway"
    if "天安门" in loc or "升旗" in loc or "广场" in loc:
        return "tiananmen"
    return "generic"


def _location_anchor_text(location: str) -> str:
    kind = _location_kind(location)
    if kind == "cafe":
        return "咖啡杯口还冒着热气"
    if kind == "ambush_cafe":
        return "街边的枪声还压在耳膜里"
    if kind == "aquarium":
        return "水母缸里的蓝光仍在晃"
    if kind == "wangfujing":
        return "街边的人潮还在往前挤"
    if kind == "tianjin":
        return "客厅里的电话铃声像随时都会再响"
    if kind == "school_gate":
        return "校门口的放学人潮还没有散完"
    if kind == "hospital_wait":
        return "走廊里的消毒水味还没散开"
    if kind == "highway":
        return "爆胎冒出的橡胶焦味还没散"
    if kind == "generic":
        return "周围的动静还没完全静下来"
    return "广场上的风声还没完全散去"


def _tethered_reaction(cons: str, location: str, player_input: str | None, nudge: bool, refuse: bool, variant: int = 0) -> tuple[str, str] | None:
    text = _player_visible_text(player_input)
    if not text:
        return None

    kind = _location_kind(location)
    focus = _extract_player_focus(player_input)
    anchor = _location_anchor_text(location)
    mood = _detect_player_mood(player_input, refuse=refuse)
    quoted = f"“{focus}”" if focus else "你刚才那句话"

    if mood == "refuse":
        if cons == "C.akito.WMAIN":
            return (
                "他怯了一下，但还是把声音放轻了。",
                f"{quoted}里的拒绝他听得很明白。{anchor}，他小心地补了一句：“没事，你要是不想，我们就先不逼你。”",
            )
        if cons == "C.xiuzai.WMAIN":
            return (
                "他把原本要说的话收了回去，只是挑了挑眉。",
                f"{quoted}的意思已经足够直白。{anchor}，他嘴里还是松了松：“行，那就先按你的意思来。”",
            )
        return (
            "他先看了看你的表情，才平稳地接下这句话。",
            f"{quoted}让气氛明显停了一下。{anchor}，他温和地说：“我明白，你可以先按自己舒服的方式来。”",
        )

    if mood == "suspicious":
        v = (variant or 0) % 3
        if cons == "C.xiuzai.WMAIN":
            opts = [
                ("他听见你说奇怪，反而像终于来了兴趣，嘴角一挑。",
                 f"{anchor}，他懒懒地顶回去：“防着我们？算你有点眼力。可光防着没用——想知道，自己跟来看。”"),
                ("他斜眼看你，毒舌里却带了点认真。",
                 f"{quoted}让他没急着辩解。{anchor}，他说：“怀疑挺好，比傻乎乎跟着强。可你这么拦着，真纪那边不等人。”"),
                ("他嗤了一声，没有否认。",
                 f"{anchor}，他丢下一句：“觉得我们有鬼，大可以走。没人求你信——只是那样你就什么都看不到了。”"),
            ]
            return opts[v]
        if cons == "C.kakashi.WMAIN":
            opts = [
                ("他听懂了你的警惕，反而退后半步，话很短。",
                 f"{anchor}，他低声说：“你怀疑……没错。我们不强求。”"),
                ("他没有解释，把视线移开，像不愿被追问。",
                 f"{quoted}他听进去了，却没有顺势粉饰。{anchor}，他只低声道：“我现在讲不清。你要么跟来看，要么现在就走。”"),
                ("他神色一紧，礼貌却疏远。",
                 f"{anchor}，他简短地说：“有些事我不能讲。信不信，由你。”"),
            ]
            return opts[v]
        if kind == "tianjin" and cons == "C.akito.WMAIN":
            opts = [
                ("他被你这句质疑卡了一下，没再硬装轻松。",
                 f"{anchor}，他压低声音说：“我知道这局面很怪，可现在最要紧的是医院那边。张尘是谁、魏初那边出了什么事，待会儿你都会亲眼看到。”"),
                ("他抓了抓头，先把你的警惕接住了。",
                 f"{quoted}让他没有再打哈哈。{anchor}，他说：“你不信也正常。可这边已经不是等真纪姐回消息那么简单了，先把人送到医院再说。”"),
                ("他明显想解释，却又知道自己说不清。",
                 f"{anchor}，他只好老实地说：“我现在拿不出能让你立刻相信的东西。你要是愿意，就先跟着看完这一步。”"),
            ]
            return opts[v]
        if kind == "school_gate" and cons == "C.zhangchen.WMAIN":
            opts = [
                ("他看出你在防备，却没有笑着糊弄过去。",
                 f"{anchor}，他把语速放慢：“怀疑我也正常。我只是来问路，顺便确认几个人的去向，不急着让你现在信。”"),
                ("他被你的质疑噎住半拍，随后干脆把态度放低。",
                 f"{quoted}让他没再兜圈子。{anchor}，他说：“你觉得我可疑，可以离远点看着；但这边等会儿真会出事。”"),
                ("他眼神顿了顿，没把问题推回给你。",
                 f"{anchor}，他只说：“我现在解释不明白。你要是想知道我在等什么，就别太早走。”"),
            ]
            return opts[v]
        opts = [
            ("他被你的质疑噎了一下，没急着打圆场。",
             f"{quoted}让他没急着打圆场。{anchor}，他挠挠头：“我证明不了什么……你信不过也正常。真纪要在就好了，她兴许能替我们说句话。”"),
            ("他挠了挠头，干脆把话挑明。",
             f"{quoted}让他不再打圆场。{anchor}，他说：“你说得对，是有点不对劲。所以才更得去看看，不是吗？”"),
            ("他咽了口唾沫，声音放低却没躲闪。",
             f"{anchor}，他认真地说：“我也说不清哪里怪，但站在这儿猜没用——去王府井，当面问真纪。”"),
        ]
        return opts[v]

    if mood == "wild":
        if cons == "C.akito.WMAIN":
            return (
                "他睨大了眼睛，像是被你的跳跃想法冒到，但又觉得有点好笑。",
                f"{quoted}这种说法让他忍不住多看了你一眼。{anchor}，他半真半假地说：“要不先别飞到那么远，先把这个下一站看完行吗？”",
            )
        if cons == "C.xiuzai.WMAIN":
            return (
                "他觉得离谱的地方反而把话听进去了。",
                f"{quoted}让他短暂地扭过头来。{anchor}，他不冲你抬杠，只是说：“先别把话题扔到天上，先把面前的事情看完。”",
            )
        return (
            "他眼神略微一顿，但还是把话题稳地接住了。",
            f"{quoted}让现场的气氛突然止了一下。{anchor}，他语气温和地说：“先不着急得出答案，我们先看看这一站之后会发生什么。”",
        )

    if mood == "reluctant":
        if kind == "tiananmen":
            if cons == "C.akito.WMAIN":
                return (
                    "他听出这句答应里带着敷衍，反而更快把重点摆到明处。",
                    f"{anchor}，他赶紧解释：“你不用马上信我们。先看一眼升旗视频就行，我表姐真纪还在等这个画面。”",
                )
            if cons == "C.xiuzai.WMAIN":
                return (
                    "他没有把你的敷衍当成热情，嘴角反而弯了一下。",
                    f"{anchor}，他懒懒地说：“这态度倒挺清醒。跟不跟都行，不过我们待会儿会去王府井等真纪，你至少知道我们不是原地编故事。”",
                )
            return (
                "他没有急着劝你，只把话说得更实在一点。",
                f"{anchor}，他说：“不信也正常。你先把我们当成临时同行者，等真纪回来，你再决定要不要继续。”",
            )
        if kind == "generic":
            if cons == "C.akito.WMAIN":
                return (
                    "他听出这句答应里带着敷衍，没再往前逼。",
                    f"{anchor}，他说：“可以，你先按自己的节奏来；要是不想接话，我们就把眼前的事处理完。”",
                )
            if cons == "C.xiuzai.WMAIN":
                return (
                    "他没有把你的敷衍当成热情，只是轻轻挑了下眉。",
                    f"{anchor}，他说：“随便也算一种态度。先看完这一步，之后你要走也没人拦。”",
                )
            return (
                "他把话停住半拍，没有把你的随口答应当成热情。",
                f"{anchor}，他说：“好，那先不争。你看着办，我们继续把当前这件事处理完。”",
            )

    if mood == "grateful":
        if kind == "cafe":
            if cons == "C.akito.WMAIN":
                return (
                    "他赶紧摆手，像是怕你把这件事算得太正式。",
                    f"{anchor}，他说：“不是借不借手机的问题，是你刚才帮了大忙。等去王府井找到真纪姐，我一定让她当面道谢。”",
                )
            if cons == "C.xiuzai.WMAIN":
                return (
                    "他靠在椅背上，语气还是懒洋洋的，但没有把你的感谢推开。",
                    f"{anchor}，他说：“谢秋人就行。顺便，王府井那边要是真没人，你就知道这事不只是借手机了。”",
                )
            return (
                "他把你的客气接住，却没有让话题停在客套上。",
                f"{anchor}，他说：“谢意先收下。下一步还是得去王府井，真纪没出现之前，这件事还没完。”",
            )
        if cons == "C.akito.WMAIN":
            return (
                "他立刻露出松了口气的表情。",
                f"{anchor}，他说：“该我谢谢你才对。那段视频对真纪姐真的很重要。”",
            )
        return (
            "他没有把你的感谢当成结束语，而是顺势把话接下去。",
            f"{anchor}，他说：“客气的话先放一边。等见到真纪，这件事才算落地。”",
        )

    if mood == "join":
        if kind == "cafe":
            if cons == "C.akito.WMAIN":
                return (
                    "他眼睛一亮，立刻把手机举起来看了一眼时间。",
                    f"{anchor}，他说：“那就一起走。王府井离这儿不远，真纪姐要是到了，应该会先往人多的地方钻。”",
                )
            if cons == "C.xiuzai.WMAIN":
                return (
                    "他像是早猜到你会这么说，慢吞吞地站直了一点。",
                    f"{anchor}，他说：“行，临时队友加一。去王府井，别让秋人继续把咖啡当早饭。”",
                )
            return (
                "他听见你愿意跟上，语气明显放松了一点。",
                f"{anchor}，他说：“那就一起去王府井。路上如果哪里不对，你随时停下来问。”",
            )

    loc_shift = sum(ord(c) for c in location)
    v = (variant + loc_shift) % 3

    if cons == "C.akito.WMAIN":
        opts = [
            ("他看着你，像是终于找到一个可以继续说下去的台阶。",
             f"{anchor}，他把语气放轻了些：“那就先往前走一站吧。要是你觉得不对劲，路上随时说。”"),
            ("他挠了挠头，朝前指了指，试图缓和气氛。",
             f"{anchor}，他说：“咱们边走边说吧，站风口里也聊不痛快。”"),
            ("他赶紧打了个哈哈，把话头引向下一步行程。",
             f"{anchor}，他说：“先跟上吧，等见到我姐，想问什么当面问她更清楚。”")
        ]
        return opts[v]

    if cons == "C.xiuzai.WMAIN":
        opts = [
            ("他把视线停在你身上几秒，像是在权衡选哪种说法。",
             f"{anchor}，他淡淡地补了一句：“别急着下结论。先走到下一个地方，你大概就知道我们是不是在胡扯。”"),
            ("他扯了扯嘴角，没冷场，但语气依旧随意。",
             f"{anchor}，他说：“怀疑是好事，不过光站着怀疑可什么都查不出来，不如跟去看看。”"),
            ("他把手揣进外套口袋，不紧不慢地偏了偏头。",
             f"{anchor}，他说：“先别急着下定义。去前面看看，真假你自己心里会有数。”")
        ]
        return opts[v]

    # C.kakashi.WMAIN / 坂本晴明
    opts = [
        ("他接住你的视线，没有急着替你做决定。",
         f"{anchor}，他温和地说：“我明白。这个话题可以先聊着看，如果你觉得哪里不对，就直接打断我们。”"),
        ("他善意地笑笑，顺着路标的方向侧过身。",
         f"{anchor}，他说：“北京这片我们也不太熟，多个人同行也热闹些，先朝前走走看吧。”"),
        ("他偏了偏头，神色柔和地看着你，没有催促。",
         f"{anchor}，他说：“你可以先跟着我们走一段。如果中途觉得无聊了，随时可以离开。”")
    ]
    return opts[v]


def _speaker_name(scene: dict[str, Any], cons: str, introduced: dict[str, bool] = None) -> str:
    if introduced and introduced.get(cons):
        return _REAL_NAMES.get(cons, cons)
    for item in scene.get("present_characters", []):
        if item.get("cons") == cons:
            return item.get("name") or cons
    return cons


def _reaction_rotation_key(scene: dict[str, Any], cons: str) -> str:
    scene_id = scene.get("scene_id") or scene.get("location") or "default"
    return f"{scene_id}:{cons}"


def _fallback_variant(player_input: str | None, options: list[tuple[str, str]], variant: int = 0) -> tuple[str, str]:
    if not options:
        return "", ""
    seed = player_input or ""
    idx = (sum(ord(ch) for ch in seed) + int(variant or 0)) % len(options)
    return options[idx]


_FALLBACK_ROTATION: dict[str, int] = {}


def _rotating_fallback_variant(key: str, options: list[tuple[str, str]]) -> tuple[str, str]:
    if not options:
        return "", ""
    idx = _FALLBACK_ROTATION.get(key, 0)
    _FALLBACK_ROTATION[key] = idx + 1
    return options[idx % len(options)]


def _scene_fallback_line(cons: str, location: str, player_input: str | None = None, variant: int = 0) -> tuple[str, str]:
    loc = location or "天安门升旗广场"
    kind = _location_kind(loc)
    anchor = _location_anchor_text(loc)
    if variant >= 4:
        if cons == "C.akito.WMAIN":
            return _fallback_variant(player_input, [
                ("他笑着打破沉默，指了指前方的路。", f"{anchor}，诶，站着也是站着，要不边走边聊？"),
                ("他侧身让开路过的人，先把目光放回你这边。", f"{anchor}，要是不想走太快，就先在这里缓一会儿。"),
                ("他没有催你，只抬手指了指前方较空的地方。", f"{anchor}，前面没那么挤。要不要换个地方再说？"),
                ("他把脚步收住，等你自己决定要不要跟上。", f"{anchor}，我先不往前凑。你想动的时候叫我一声。"),
                ("他看了看周围的空隙，声音放得轻快却不催促。", f"{anchor}，这会儿人流松了一点。我们可以慢慢走。"),
                ("他把伸出去的手又收回，像是把选择留给了你。", f"{anchor}，不急着选方向。先看你现在想待在哪里。"),
            ], variant)
        if cons == "C.xiuzai.WMAIN":
            return _fallback_variant(player_input, [
                ("他叹了口气，有些懒散地摊了摊手。", f"{anchor}，……行吧，你不说话，那我替你说。晴明，走了。"),
                ("他往旁边让了半步，没有逼你接话。", f"{anchor}，不想说就先别说。人又不会因为你沉默就消失。"),
                ("他扫了一眼周围的动静，语气放得比刚才短。", f"{anchor}，站在这儿耗着也行。等你想开口再开口。"),
                ("他靠到不挡路的地方，把急着追问的劲头收了起来。", f"{anchor}，我不替你做决定。要走要留，你自己挑。"),
                ("他抬眼看了看前方，没再用话把你往哪边推。", f"{anchor}，这里还算安静。想理清楚了再动也不晚。"),
                ("他把手插回口袋，给这段沉默留了余地。", f"{anchor}，不接话没关系。反正我也不赶着听答案。"),
            ], variant)
        if cons == "C.kakashi.WMAIN":
            return _fallback_variant(player_input, [
                ("他看着你局促的样子，眼神温和地安抚道。", f"{anchor}，（日语）不急。你按你的节奏来就好。"),
                ("他把脚步放慢，给你留出不会被催促的距离。", f"{anchor}，（日语）我们先看着周围。你准备好了再说。"),
                ("他没有追问，只把视线从人群里收回来。", f"{anchor}，（日语）不用马上决定。先留在这里也可以。"),
                ("他站到稍侧一点的位置，替你挡开经过的人。", f"{anchor}，（日语）这里不需要逞强。先把呼吸放稳。"),
                ("他抬眼确认周围没有新的动静，才重新看向你。", f"{anchor}，（日语）我会在。你不用为了回应谁而着急。"),
                ("他把手从口袋里抽出来又停住，没有擅自碰你。", f"{anchor}，（日语）想往前走时告诉我；现在停着也没关系。"),
            ], variant)
    
    if kind == "cafe":
        if cons == "C.akito.WMAIN":
            return "他吸了一口咖啡，笑着看着你。", "这里的拿铁味道还挺不错的。对了，你等会儿打算去哪儿逛？"
        if cons == "C.xiuzai.WMAIN":
            return "他托着下巴，懒洋洋地看了一眼同伴。", "秋人，喝你的咖啡吧。人家说不定有自己的计划。"
        return "他温和地笑笑，把话题接了过去。", "别介意，他总是这样藏不住话。不过，北京的清晨确实很有活力。"
    elif kind == "ambush_cafe":
        if cons == "C.akito.WMAIN":
            return "他把相机护在胸前，声音被枪声压得发紧。", "先别站着，往遮挡后面退！我会看着街口。"
        if cons == "C.xiuzai.WMAIN":
            return "他贴着桌沿矮下身，视线已经扫向对面楼层。", "别抬头。开枪的人还没走远。"
        return "他把声音压得很低，目光没有离开街边的死角。", "先确认有没有第二个射手，再动。"
        
    elif kind == "aquarium":
        if cons == "C.akito.WMAIN":
            return "他兴奋地指着玻璃缸里的蓝色水母。", "哇！这些发光水母真漂亮，真想养一只在家里。"
        if cons == "C.xiuzai.WMAIN":
            return "他摇了摇头，有些无奈地笑笑。", "养在家里？那大概需要一整个海水循环系统吧。"
        visible = player_input or ""
        if "跟" in visible or "配合" in visible:
            return "他从水母缸前退开半步，给人流让出一点空隙。", "人群在往表演区走。跟上可以，但别离玻璃太近。"
        if "伸手" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:reach:{visible}", [
                ("他被你突兀的动作弄得一怔，先看了看周围有没有危险。", "这里暂时没有车，也没有撞击声。先把手放低。"),
                ("他避开旁边经过的游客，轻轻按住你的手腕。", "你要够谁？先看清楚，我们现在不在车里。"),
                ("他下意识往后让了半步，视线从你手上移到人群。", "别急着伸手。这里还没有需要你扑过去的东西。"),
            ])
        if "护住" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:brace:{visible}", [
                ("他下意识往旁边让开半步，目光迅速扫过人群。", "别急。现在是在水族馆，危险如果出现，也不会从挡风玻璃外冲进来。"),
                ("他没有笑你的紧张，只把你往人少的位置带了半步。", "先站稳。真有危险，我们再一起处理。"),
                ("他看了一眼你的防备姿势，声音低了下来。", "护住自己没错，但先确认危险真的在这里。"),
            ])
        if "撞击" in visible or "前面有情况" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:impact:{visible}", [
                ("他压低声音，像是在把你从某个瞬间拉回现场。", "你反应太快了。先确认眼前是什么地方。"),
                ("他扶住旁边的栏杆，确认水槽前没有真正的冲撞。", "慢一点。你像是提前看见了什么，但这里还没发生。"),
                ("他看了一眼你的手，又看向玻璃后的蓝光。", "现在先别扑。这里能撞上来的只有游客和推车。"),
            ])
        if "点头" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:nod:{visible}", [
                ("他见你点头，便把话停在不会打扰人流的位置。", "那就在这里停一下。水母缸前至少没那么挤。"),
                ("他轻轻点头回应，视线仍落在蓝色水光里。", "嗯。先看一会儿也好，别急着往前挤。"),
                ("他把脚步放慢，像是默认你已经跟上节奏。", "好，那就按这个速度走。人群散开前别离太远。"),
            ])
        if "听" in visible or "安静" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:listen:{visible}", [
                ("他把声音放低，像是怕惊动玻璃后的蓝光。", "那就先听水声吧。这里至少比外面适合把话说慢。"),
                ("他看着水槽里缓慢漂浮的影子，语气也跟着慢下来。", "安静一点也好。外面太吵，这里还能听见自己在想什么。"),
                ("他没有催你回答，只把脚步停在不挡路的位置。", "先站一会儿吧。等人流散开，再决定往哪边走。"),
            ])
        if "按" in visible:
            return "他看了看水槽边的指示牌，语气仍然很轻。", "先按你觉得舒服的节奏走。这里绕一圈也不会太突兀。"
        if "看" in visible or "皱眉" in visible:
            return "他察觉到你的视线，没有立刻把话题推开。", "你是在看我，还是在看那只水母？两边都挺奇怪的。"
        if "没接" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:no_reply:{visible}", [
                ("他没有把你的沉默当成拒绝，只把话收得更短。", "不接也行。先走到前面人少的地方。"),
                ("他避开旁边经过的游客，给你留出半步距离。", "那就先不说这个。等安静一点再谈。"),
                ("他看了你一眼，没有继续追问。", "我明白。这里不是适合解释的地方。"),
            ])
        if "等" in visible:
            return _rotating_fallback_variant(f"{loc}:{cons}:aquarium:wait:{visible}", [
                ("他停了一下，把没说完的话收得更短。", "嗯。那就先不急着解释，等走到人少一点的地方。"),
                ("他没有追着你的沉默问下去，只看了看前方的人流。", "先把这段路走完。等声音小一点，我再回答你。"),
                ("他把目光从水槽上移开，像是在给你留出判断的时间。", "不接话也可以。这里至少还能让人缓一口气。"),
                ("他让开一名经过的游客，才把声音压低。", "等一下也行。这里人太多，话说急了只会更乱。"),
                ("他把手插回口袋，像是接受了这段沉默。", "那就先把问题放着。等前面空一点，再慢慢拆。"),
                ("他看了你一眼，没有把沉默当成拒绝。", "我知道你还在判断。先走到不挡路的地方。"),
            ])
        return _fallback_variant(player_input, [
            ("他看着水缸中漂浮的水母，语气很轻。", "深海的幽蓝色确实让人平静，仿佛时间都流逝得慢了一些。"),
            ("他把视线从水母缸移回来，声音压得很低。", "这里光线太暗，反而让人容易把话说慢一点。"),
            ("他望着玻璃后的蓝光，像是终于找到了一个不刺眼的方向。", "先在这里停一下也好，人群没那么挤。"),
        ], variant)
        
    elif kind == "wangfujing":
        if cons == "C.akito.WMAIN":
            return "他在人潮边缘停住脚步，频频看向手机。", "真纪姐还是没回。要不先去海族馆？她追过来也有个明确地方。"
        if cons == "C.xiuzai.WMAIN":
            return "他被人流挤得往旁边让了一步，语气还是懒散。", "继续在这里等，只会把秋人等成路标。换个地方吧。"
        visible = player_input or ""
        if "跟" in visible:
            return "他确认你跟上后，才把视线转向更醒目的路牌。", "别离太远。海族馆比这里好认，真纪找过来也不会被人潮吞掉。"
        if "看" in visible:
            return "他察觉到你的视线，停了半拍，语气仍然很轻。", "你也觉得这里太挤了吧。先换个能看清人的地方。"
        if "没接" in visible or "等" in visible:
            return "他没有追问你为什么沉默，只朝人流外侧偏了偏头。", "不想接也没关系。先离开这段人潮，再慢慢想问什么。"
        if "皱眉" in visible or "警惕" in visible:
            return "他注意到你的戒备，脚步没有逼得太近。", "保持警惕是对的。这里人太多，先换个能看清四周的位置。"
        if "听" in visible or "示意" in visible:
            return "他把话压短，像是只给你一个能跟上的方向。", "往前一点。等真纪回电话，我们再把事情说清楚。"
        return _fallback_variant(player_input, [
            ("他望向街口的人潮，没有把话说成告别。", "先别散。真纪如果真找过来，海族馆比这条街好认得多。"),
            ("他侧身避开迎面的人流，朝前面的路牌看了一眼。", "这里太容易走散。换个更醒目的地方等她吧。"),
            ("他把手机收回口袋，语气没有催促，却已经转向街口。", "王府井人太密，真纪要找我们也难。先往海族馆那边走。"),
        ], variant)
    elif kind == "tianjin":
        if cons == "C.akito.WMAIN":
            return "他把声音压得很轻，像是怕惊动客厅里那点紧绷。", "电话要是再响一次，情况大概还会更糟。我们先别把人心弄乱。"
        if cons == "C.zhangchen.WMAIN":
            return "他坐姿没怎么变，只是把目光从手机屏幕上抬了起来。", "我先在这边待命。要去医院也行，我开车。"
        return "他看了一眼客厅另一头的动静，把话说得很稳。", "先把消息等全，再决定谁去医院、谁留在这边。"
    elif kind == "school_gate":
        if cons == "C.zhangchen.WMAIN":
            return "他站在人流边上，没有急着往前拦人。", "我真只是问路。要是你们知道十六中往哪边走，告诉我一声就行。"
        if cons == "C.banbo.WMAIN":
            return "她侧过身避开人流，眼神里还带着点警惕。", "放学点人这么多，突然跑来搭话的本来就可疑。"
        return "她朝校门口那边看了一眼，像是在确认还有没有别的人跟过来。", "先别急着走，这人看着不像单纯迷路。"
    elif kind == "hospital_wait":
        if cons == "C.kakashi.WMAIN":
            return "他靠在走廊的墙边，视线钉在急救室那盏红灯上。", "……等吧。现在能做的只有等。"
        if cons == "C.xiuzai.WMAIN":
            return "他站在一旁，没有平时的懒散，眼神沉得不像话。", "里面的情况……比我们想的要糟。"
        if cons == "C.zhangchen.WMAIN":
            return "他把手机攥得很紧，像是在忍着不往急救室门口冲。", "人已经送进去了，剩下的只能等医生出来。"
        if cons == "C.banbo.WMAIN":
            return "她坐也不是站也不是，视线总往急救室门口飘。", "我爸还在里面……现在说什么都没用。"
        return "她把声音放低，像是怕惊动走廊里每一点动静。", "先等等吧，消息应该很快就会出来。"

    elif kind == "highway":
        if cons == "C.kakashi.WMAIN":
            return "他盯着挡风玻璃外的黑暗，手还搭在安全带上。", "别乱动，先看清楚外面到底是什么。"
        if cons == "C.xiuzai.WMAIN":
            return "他脸色发白，声音比平时短得多。", "这年头连狗都跟我们过不去……你没事吧？"
        return "车厢里的引擎声压过了别的动静。", "先稳住，路上的事我们两个人应付得来。"

    elif kind == "generic":
        # 中性兜底：新地点没有专属分支时，宁可平淡也不窜戏
        is_director_tick = (player_input is None or player_input == "director_tick")
        if not is_director_tick:
            if cons == "C.akito.WMAIN":
                return "他眼睛一亮，几乎立刻接住了你的话。", "嗯，你说得对。我们先把眼前的事理清楚。"
            if cons == "C.kakashi.WMAIN":
                return _fallback_variant(player_input, [
                    ("他没急着接话，只是先看着你，等你继续。", "我听着。你先说完。"),
                    ("他把话头停住，视线仍然留在你这边。", "嗯，我在听。你把意思说完整。"),
                    ("他没有抢着判断，只是轻轻点了一下头。", "先按你说的来，我们再看下一步。"),
                ], variant)
            if cons == "C.xiuzai.WMAIN":
                return "他懒懒地扬了下眉，没有打断你。", "行，你先讲。别讲到一半又把锅丢给我。"
            return "他把视线从远处收回来，看向你。", "先理清眼前的事再决定下一步吧。"
        else:
            if cons == "C.akito.WMAIN":
                return "他先看了一眼周围，才把注意力放回你身上。", "怎么了？有什么想说的？"
            if cons == "C.kakashi.WMAIN":
                return "他没出声，只是安静地在旁边等着。", "先看看情况吧。"
            if cons == "C.xiuzai.WMAIN":
                return "他靠在一边，神色没什么波动。", "急也没用，先看清楚再说。"
            return "气氛安静了一瞬。", "先看看接下来会发生什么。"

    else:
        # 天安门升旗广场
        is_director_tick = (player_input is None or player_input == "director_tick")
        if not is_director_tick:
            if cons == "C.akito.WMAIN":
                return "他眼睛一亮，几乎立刻接住了你的话。", "真的可以吗？太好了，我就看一小段，不会乱翻你的东西。"
            if cons == "C.xiuzai.WMAIN":
                return "他偏过头看你，像是在判断你是不是随口客气。", "你还挺好说话的嘛。秋人，别把人家设备摔了。"
            return _fallback_variant(player_input, [
                ("他观察了一下你的反应，语气温和地把话接稳。", "谢谢。我们只是想留个纪念，如果不方便也没关系。"),
                ("他把同伴往后拦了半步，先确认你没有被催得不舒服。", "如果你愿意帮忙，我们会记住这份人情；不愿意也没关系。"),
                ("他看了一眼秋人，又把视线转回你这边。", "别被他说得太急。你方便的话，看一眼就好。"),
            ], variant)
        else:
            if cons == "C.akito.WMAIN":
                return "他先看向你手里的记录设备，语气轻快又有点不好意思。", "那个……你刚才是不是拍到升旗了？能不能借我们看一眼？"
            if cons == "C.xiuzai.WMAIN":
                return "他没有直接靠近，只在旁边懒洋洋地补了一句。", "秋人，别见谁都搭话。"
            return "他把同伴稍微往后拦了半步，朝你露出一个礼貌的笑。", "抱歉，他只是有点兴奋。"


def _reaction_line(cons: str, scene: dict[str, Any], player_input: str | None, nudge: bool, refuse: bool, variant: int = 0) -> tuple[str, str]:
    tethered = _tethered_reaction(cons, scene.get("location") or "", player_input, nudge, refuse, variant)
    if tethered is not None:
        return tethered
    loc = scene.get("location") or "天安门升旗广场"
    kind = _location_kind(loc)
    
    if kind == "ambush_cafe":
        if refuse:
            return "他没把视线从街口移开，只把声音压得更低。", "现在不是争的时候。先蹲下，活着再说。"
        if nudge:
            if cons == "C.akito.WMAIN":
                return "他咽了一下，还是强迫自己把话说清楚。", "你说的我听见了。先找遮挡，我来记对面楼层。"
            if cons == "C.xiuzai.WMAIN":
                return "他冷冷扫了你一眼，语速比平时更短。", "怀疑可以，别站成靶子。先趴下。"
            return "他侧身挡住半边视线，语气仍旧克制。", "我明白。先把人群从枪线里带出去。"
        if cons == "C.akito.WMAIN":
            return "他把相机按在怀里，脸色发白却还在看街口。", "我拍到了方向，但现在先别看，退到桌子后面！"
        if cons == "C.xiuzai.WMAIN":
            return "他压低身体，眼神一下子冷了下来。", "十层。别抬头，他在等第二个目标。"
        return "他站位往你和街边之间错了半步，声音很轻。", "先别乱跑，枪线还没断。"

    if kind == "cafe":
        if refuse:
            if cons == "C.akito.WMAIN":
                return "有些尴尬地抓了抓头，打了个哈哈。", "哈哈，没事没事，我们也就随便聊聊。"
            if cons == "C.xiuzai.WMAIN":
                return "端起咖啡抿了一口，神色懒散。", "秋人，都说了别打扰人家。"
            return "端正地坐着，礼貌地微笑道歉。", "抱歉，是我们太唐突了。北京的咖啡味道还不错吧？"
        elif nudge:
            if cons == "C.akito.WMAIN":
                return "眨了眨眼，神秘兮兮地把头凑过来。", "对了，你听说过火影忍者的那个原画吗？其实我还挺了解的。"
            if cons == "C.xiuzai.WMAIN":
                return "有些无聊地用手指敲着桌面。", "真纪怎么还没来……喂，你说她是不是又堵在路上了？"
            return "温和地笑笑，顺着话题引导。", "我们今天其实是在这里等一个朋友，等她到了再一起商量行程。"
        else:
            if cons == "C.akito.WMAIN":
                return "喝了一大口拿铁，一脸满足。", "这家店的咖啡味道真香，出来旅游喝上一杯热的太舒服了。"
            if cons == "C.xiuzai.WMAIN":
                return "用勺子轻轻搅拌着咖啡，托着腮。", "北京的空气确实很干燥，不过屋里倒是很暖和。"
            return "微笑地看着你们，语气温和平缓。", "其实我们刚从日本过来，对这附近还不算太熟悉。"

    elif kind == "aquarium":
        if refuse:
            if cons == "C.akito.WMAIN":
                return "摸了摸鼻子，有些不好意思。", "啊，那不好意思打扰啦，我去看水母了。"
            if cons == "C.xiuzai.WMAIN":
                return "双手插兜，打了个哈欠。", "自讨没趣，走吧秋人。"
            return "友好地微微点头。", "打扰了，祝你逛得愉快。"
        elif nudge:
            if cons == "C.akito.WMAIN":
                return "指着水母缸，有些兴奋地对你说。", "你快看！那个蓝色的水母好漂亮，我们要不要过去拍一张？"
            if cons == "C.xiuzai.WMAIN":
                return "懒洋洋地瞥了眼水母缸。", "晴明，这儿人挺多的，咱们别走散了。"
            return "温和地提醒。", "深海的幽蓝色确实容易让人安静，但也要注意别跟人群走散了。"
        else:
            if cons == "C.akito.WMAIN":
                return "趴在玻璃栏杆前，眼睛亮亮地看着水母。", "水族馆的灯光真棒，像是在看一个深海的童话。"
            if cons == "C.xiuzai.WMAIN":
                return "看着玻璃缸里呼吸的水母，表情放松下来。", "水母这种生物，据说连大脑都没有，真让人羡慕。"
            return "在旁边静静地看着光影流动。", "光斑落在水面上的感觉很美，好像时间都被放慢了。"

    elif kind == "wangfujing":
        if refuse:
            if cons == "C.akito.WMAIN":
                return "叹了口气，有些垂头丧气。", "好吧好吧，我也就随口问问。"
            if cons == "C.xiuzai.WMAIN":
                return "撇了撇嘴，拽了拽同伴的衣角。", "走了走了，别在路中间挡道。"
            return "礼貌地颔首。", "打扰了，那我们先往前走了。"
        elif nudge:
            if cons == "C.akito.WMAIN":
                return "他在人潮里踮脚看了一圈，还是没找到真纪。", "这样等也不是办法。海族馆目标更明显，她真追过来也找得到。"
            if cons == "C.xiuzai.WMAIN":
                return "他扫了一眼越来越密的人流，懒懒地把话压短。", "别把自己等成路标。去海族馆，至少比在这里发呆强。"
            return "望向街口的人流，语气仍然平稳。", "先换个更好认的地方吧。真纪如果出现，海族馆比这条街容易碰上。"
        else:
            if cons == "C.akito.WMAIN":
                return "他捏着手机，明显还在等真纪回消息。", "她还是没回。我们先去海族馆吧，别在这儿把人跟丢了。"
            if cons == "C.xiuzai.WMAIN":
                return "他被路人挤得往旁边避了半步，皱了皱眉。", "王府井适合迷路，不适合找人。走吧，换个地方。"
            return "看着人潮从身边涌过，没有把话说成告别。", "继续站在这里，线索只会被人流冲散。先去海族馆。"
    elif kind == "tianjin":
        if refuse:
            if cons == "C.akito.WMAIN":
                return "他把话咽回去，没再硬撑着活跃气氛。", "行，那先不聊这个。医院和家里这两头已经够乱了。"
            if cons == "C.zhangchen.WMAIN":
                return "他点了下头，没有追问。", "明白。你们先按自己的节奏来，需要车的时候叫我。"
            return "他看出你不想接话，便顺势收住了。", "先把消息理顺吧，别在这种时候互相逼着表态。"
        elif nudge:
            if cons == "C.akito.WMAIN":
                return "他往门口那边看了一眼，心思明显还在医院。", "魏初姐那边催得急，我们最好别在这儿耽搁太久。"
            if cons == "C.zhangchen.WMAIN":
                return "他站起身，像是已经把下一步想清楚了。", "要去医院的话现在就能走。我认路，也认人。"
            return "他把手机屏幕按亮又熄灭，像在等下一条消息。", "再给医院那边回个电话，确认完就动身。"
        else:
            if cons == "C.akito.WMAIN":
                return "他坐不太住，话说到一半总要往门口瞄。", "本来只是来接真纪姐，结果一下子全都变成医院的事了。"
            if cons == "C.zhangchen.WMAIN":
                return "他语气不高，却把事情说得很实。", "初姐让我先守在这边。你们要去医院，我负责把人带过去。"
            return "他把话压得很轻，像是不想让客厅更乱。", "先分清谁留下谁过去，别再让消息在半路断掉。"
    elif kind == "school_gate":
        if refuse:
            if cons == "C.zhangchen.WMAIN":
                return "他退了半步，没有继续拦人。", "抱歉，是我唐突了。"
            if cons == "C.banbo.WMAIN":
                return "她抱起手臂，语气立刻硬了点。", "都说了不熟，别再追着问。"
            return "她往旁边挪了挪，把距离拉开。", "放学点别跟陌生人纠缠太久。"
        elif nudge:
            if cons == "C.zhangchen.WMAIN":
                return "他像是怕错过谁似的，又往校门口看了一眼。", "除了问路，我还在等几个人。你们要是见过他们，告诉我也行。"
            if cons == "C.banbo.WMAIN":
                return "她压低声音，明显不想让更多人听见。", "这人不像单纯找学校的，你看他一直盯着人流。"
            return "她看着来来往往的学生，语速很快。", "先别被他带着走，弄清楚他到底在等谁。"
        else:
            if cons == "C.zhangchen.WMAIN":
                return "他站在校门口外侧，像是在让自己看起来不那么像拦人的。", "十六中就在这附近吧？我第一次来，怕走岔了。"
            if cons == "C.banbo.WMAIN":
                return "她没完全放下戒心，说话时还看着对方。", "放学点跑来问路的人不少，但他确实有点怪。"
            return "她把书包往肩上拽了拽，没有立刻走开。", "要不先看看他到底想干什么。"
    elif kind == "hospital_wait":
        if refuse:
            if cons == "C.zhangchen.WMAIN":
                return "他应了一声，没再逼人说话。", "好，先等医生。别的都晚点再说。"
            if cons == "C.banbo.WMAIN":
                return "她红着眼眶，把脸别开了。", "我现在不想聊。"
            return "她点点头，像是在忍着情绪。", "先安静一会儿吧。"
        elif nudge:
            if cons == "C.zhangchen.WMAIN":
                return "他看了一眼急救室上方的红灯，声音压得极低。", "等医生出来前，我们至少得把该通知的人都通知到。"
            if cons == "C.banbo.WMAIN":
                return "她手指攥着衣角，话说得很急。", "要不要再问一次护士？总不能一直这么等。"
            return "她往走廊尽头看了看，像是怕下一秒就有人冲出来。", "先把能做的事做了，剩下的只能等。"
        else:
            if cons == "C.zhangchen.WMAIN":
                return "他站在急救室外，没有平时那种游刃有余。", "消息一来得太快，车一停下就直接推进去了。"
            if cons == "C.banbo.WMAIN":
                return "她盯着急救室门口，声音发飘。", "刚才还好好的，怎么一下子就成这样了……"
            return "她把呼吸压得很轻，像怕一开口就散掉。", "等灯灭吧，灯灭了至少能知道下一步怎么办。"

    elif kind == "highway":
        if refuse:
            if cons == "C.kakashi.WMAIN":
                return "他没再多问，视线转回窗外。", "行，那你先别出声，我盯着路。"
            if cons == "C.xiuzai.WMAIN":
                return "他耸了耸肩，语气还是懒懒的。", "不想说就算了，反正也没工夫聊天。"
            return "车厢里安静了一瞬，只有引擎声。", "先这样吧，路况比闲聊要紧。"
        elif nudge:
            if cons == "C.kakashi.WMAIN":
                return "他眉头没松开，手仍搭在安全带上。", "有话现在说，等下未必还有空档。"
            if cons == "C.xiuzai.WMAIN":
                return "他勉强笑了一下，视线却没离开窗外。", "别转移话题，刚才那团黑影你也看见了吧？"
            return "车速没变，气氛却绷紧了一点。", "先看着前面，这条路今晚不太对劲。"
        else:
            if cons == "C.kakashi.WMAIN":
                return "他盯着挡风玻璃外的黑暗，声音压得很低。", "别乱动，先看清楚外面到底是什么。"
            if cons == "C.xiuzai.WMAIN":
                return "他脸色发白，却还硬撑着开玩笑。", "这年头连狗都跟我们过不去……你没事吧？"
            return "车厢里的引擎声压过了别的动静。", "先稳住，路上的事我们两个人应付得来。"

    else:
        # 默认：天安门升旗广场
        if refuse:
            if cons == "C.akito.WMAIN":
                return "有一点尴尬，但很快堆起笑容。", "诶别介嘛……那算了算了。"
            if cons == "C.xiuzai.WMAIN":
                return "双手插兜，撇了撇嘴。", "啧，人家不乐意，你还真上赶着。"
            return "礼貌地微微欠身。", "无妨，是我们唐探了。"
        elif nudge:
            if cons == "C.akito.WMAIN":
                return "凑近了一点，神神秘秘地小声说。", "对了，刚说的那个升旗的录像……方便的话给瞅一眼呗？"
            if cons == "C.xiuzai.WMAIN":
                return "斜眼看过来，指了指你的设备。", "既然都碰上了，不如把刚才录到的借圆脸看一下，免得他一直念叨。"
            return "温和地解释。", "如果方便的话，能借用一下刚才的升旗视频么？我们刚好错过了。"
        else:
            if cons == "C.akito.WMAIN":
                return "抓了抓头发，有些无奈。", "你这人说话真有意思，不过咱们现在正缺录像呢。"
            if cons == "C.xiuzai.WMAIN":
                return "叹了口气，靠在旁边的栏杆上。", "圆脸，你就别给人家添乱了。"
            return "好奇地打量着你的录影设备。", "谢谢。北京的清晨确实很有活力啊，不过比起录像，我觉得交流更重要呢。"


def _fallback_npc_turn(scene: dict[str, Any], player_input: str | None, state, nudge: bool = False, refuse: bool = False) -> list[dict[str, Any]]:
    speakers = choose_speakers(scene, player_input, max_speakers=2)
    if not speakers:
        present_chars = scene.get("present_characters", [])
        if present_chars:
            valid_chars = [item for item in present_chars if item.get("cons") and not item["cons"].startswith("C.player")]
            if valid_chars:
                speakers = [{"cons": valid_chars[0]["cons"]}]
            else:
                speakers = [{"cons": "C.akito.WMAIN"}]
        else:
            speakers = [{"cons": "C.akito.WMAIN"}]
            
    messages = []
    jp = detect_player_japanese(player_input)
    for sp in speakers:
        cons = sp.get("cons")
        if not cons:
            continue
        rotation_key = _reaction_rotation_key(scene, cons)
        _rot = (state.react_rotation.get(rotation_key, 0) if (state is not None and getattr(state, "react_rotation", None) is not None) else 0)
        stage, dialogue = _reaction_line(cons, scene, player_input, nudge, refuse, variant=_rot)
        if state is not None:
            if getattr(state, "react_rotation", None) is None:
                state.react_rotation = {}
            state.react_rotation[rotation_key] = _rot + 1
        mood = _seed_mood(state, cons)
        lang = "ja" if (cons == "C.kakashi.WMAIN" and jp) else "zh"
        if cons == "C.kakashi.WMAIN":
            dialogue = strip_kana(dialogue)
        messages.append({
            "role": "npc",
            "cons": cons,
            "name": _speaker_name(scene, cons, state.introduced if state else None),
            "stage": stage,
            "inner": _fallback_inner(cons, mood),
            "content": dialogue,
            "lang": lang,
        })
    if state is not None:
        state.save()
    return messages


def _proceed_ack_line(scene: dict[str, Any], player_input: str | None, state) -> dict[str, Any] | None:
    if _location_kind(scene.get("location") or "") != "tiananmen":
        return None
    return {
        "role": "npc",
        "cons": "C.akito.WMAIN",
        "name": _speaker_name(scene, "C.akito.WMAIN", state.introduced if state else None),
        "stage": "眼睛一亮，立刻把手机攥紧了一点。",
        "content": "真的可以？那先别急着散，我表姐还等着这段升旗视频。"
    }


def _extract_player_self_intro_name(player_input: str | None) -> str | None:
    text = _player_visible_text(player_input) or ""
    match = re.search(r"(?:我是|我叫|叫我|名字是)\s*([^\s，。！？,.!?、]{1,12})", text)
    if not match:
        return None
    name = match.group(1).strip("“”\"'：:；;")
    return name or None


def _player_thread_ack_line(scene: dict[str, Any], player_input: str | None, state) -> dict[str, Any] | None:
    name = _extract_player_self_intro_name(player_input)
    if not name:
        return None
    present = [
        item.get("cons") for item in scene.get("present_characters", [])
        if item.get("cons") and not item["cons"].startswith("C.player")
    ]
    cons = "C.akito.WMAIN" if "C.akito.WMAIN" in present else (present[0] if present else None)
    if not cons:
        return None
    if cons == "C.xiuzai.WMAIN":
        stage = "他把你的名字在舌尖过了一遍，像是顺手把线头拎住。"
        content = f"{name}是吧？行，至少这句我听见了。"
    elif cons == "C.kakashi.WMAIN":
        stage = "他慢半拍地点点头，先把你的自我介绍接住。"
        content = f"{name}。嗯，我记住了。"
    else:
        stage = "他先接住你的名字，语气明显松了一点。"
        content = f"{name}是吧？我记住了。那个，先谢谢你愿意帮忙。"
    return {
        "role": "npc",
        "cons": cons,
        "name": _speaker_name(scene, cons, state.introduced if state else None),
        "stage": stage,
        "content": content,
    }


def _bridge_line(scene: dict[str, Any], player_input: str | None, turn_type: str, state) -> dict[str, Any] | None:
    present = [item.get("cons") for item in scene.get("present_characters", []) if item.get("cons") and not item["cons"].startswith("C.player")]
    cons = "C.akito.WMAIN" if "C.akito.WMAIN" in present else (present[0] if present else None)
    if not cons:
        return None
    bridge = _tethered_reaction(cons, scene.get("location") or "", player_input, True, turn_type == "refuse")
    if bridge is None:
        bridge = (
            "他先把情绪压住，再把话题稳稳接了下去。",
            "你话里的那点情绪他听出来了，但他没有立刻把话掐死，而是带着你把话题拉回当下。",
        )
    stage, content = bridge
    return {
        "role": "npc",
        "cons": cons,
        "name": _speaker_name(scene, cons, state.introduced if state else None),
        "stage": stage,
        "content": content,
    }


def _render_turn(scene: dict[str, Any], speakers: list[dict[str, Any]], player_input: str | None = None, introduced: dict[str, bool] = None, variant: int = 0) -> dict[str, Any]:
    messages = []
    location = scene.get("location") or "未知地点"
    intro_snap = dict(introduced) if introduced is not None else {}
    if not player_input:
        messages.append({
            "role": "director",
            "name": "主持人",
            "content": scene.get("current_beat", ""),
            "_introduced_snapshot": intro_snap,
        })
    elif not speakers:
        messages.append({
            "role": "director",
            "name": "主持人",
            "content": f"这句话落在{location}的人声里，几个人都只是短暂看向你，没有立刻接话。",
            "_introduced_snapshot": intro_snap,
        })
    for offset, speaker in enumerate(speakers):
        stage, dialogue = _scene_fallback_line(speaker["cons"], location, player_input, variant + offset)
        messages.append({
            "role": "npc",
            "cons": speaker["cons"],
            "name": _speaker_name(scene, speaker["cons"], introduced),
            "stage": stage,
            "content": dialogue,
            "_introduced_snapshot": intro_snap,
        })
    return {"messages": messages, "needs_player_response": True}


def _compact_dialogue_text(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _repair_repeated_npc_lines(rendered: dict[str, Any], scene: dict[str, Any], state: SceneState, player_input: str | None) -> None:
    messages = rendered.get("messages") or []
    if not messages:
        return
    location = scene.get("location") or ""
    seen = {
        _compact_dialogue_text(item.get("content"))
        for item in (scene.get("recent_log") or [])
        if item.get("role") in ("npc", "overhear")
    }
    state_seen = getattr(state, "seen_npc_lines", None)
    if not isinstance(state_seen, dict):
        state_seen = {}
        state.seen_npc_lines = state_seen
    location_seen = state_seen.setdefault(location, [])
    seen.update(location_seen)
    local_seen: set[str] = set()
    present_cons = [
        item.get("cons") for item in scene.get("present_characters", [])
        if item.get("cons") and not item["cons"].startswith("C.player")
    ]
    for idx, msg in enumerate(messages):
        if msg.get("role") != "npc":
            continue
        compact = _compact_dialogue_text(msg.get("content"))
        if len(compact) < 8:
            continue
        duplicate = compact in seen or compact in local_seen
        local_seen.add(compact)
        if not duplicate:
            continue
        cons = msg.get("cons") or (present_cons[idx % len(present_cons)] if present_cons else None)
        if not cons:
            continue
        stage, content = _scene_fallback_line(
            cons,
            location,
            player_input,
            state.canon_beat_index + getattr(state, "repeat_count", 0) + idx + 1,
        )
        msg["cons"] = cons
        msg["name"] = _speaker_name(scene, cons, state.introduced)
        msg["stage"] = stage
        msg["content"] = content
        compact = _compact_dialogue_text(content)
        local_seen.add(compact)
    for msg in messages:
        if msg.get("role") != "npc":
            continue
        compact = _compact_dialogue_text(msg.get("content"))
        if len(compact) >= 8 and compact not in location_seen:
            location_seen.append(compact)
    if len(location_seen) > 80:
        state_seen[location] = location_seen[-80:]
    state.save()


def _messages_from_director_output(output: dict[str, Any], scene: dict[str, Any], introduced: dict[str, bool] = None) -> dict[str, Any]:
    messages = []
    intro_snap = dict(introduced) if introduced is not None else {}
    narration = (output.get("narration") or "").strip()
    if narration:
        messages.append({
            "role": "director",
            "name": "主持人",
            "content": narration,
            "_introduced_snapshot": intro_snap,
        })
    for item in output.get("speakers", []):
        messages.append({
            "role": "npc",
            "cons": item.get("cons"),
            "name": _speaker_name(scene, item.get("cons"), introduced),
            "stage": item.get("stage", ""),
            "content": item.get("dialogue", ""), "inner": item.get("inner", ""), "lang": item.get("lang", "zh"),
            "_introduced_snapshot": intro_snap,
        })
    return {
        "messages": messages,
        "needs_player_response": bool(output.get("needs_player_response", True)),
        "state_updates": output.get("state_updates", {}),
    }


def _normalize_director_output(output: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    present = {item.get("cons") for item in scene.get("present_characters", []) if item.get("cons")}
    alias_to_cons: dict[str, str] = {}
    for cons, aliases in _CONS_ALIASES.items():
        if cons in present:
            for alias in aliases:
                alias_to_cons[alias] = cons
    for item in output.get("speakers", []) or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("cons")
        if raw in alias_to_cons:
            item["cons"] = alias_to_cons[raw]
    return output


def strip_scratch(text: str) -> str:
    if not text:
        return ""
    t = text
    t = re.sub(r"\[DIRECTOR\s+ADJUDICATION\].*?$", "", t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r"Meta_State\s+Sidecar\s*\{.*?\}", "", t, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"Meta_State\s*\{.*?\}", "", t, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"\[DIRECTOR\s+ADJUDICATION\]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Meta_State\s+Sidecar", "", t, flags=re.IGNORECASE)
    return t.strip()


def _in_world_transition_narration(scene: dict[str, Any], target: dict[str, Any] | None) -> str:
    current_place = scene.get("location") or ""
    target_place = (target or {}).get("place") or ""
    if current_place == "天安门升旗广场" and target_place == "广场旁咖啡厅":
        return "广场上的风渐渐散开，几句没说完的话被带进附近的咖啡香里。"
    if current_place == "天安门升旗广场" and target_place == "北京海族馆":
        return "和三人在广场暂时分别后，你稍后也动身前往北京海族馆，却意外地在海族馆门口再次碰见了他们。"
    if current_place == "广场旁咖啡厅" and target_place == "王府井街道":
        return "咖啡厅的门在身后合上，清晨的人流把一行人推向王府井。"
    if current_place == "北京海族馆" and target_place == "街角咖啡厅":
        return "水母馆前的人潮越聚越密，馆外的喧闹把他们带向街角咖啡厅。"
    if current_place == "王府井街道" and target_place == "北京海族馆":
        return "真纪的电话仍旧没有打来。王府井的人潮把等待冲得越来越散，继续站在这里只会把线索等散。"
    if current_place == "王府井街道" and target_place == "天津·真纪家见张尘":
        return "在接到真纪的一通奇怪电话后，你们临时改变了计划，买票登上了前往天津的城际列车，前往真纪的家。"
    if current_place == "王府井街道" and target_place == "十六中校门口":
        return "王府井的喧嚣逐渐远去，你独自一人乘上了前往十六中的公交，回到那个承载了许多回忆的校门口。"
    if target_place:
        return f"当前地点的话题暂时收住，下一段路把视线引向{target_place}。"
    return "当前地点的话题暂时收住，下一段路在门外接上。"


def _hold_scene_narration(scene: dict[str, Any], player_input: str | None = None) -> str:
    location = scene.get("location") or "现场"
    if location == "天安门升旗广场":
        return "你的话音落进广场的人声里，几个人只是彼此看了一眼，脚步还留在原地。"
    if location == "街角咖啡厅":
        return "桌边短暂安静了几秒，几个人交换了个眼神，谁也没有急着起身离开。"
    if location == "北京海族馆":
        return "水光在几人脸上轻轻晃过，短暂的沉默之后，他们仍旧停在原地没有散开。"
    return "现场安静了一瞬，几个人都还留在原地，没有立刻转身离开。"


def _is_same_scene_target(scene: dict[str, Any], current_scene_id: str, target: dict[str, Any] | None) -> bool:
    if not target:
        return False
    return (
        (target.get("scene_id") and target.get("scene_id") == current_scene_id)
        or ((target.get("place") or "") == (scene.get("location") or ""))
    )


def _is_scene_visited(run_no: int, scene_id: str) -> bool:
    from scene_state import SceneState
    try:
        path = SceneState.get_path(run_no, scene_id)
        if isinstance(path, str):
            return os.path.exists(path)
        elif hasattr(path, "exists"):
            return path.exists()
        return os.path.exists(str(path))
    except Exception:
        return False


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_repeat_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip().translate(_REPEAT_PUNCT_TRANS)
    text = _REPEAT_WS_RE.sub(" ", text)
    return text


def _collect_recent_self_dialogues(
    scene: dict[str, Any],
    cons: str,
    sample_window: int = 3,
    max_items: int = 2,
    max_chars: int = 80,
) -> list[str]:
    if not scene or not scene.get("recent_log"):
        return []
    candidates: list[str] = []
    seen_norms: set[str] = set()
    for item in reversed(scene["recent_log"]):
        if item.get("cons") != cons or item.get("role") != "npc":
            continue
        content = (item.get("content") or "").strip()
        if not content:
            continue
        norm = _normalize_repeat_text(content)
        if not norm or norm in seen_norms:
            continue
        seen_norms.add(norm)
        clipped = content[:max_chars].strip()
        candidates.append(clipped)
        if len(candidates) >= sample_window:
            break
    if not candidates:
        return []
    return list(reversed(candidates[-max_items:]))


def _actor_temperature(scene: dict[str, Any], cons: str, soul: dict[str, Any]) -> float:
    soul = soul or {}
    if soul.get("repeat_count", 0) < 1:
        return _ACTOR_SPEAK_BASE_TEMP
    if not _collect_recent_self_dialogues(scene, cons):
        return _ACTOR_SPEAK_BASE_TEMP
    return _ACTOR_SPEAK_REPEAT_TEMP


def _visible_recent_scene_lines(scene: dict[str, Any], cons: str | None = None, limit: int = 6) -> list[tuple[str, str]]:
    if not scene or not scene.get("recent_log"):
        return []
    lines: list[tuple[str, str]] = []
    allowed_roles = {"player", "npc", "director", "overhear"}
    for item in scene["recent_log"]:
        if item.get("role") not in allowed_roles:
            continue
        if item.get("role") == "npc" and cons and item.get("cons") != cons:
            continue
        speaker = item.get("speaker", "主持人")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        lines.append((speaker, content))
    return lines[-limit:]


def _build_actor_speak_prompt(
    cons: str,
    voice_ctx: dict[str, Any],
    scene: dict[str, Any],
    player_input: str,
    next_canon_beat: dict[str, Any] | None = None,
    hard_constraints: str | None = None,
    soul: dict[str, Any] | None = None,
) -> tuple[str, float, list[str]]:
    soul = soul or {}
    recent_self_dialogues = _collect_recent_self_dialogues(scene, cons)
    temperature = _actor_temperature(scene, cons, soul)
    parsed = parse_player_input_modalities(player_input)
    player_action = parsed["action"]
    player_speech = parsed["speech"]

    input_desc = []
    if player_action:
        input_desc.append(f"玩家做出动作: *{player_action}*")
    if player_speech:
        input_desc.append(f"玩家说: \"{player_speech}\"")

    input_str = "、".join(input_desc) if input_desc else "（无）"

    lines = [
        f"你扮演《存在的意义：因果之外》中的角色：{cons}（{_speaker_name(scene, cons)}）。",
        "请根据你的设定、近因以及玩家的最新言语与动作，说下一句台词。可以直接带上肢体动作描述（stage）。",
        "【设计指令：出戏/元提问化解规则】",
        "若玩家提出的言语或动作涉及系统设定、第四面墙、AI/游戏或“正典/非正典”等元概念（如问“这是正典吗”），你必须假装完全听不懂或答非所问，绝不要顺着玩家提及这些元词汇（不可实体化“正典书”或承认是游戏/AI），在戏内以正常角色的疑惑口吻回应，继续维持沉浸感。",
        "",
        f"当前地点: {scene.get('location')}",
        f"玩家最新行动: {input_str}",
    ]

    # 正典约束卡（anchored 档位）
    if next_canon_beat or hard_constraints:
        lines.append("\n【正典铁律 · 不可违背】")
        if hard_constraints:
            lines.append(f"- 你的人格硬约束: {hard_constraints}")
        if next_canon_beat:
            nsp = next_canon_beat.get("speaker", "")
            ntx = next_canon_beat.get("text", "")
            lines.append(f"- 你接下来要自然地把对话引向这一拍（锚点，别跳过、别抢别人台词）:")
            lines.append(f"    下一正典拍 = {nsp}:「{ntx}」")
            lines.append("- 即兴只能是通往这一拍的过渡；不要引入新支线、新人物、新地点。")

    visible_recent = _visible_recent_scene_lines(scene, cons=cons)
    if visible_recent:
        lines.append("\n最近场景对话:")
        for speaker, content in visible_recent:
            lines.append(f"- {speaker}: {content}")
    if recent_self_dialogues:
        lines.append("\n【你刚刚已经说过的原句，禁止换皮重述】:")
        for text in recent_self_dialogues:
            lines.append(f"- {text}")
        lines.append("这次必须换角度、换措辞，并把互动往前推进半步；禁止只改几个词后重复同一意思。")
            
    lines.append(f"\n你的表层设定: {voice_ctx.get('persona_surface') or ''}")
    
    voice_brief = voice_ctx.get("voice_brief") or {}
    voice_rules = [str(item) for item in (voice_brief.get("rules") or []) if item]
    if voice_rules:
        lines.append("VOICE_BRIEF:")
        for rule in voice_rules[:5]:
            lines.append(f"- {rule}")

    voice_lines = [q.get("text", "") for q in voice_ctx.get("voice_samples", []) if q.get("text")]
    if voice_lines:
        lines.append("你的语气与说话口吻示例（请模仿其风格）：")
        for q in voice_lines[:3]:
            lines.append(f"  * {q}")
            
    agenda = voice_ctx.get("agent_state", {}).get("short_term_agenda", {})
    if agenda.get("text"):
        lines.append(f"你当下的短期计划/动机: {agenda['text']}")
        next_scene = agenda.get("next_scene")
        if next_scene and isinstance(next_scene, dict) and next_scene.get("place"):
            lines.append(
                f"注意：你有一个可以带领大家前往的下一地点: {next_scene.get('place')}。 "
                "如果你认为当前对话时机已经合适（例如玩家同意了，或者聊得差不多了），你可以在输出的 JSON 中加入 \"action\": \"transition\" 字段，主动提出并开始带大家去下一地点。"
            )
        
    always = [item.get("text", "") for item in voice_ctx.get("lorebook", {}).get("always", []) if item.get("text")]
    keyed = [item.get("text", "") for item in voice_ctx.get("lorebook", {}).get("keyed", []) if item.get("text")]
    facts = always[:3] + keyed[:3]
    if facts:
        lines.append("你当前知道的事实:")
        for fact in facts:
            lines.append(f"  - {fact}")
            
    forbidden = [pid for pid in voice_ctx.get("forbidden_prop_ids", []) if pid]
    if forbidden:
        lines.append("【绝对不可触碰、提及或暗示的秘密命题ID】:" + "、".join(forbidden))
        lines.append("请确保你的台词不泄露上述命题包含的任何内容。")
        
    soul = soul or {}
    _w = _char_want(cons)
    if _w.get("want"):
        lines.append("\n【你此刻的关系性想要（灵魂，决定你怎么演，不决定剧情走向）】: " + _w["want"])
    _mood = soul.get("mood")
    if _mood:
        lines.append("你此刻的情绪: " + str(_mood) + "（信任玩家 " + str(soul.get("trust", 0)) + "/3）。让它真实地染你的语气；该警惕就警惕，该毒舌就毒舌，别为讨好玩家而软化。")
        if str(_mood) in ("guarded", "irritated", "rebuffed"):
            lines.append("玩家此刻明显敌意/质疑。别急着打圆场、别用‘一起去看看/别担心/我们也急’这类话把怀疑抹平，也别用推进剧情的客套句盖过这场对峙；先让你的人格真实接住这份敌意（警惕、毒舌或坦白），再谈其他。")
    if soul.get("last_spark"):
        lines.append("你记得玩家刚做的一件事: " + str(soul["last_spark"]))
    if soul.get("repeat_count", 0) >= 1:
        lines.append("注意：玩家已连续重复同样的话。别重述你上一拍说过的内容、也别换皮重说；要么把剧情往前推进一步，要么直接点破这种重复。")
    if cons == "C.kakashi.WMAIN":
        if soul.get("player_lang_ja"):
            lines.append("玩家用日语跟你搭话——你切到母语，说得流利放松、愿意多说（lang 填 ja）。但台词一律用中文呈现，绝不出现任何日语假名。")
        else:
            lines.append("你的中文不好（不是全才）：说简短、磕巴、偶尔语序略怪的中文（lang 填 zh）。绝不出现任何日语假名。")
    # R1+R2：无 canon 可推进（终点/free）时，逼角色主动按 want 行动 + 换对话动作
    if next_canon_beat is None:
        lines.append(
            "\n【此刻没有既定剧情要推进——别干等玩家发问】：你有自己想要的东西（见上方关系性想要/动机）。"
            "主动做点什么——顺着它往前带半步、抛出你自己的观察或情绪、或换个话题，而不是被动应答。"
            "并且这一拍换一种回应方式：别重复上一拍的套路（例如总用闪避加轻嘲），要么露一条新信息或新情绪，要么把互动推进一点。"
        )
    lines.append(
        '\n请严格按以下 JSON 格式输出，不要包含任何其他字符：\n'
        '{"stage": "一句话描述你的神态/动作", "dialogue": "你说的一句台词", "action": "可选，如果发起转场则填 \'transition\'，否则不填或设为 null"}'
    )
    lines.append("另外在同一个 JSON 里再追加两个字段：inner（你没说出口的内心独白，一句，不展示给玩家）与 lang（zh 或 ja，仅卡卡西用日语时填 ja，文本仍为中文）。")

    return "\n".join(lines), temperature, recent_self_dialogues


def should_route_slow_path(
    req_data: dict[str, Any],
    scene: dict[str, Any],
    recent_log: list[dict[str, Any]],
    contract_result: dict[str, Any],
    gm_pacing: dict[str, Any]
) -> bool:
    op = req_data.get("op", "start_scene")
    if op == "start_scene":
        return True
    player_input = req_data.get("player_input", "")
    if not player_input:
        return True
    if gm_pacing.get("should_transition"):
        return True
    if contract_result.get("mode") == "converge":
        return True
    if contract_result.get("covered"):
        return True
    text = player_input.strip()
    if len(text) > 6:
        return True
    if any(key in text for key in ("再见", "走了", "拜拜", "出发", "移动", "咖啡厅", "海洋馆", "王府井")):
        return True
    return False


def _classify_actor_llm_error(exc: Exception) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    return llm_transport.classify_request_error(exc)


def _call_actor_llm_once(
    prompt: str,
    config: dict[str, Any],
    temperature: float,
    timeout: float,
) -> tuple[dict[str, Any] | None, str | None]:
    cfg = config or {}
    api_key = (cfg.get("api_key") or "").strip()
    api_url = (cfg.get("api_url") or "").strip()
    model = (cfg.get("model") or "").strip()
    if not api_key or not api_url or not model:
        return None, "missing_config"

    body = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {
                "role": "system",
                "content": "你只输出符合协议的角色发声 JSON，不要输出任何解释。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    body.update(llm_transport.chat_request_options(cfg))
    try:
        payload = llm_transport.post_json(
            api_url,
            api_key,
            body,
            timeout=timeout,
        )
        choices = payload.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            parsed = _extract_json_object(content)
            if parsed:
                return parsed, None
        return None, "empty_result"
    except Exception as exc:
        return None, _classify_actor_llm_error(exc)


def _actor_speak_llm_with_debug(
    cons: str,
    voice_ctx: dict[str, Any],
    scene: dict[str, Any],
    player_input: str,
    config: dict[str, Any],
    next_canon_beat: dict[str, Any] | None = None,
    hard_constraints: str | None = None,
    soul: dict[str, Any] | None = None,
    attempt_plan: list[tuple[str, float, float]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    prompt, temperature, recent_self_dialogues = _build_actor_speak_prompt(
        cons,
        voice_ctx,
        scene,
        player_input,
        next_canon_beat=next_canon_beat,
        hard_constraints=hard_constraints,
        soul=soul,
    )
    attempts = attempt_plan or [
        ("first", _ACTOR_SPEAK_PRIMARY_TIMEOUT, _ACTOR_SPEAK_RETRY_BACKOFF),
        ("retry", _ACTOR_SPEAK_RETRY_TIMEOUT, 0.0),
    ]
    errors: list[str] = []
    timeout_trace: list[float] = []
    backoff_trace: list[float] = []
    for idx, (label, timeout, backoff_s) in enumerate(attempts):
        timeout_trace.append(timeout)
        parsed, error = _call_actor_llm_once(prompt, config, temperature, timeout)
        if parsed and parsed.get("dialogue"):
            return parsed, {
                "cons": cons,
                "ok": True,
                "attempts": len(errors) + 1,
                "timeouts": timeout_trace,
                "backoffs": backoff_trace,
                "temperature": temperature,
                "recent_self_dialogues": recent_self_dialogues,
                "last_error": errors[-1] if errors else None,
                "resolved_after": label,
            }
        if error == "missing_config":
            return None, {
                "cons": cons,
                "ok": False,
                "attempts": len(errors) + 1,
                "timeouts": timeout_trace,
                "backoffs": backoff_trace,
                "temperature": temperature,
                "recent_self_dialogues": recent_self_dialogues,
                "last_error": error,
            }
        errors.append(f"{error}_{label}")
        if idx < len(attempts) - 1 and llm_transport.is_retryable_error(error) and backoff_s > 0:
            backoff_trace.append(backoff_s)
            time.sleep(backoff_s)
    return None, {
        "cons": cons,
        "ok": False,
        "attempts": len(attempts),
        "timeouts": timeout_trace,
        "backoffs": backoff_trace,
        "temperature": temperature,
        "recent_self_dialogues": recent_self_dialogues,
        "last_error": errors[-1] if errors else "empty_result_retry",
    }


def _actor_speak_llm(
    cons: str,
    voice_ctx: dict[str, Any],
    scene: dict[str, Any],
    player_input: str,
    config: dict[str, Any],
    next_canon_beat: dict[str, Any] | None = None,
    hard_constraints: str | None = None,
    soul: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    parsed, _debug = _actor_speak_llm_with_debug(
        cons,
        voice_ctx,
        scene,
        player_input,
        config,
        next_canon_beat=next_canon_beat,
        hard_constraints=hard_constraints,
        soul=soul,
    )
    return parsed


def _actor_speak_llm_concurrent(
    speakers_list: list[dict[str, Any]],
    voice_contexts: dict[str, dict[str, Any]],
    scene: dict[str, Any],
    player_input: str,
    config: dict[str, Any],
    next_canon_beat: dict[str, Any] | None = None,
    hard_constraints: dict[str, str] | None = None,
    soul_map: dict[str, dict[str, Any]] | None = None,
    include_debug: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
    results = []
    if not speakers_list:
        return (results, {"fallback_reason_by_cons": {}, "attempt_debug_by_cons": {}}) if include_debug else results
    soul_map = soul_map or {}
    started = time.monotonic()
    attempt_debug_by_cons: dict[str, dict[str, Any]] = {}
    fallback_reason_by_cons: dict[str, str] = {}
    max_workers = max(1, min(_ACTOR_SPEAK_MAX_WORKERS, len(speakers_list)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _actor_speak_llm_with_debug,
                sp["cons"],
                voice_contexts.get(sp["cons"], {}),
                scene,
                player_input,
                config,
                next_canon_beat,
                (hard_constraints or {}).get(sp["cons"]),
                soul_map.get(sp["cons"]),
            ): sp
            for sp in speakers_list
        }
        for sp in speakers_list:
            fut = [f for f, s in futures.items() if s == sp][0]
            try:
                got, debug = fut.result()
                attempt_debug_by_cons[sp["cons"]] = debug
                if got and got.get("dialogue"):
                    dialogue = got["dialogue"]
                    lang = got.get("lang") or "zh"
                    if sp["cons"] == "C.kakashi.WMAIN":
                        dialogue = strip_kana(dialogue)
                    else:
                        lang = "zh"
                    results.append({
                        "cons": sp["cons"],
                        "stage": got.get("stage", ""),
                        "inner": got.get("inner", ""),
                        "dialogue": dialogue,
                        "lang": lang,
                        "action": got.get("action")
                    })
                else:
                    fallback_reason_by_cons[sp["cons"]] = debug.get("last_error") or "empty_result_retry"
            except Exception:
                fallback_reason_by_cons[sp["cons"]] = "unexpected_error_future"
                attempt_debug_by_cons[sp["cons"]] = {"cons": sp["cons"], "ok": False, "last_error": "unexpected_error_future"}

    success_cons = {item["cons"] for item in results}
    for sp in speakers_list:
        cons = sp["cons"]
        if cons in success_cons:
            continue
        remaining = _ACTOR_SPEAK_TOTAL_BUDGET - (time.monotonic() - started)
        if remaining <= 0:
            fallback_reason_by_cons[cons] = "budget_exhausted_partial_fallback"
            attempt_debug_by_cons.setdefault(cons, {})["final_reason"] = "budget_exhausted_partial_fallback"
            continue
        retry_timeout = max(1.0, min(float(_ACTOR_SPEAK_RETRY_TIMEOUT), float(remaining)))
        got, retry_debug = _actor_speak_llm_with_debug(
            cons,
            voice_contexts.get(cons, {}),
            scene,
            player_input,
            config,
            next_canon_beat=next_canon_beat,
            hard_constraints=(hard_constraints or {}).get(cons),
            soul=soul_map.get(cons),
            attempt_plan=[("single_retry", retry_timeout, 0.0)],
        )
        attempt_debug_by_cons[cons] = {
            **attempt_debug_by_cons.get(cons, {}),
            "single_retry": retry_debug,
        }
        if got and got.get("dialogue"):
            dialogue = got["dialogue"]
            lang = got.get("lang") or "zh"
            if cons == "C.kakashi.WMAIN":
                dialogue = strip_kana(dialogue)
            else:
                lang = "zh"
            results.append({
                "cons": cons,
                "stage": got.get("stage", ""),
                "inner": got.get("inner", ""),
                "dialogue": dialogue,
                "lang": lang,
                "action": got.get("action"),
            })
            fallback_reason_by_cons.pop(cons, None)
        else:
            reason = retry_debug.get("last_error") or fallback_reason_by_cons.get(cons) or "empty_result_single_retry"
            fallback_reason_by_cons[cons] = f"{reason}_retry_fail_fallback"
            attempt_debug_by_cons[cons]["final_reason"] = fallback_reason_by_cons[cons]
    if include_debug:
        return results, {
            "fallback_reason_by_cons": fallback_reason_by_cons,
            "attempt_debug_by_cons": attempt_debug_by_cons,
            "budget_seconds": _ACTOR_SPEAK_TOTAL_BUDGET,
        }
    return results


def _director_llm(prompt: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Call an OpenAI-compatible chat endpoint. Return parsed JSON or None."""
    cfg = config or {}
    api_key = (cfg.get("api_key") or "").strip()
    api_url = (cfg.get("api_url") or "").strip()
    model = (cfg.get("model") or "").strip()
    if not api_key or not api_url or not model:
        return None

    body = {
        "model": model,
        "temperature": 0.6,
        "messages": [
            {
                "role": "system",
                "content": "你是《存在的意义：因果之外》的场景导演。只输出符合协议的 JSON，不要输出解释。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    body.update(llm_transport.chat_request_options(cfg))
    req = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    choices = payload.get("choices") or []
    if not choices:
        return None
    content = choices[0].get("message", {}).get("content", "")
    return _extract_json_object(content)


def _check_actor_initiative_transition(actor_results: list[dict[str, Any]], contexts: dict[str, dict[str, Any]], gm_pacing: dict[str, Any]):
    for item in actor_results:
        if item.get("action") == "transition":
            cons = item.get("cons")
            ctx = contexts.get(cons) or {}
            agenda = ctx.get("agent_state", {}).get("short_term_agenda", {})
            next_scene = agenda.get("next_scene")
            if next_scene and isinstance(next_scene, dict) and next_scene.get("place"):
                gm_pacing["should_transition"] = True
                gm_pacing["target"] = next_scene
                break


def _unwrap_actor_speak_result(
    payload: list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(payload, tuple) and len(payload) == 2:
        return payload[0], payload[1]
    return payload, {}


def handle(req_data: dict[str, Any], db_path: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    op = req_data.get("op", "start_scene")
    scene_id = req_data.get("scene_id") or _DEFAULT_SCENE["scene_id"]
    place = req_data.get("place") or _DEFAULT_SCENE["place"]
    ch_anchor = int(req_data.get("ch_anchor") or _DEFAULT_SCENE["ch_anchor"])
    run_no = int(req_data.get("run_no") or 1)

    from scene_state import SceneState
    state = SceneState.load(run_no, scene_id)
    print(f"DEBUG_LOAD: op={op}, run_no={run_no}, scene_id={scene_id}, canon_beat_index={state.canon_beat_index}", flush=True)

    if op == "reset_scene":
        reset_scene = _scene_def(scene_id, place, ch_anchor)
        state.canon_beat_index = 0
        state.deviation_count = 0
        state.scene_ended = False
        state.location = reset_scene["location"]
        state.time_of_day = reset_scene["time_of_day"]
        state.present = reset_scene["present_characters"]
        state.ch_anchor = int(reset_scene["ch_anchor"])
        _reset_introduced_for_scene(state, reset_scene)
        # Prevent state pollution: if resetting the opening scene, delete all other scene states for this run
        if scene_id == "OPENING_TIANANMEN_001":
            from pathlib import Path
            states_dir = Path(_HERE) / "states"
            if states_dir.exists():
                for p in states_dir.glob(f"state_{run_no}_*.json"):
                    if p.name != f"state_{run_no}_{scene_id}.json":
                        try:
                            p.unlink()
                        except Exception:
                            pass
        state.save()
        try:
            append_scene_log(_SCENE_LOG_PATH, {
                "run_no": run_no,
                "scene_id": scene_id,
                "location": reset_scene["location"],
                "speaker": "",
                "role": "__delete_scene__",
                "content": "",
            })
        except Exception:
            pass
        return {"status": "ok", "scene_id": scene_id, "run_no": run_no}

    elif op == "new_run":
        from pathlib import Path
        states_dir = Path(_HERE) / "states"
        max_run = 0
        if states_dir.exists():
            for p in states_dir.glob("state_*.json"):
                m = re.match(r"state_(\d+)_(.*)\.json", p.name)
                if m:
                    max_run = max(max_run, int(m.group(1)))
        new_run_no = max(run_no + 1, max_run + 1)
        new_state = SceneState(new_run_no, "OPENING_TIANANMEN_001")
        new_state.location = "天安门升旗广场"
        new_state.ch_anchor = 8
        new_state.save()
        return {"status": "ok", "run_no": new_run_no, "scene_id": "OPENING_TIANANMEN_001"}

    if not state.location:
        scene_def = _scene_def(scene_id, place, ch_anchor)
        state.location = scene_def["location"]
        state.time_of_day = scene_def["time_of_day"]
        state.present = scene_def["present_characters"]
        state.ch_anchor = ch_anchor
        if state.canon_beat_index == 0:
            _reset_introduced_for_scene(state, scene_def)
        state.save()
    else:
        place = state.location
        ch_anchor = state.ch_anchor

    recent_log = load_scene_log(_SCENE_LOG_PATH, run_no, scene_id=None, limit=30)

    scene_def = _scene_def(scene_id, place, ch_anchor)
    if state.present:
        scene_def["present_characters"] = state.present
    scene = build_scene_context(scene_id, scene_def, recent_log)
    scene["runtime"]["run_no"] = run_no

    # Merge committed facts from SceneState into build_scene_context's accumulated list
    for item in state.committed:
        if item not in scene["committed"]:
            scene["committed"].append(item)

    contexts = {
        item["cons"]: build_participant_context(
            item["cons"],
            scene,
            db_path,
            relationship_stage="stranger",
            voice_stage="trusted",
            schedules_path=_SCHEDULES_PATH,
        )
        for item in scene.get("present_characters", [])
        if item.get("cons")
    }

    player_input = None
    speakers = []
    fallback_rendered = None
    delta_events = []
    contract_result = None
    actor_llm_debug: dict[str, Any] = {}
    scene_over_flag = False  # 终结闸：走散拍播完后置 True
    auto_transition_after_canon = False
    released_exhausted_proceed_to_live = False
    turn_source = "local_fallback"

    if op == "start_scene":
        contract_result = adjudicate_scene_contract(scene, "")
        _pre_exit = resolve_active_exit_state(state, contract_result or {})
        _exit_state_for_beats: str | None = _pre_exit["id"] if _pre_exit else None
        if state.canon_beat_index == 0:
            # First entry: Autoplay intro and consecutive beats
            messages = []
            if scene.get("current_beat"):
                messages.append({
                    "role": "director",
                    "name": "主持人",
                    "content": scene.get("current_beat"),
                })

            # Autoplay beats
            flow_msgs = _play_canon_beats(scene, state, exit_state=_exit_state_for_beats)
            messages.extend(flow_msgs)
            if flow_msgs:
                turn_source = "canon"
            
            fallback_rendered = {
                "messages": messages,
                "needs_player_response": True,
                "state_updates": {},
            }
        else:
            speakers = choose_speakers(scene, None, max_speakers=2)
            fallback_rendered = _render_turn(scene, speakers, None, state.introduced, state.canon_beat_index)

    elif op == "player_say":
        player_input = req_data.get("player_input", "")
        # 终结闸：场景已走散/终幕，engine 不再产出，前端应据 scene_over 收尾
        if getattr(state, "scene_ended", False):
            return {
                "build_version": _get_git_short_sha(),
                "director_mode": "scene_ended",
                "surface": _surface(scene),
                "scene": scene,
                "messages": [],
                "persisted": [],
                "delta_events": [],
                "runtime_props_recorded": [],
                "contract_result": None,
                "needs_player_response": False,
                "scene_over": True,
                "turn_source": "scene_ended",
            }
        force_fallback_local = False
        # name unlock detection on player input
        _check_name_unlock(player_input, state)
        
        contract_result = adjudicate_scene_contract(scene, player_input)
        _pre_exit = resolve_active_exit_state(state, contract_result or {})
        _exit_state_for_beats: str | None = _pre_exit["id"] if _pre_exit else None
        parsed = parse_player_input_modalities(player_input)
        if parsed["thought"] != "" and parsed["speech"] == "":
            visible_to = []
        else:
            # player 不是 NPC，不加入 learned_by（谁"学到"这轮对话内容）
            visible_to = [item["cons"] for item in scene.get("present_characters", [])
                          if item.get("cons") and item["cons"] != "C.player.WMAIN"]

        player_record = append_scene_log(_SCENE_LOG_PATH, {
            "run_no": run_no,
            "scene_id": scene_id,
            "location": scene["location"],
            "speaker": "你",
            "role": "player",
            "content": player_input,
            "visible_to": visible_to,
            "created_runtime_props": [],
        })
        delta_events = scene_log_to_delta_events([player_record])
        append_delta_events(_DELTA_LEDGER_PATH, delta_events)
        scene["recent_log"] = load_scene_log(_SCENE_LOG_PATH, run_no, scene_id=None, limit=30)
        
        recent_script_lines = []
        for item in scene.get("recent_log", [])[-8:]:
            spk = item.get("speaker", "主持人")
            cnt = item.get("content", "")
            recent_script_lines.append(f"- {spk}: {cnt}")
        recent_script = "\n".join(recent_script_lines)

        dialogue_flow = scene.get("dialogue_flow", [])
        next_beat_index = state.canon_beat_index
        next_beat = dialogue_flow[next_beat_index] if next_beat_index < len(dialogue_flow) else None

        turn_type = classify_player_turn(player_input, state)
        original_turn_type = turn_type  # 保存原始分类，避免 ack 误触
        # 即兴档位：locked=零即兴强制推进；anchored=带正典约束卡即兴（默认）；free=完全自由
        improv_mode = (next_beat or {}).get("improv", "anchored")
        cond_res = None
        if next_beat and turn_type != "leave":
            condition_nl = next_beat.get("condition")
            path_id = next_beat.get("path_id") if next_beat else None
            if next_beat.get("beat_type") == "player_choice" and path_id in ("B1_dog", "choiceA_brace"):
                cond_map = {
                    "B1_dog": (
                        "玩家的话或动作体现出示警、提醒、让车内角色注意前方异常，"
                        "或主动指出路面/狗/危险源。"
                    ),
                    "choiceA_brace": (
                        "玩家的话或动作体现出扑向、护住、够向卡卡西或司机席，"
                        "或在撞击瞬间做出明确自我保护与保护他人的动作。"
                        "单纯抢方向盘、换驾驶、催人上车不算命中。"
                    ),
                }
                condition_nl = condition_nl or cond_map.get(path_id)
                is_satisfied = evaluate_condition(condition_nl, recent_script, player_input, config, path_id=path_id)
                cond_res = is_satisfied
                if is_satisfied:
                    turn_type = "proceed"
                else:
                    turn_type = "deviate"
            elif next_beat.get("beat_type") == "player_choice":
                # player_choice 拍是明确给玩家动作/发言的入口：
                # 除了显式 leave/refuse，都应视为有效选择并推进。
                if turn_type not in ("refuse", "leave"):
                    turn_type = "proceed"
            elif improv_mode == "locked":
                # locked 段：非拒绝/离场输入一律视为推进，不触发即兴
                if turn_type not in ("refuse", "leave"):
                    turn_type = "proceed"
            elif not condition_nl:
                # ── G2：有 path_id 的 player_choice beat 无 condition → 语义评估 ──
                if path_id in ("B1_dog", "choiceA_brace"):
                    # 触发语义 condition（见执行计划已裁定定义）
                    cond_map = {
                        "B1_dog": (
                            "玩家的话或动作体现出示警、提醒、让车内角色注意前方异常，"
                            "或主动指出路面/狗/危险源。"
                        ),
                        "choiceA_brace": (
                            "玩家的话或动作体现出扑向、护住、够向卡卡西或司机席，"
                            "或在撞击瞬间做出明确自我保护与保护他人的动作。"
                            "单纯抢方向盘、换驾驶、催人上车不算命中。"
                        ),
                    }
                    condition_nl = cond_map.get(path_id)
                    if condition_nl:
                        is_satisfied = evaluate_condition(condition_nl, recent_script, player_input, config, path_id=path_id)
                        cond_res = is_satisfied
                        if is_satisfied:
                            turn_type = "proceed"
                        else:
                            turn_type = "deviate"
                # else: anchored + 无 condition + 无特殊 path_id：保持 classify_player_turn 原始判定
            else:
                is_satisfied = evaluate_condition(condition_nl, recent_script, player_input, config)
                cond_res = is_satisfied
                if is_satisfied:
                    turn_type = "proceed"
                else:
                    if _NEG_AGREE_RE.search(player_input or ""):
                        turn_type = "refuse"
                    else:
                        turn_type = "deviate"
        print(f"DEBUG_TURN: next_beat_index={next_beat_index}, original_turn_type={original_turn_type}, turn_type={turn_type}, cond_res={cond_res}", flush=True)

        _norm_in = re.sub(r"[^\w一-龥]", "", _player_visible_text(player_input) or "")
        if _norm_in and _norm_in == getattr(state, "last_player_input", ""):
            state.repeat_count = getattr(state, "repeat_count", 0) + 1
        else:
            state.repeat_count = 0
        state.last_player_input = _norm_in

        if not hasattr(state, "deviation_count"):
            state.deviation_count = 0

        if next_beat is None and turn_type != "leave":
            state.deviation_count = 0; state.save()
            fallback_rendered = {"messages": [], "needs_player_response": True, "state_updates": {}}
            force_fallback_local = False
            released_exhausted_proceed_to_live = True
            speakers = choose_speakers(scene, player_input, max_speakers=2)
            if not speakers:
                present_chars = scene.get("present_characters", [])
                valid_chars = [item for item in present_chars if item.get("cons") and not item["cons"].startswith("C.player")]
                if valid_chars:
                    speakers = [{"cons": valid_chars[0]["cons"]}]

        elif turn_type == "leave":
            state.deviation_count = 0; state.save()
            speakers = choose_speakers(scene, player_input, max_speakers=2)
            fallback_rendered = _render_turn(scene, speakers, player_input, state.introduced, state.canon_beat_index + getattr(state, "repeat_count", 0))

        elif turn_type == "proceed":
            state.deviation_count = 0; state.save()
            messages = []
            thread_ack = _player_thread_ack_line(scene, player_input, state)
            if thread_ack:
                messages.append(thread_ack)
            elif not is_idle_input(player_input) and original_turn_type == "proceed":  # ack 仅对真正同意的输入触发
                ack = _proceed_ack_line(scene, player_input, state)
                if ack: messages.append(ack)
            beat_before = next_beat  # 记录即将播的拍，用于 scene_end 检测
            awarded_paths = register_branch_progress(state, contract_result or {}, _beat_path_ids(beat_before))
            _post_exit = resolve_active_exit_state(state, contract_result or {})
            _award_crash_intervention_memory(scene, state, _post_exit)
            _exit_state_for_beats = _post_exit["id"] if _post_exit else _exit_state_for_beats
            flow_msgs = _play_canon_beats(scene, state, limit=1, exit_state=_exit_state_for_beats)
            messages.extend(flow_msgs)
            state_updates = {}
            if awarded_paths:
                state_updates["branch_paths_triggered"] = awarded_paths
            fallback_rendered = {"messages": messages, "needs_player_response": True, "state_updates": state_updates}
            if flow_msgs:
                turn_source = "canon"
                force_fallback_local = True                      # canon is deterministic while it still has beats.
                speakers = []
            else:
                # Canon is exhausted but the scene is not ended; let live actors improvise
                # instead of cycling canned fallback lines on repeated proceed inputs.
                force_fallback_local = False
                released_exhausted_proceed_to_live = True
                speakers = choose_speakers(scene, player_input, max_speakers=2)
                if not speakers:
                    present_chars = scene.get("present_characters", [])
                    valid_chars = [item for item in present_chars if item.get("cons") and not item["cons"].startswith("C.player")]
                    if valid_chars:
                        speakers = [{"cons": valid_chars[0]["cons"]}]
            # scene_end 终结闸：走散/终幕拍播完即结束场景，不再即兴
            if beat_before and beat_before.get("scene_end"):
                scene_over_flag = True
                state.scene_ended = True
                state.save()
            if beat_before and beat_before.get("auto_transition") and state.canon_beat_index >= len(scene.get("dialogue_flow", [])):
                auto_transition_after_canon = True

        else:  # turn_type in ("deviate", "refuse")
            state.deviation_count += 1
            delta = state.deviation_count
            if getattr(state, "repeat_count", 0) >= 2:   # 反空转：连发3次同样的话→强收敛推进
                delta = 3
            state.save()
            if delta >= 2:                                       # FLOOR：硬收敛，连续脱稿第2次即触发
                messages = []
                bridge = _bridge_line(scene, player_input, turn_type, state)   # INV-17b 承接玩家话头
                if bridge: messages.append(bridge)
                
                limit = 1
                dialogue_flow = scene.get("dialogue_flow", [])
                if state.canon_beat_index < len(dialogue_flow):
                    next_beat = dialogue_flow[state.canon_beat_index]
                    speaker_cons = _speaker_to_cons(next_beat["speaker"], scene.get("present_characters", []))
                    if not speaker_cons:
                        limit = 2
                
                floor_beat = dialogue_flow[state.canon_beat_index] if state.canon_beat_index < len(dialogue_flow) else None
                _floor_exit = resolve_active_exit_state(state, contract_result or {})
                _exit_state_for_beats = _floor_exit["id"] if _floor_exit else _exit_state_for_beats
                flow_msgs = _play_canon_beats(scene, state, limit=limit, exit_state=_exit_state_for_beats)
                messages.extend(flow_msgs or _fallback_npc_turn(scene, player_input, state))
                state.deviation_count = 0; state.save()
                if floor_beat and floor_beat.get("scene_end"):
                    scene_over_flag = True
                    state.scene_ended = True
                    state.save()
                if floor_beat and floor_beat.get("auto_transition") and state.canon_beat_index >= len(scene.get("dialogue_flow", [])):
                    auto_transition_after_canon = True
                fallback_rendered = {"messages": messages, "needs_player_response": True, "state_updates": {}}
                turn_source = "canon" if flow_msgs else "local_fallback"
                force_fallback_local = True
                speakers = []
            else:                                                # δ=1 自由反应；δ=2 反应+软靠 agenda
                nudge = (delta == 2)
                speakers = choose_speakers(scene, player_input, max_speakers=2)
                if not speakers:
                    present_chars = scene.get("present_characters", [])
                    if present_chars:
                        valid_chars = [item for item in present_chars if item.get("cons") and not item["cons"].startswith("C.player")]
                        if valid_chars:
                            speakers = [{"cons": valid_chars[0]["cons"]}]
                messages = _fallback_npc_turn(scene, player_input, state, nudge=nudge, refuse=(turn_type == "refuse"))
                fallback_rendered = {"messages": messages, "needs_player_response": True, "state_updates": {}}
    else:
        return {"error": f"未知 scene op: {op}"}

    group_prompt = compose_group_prompt(scene, contexts, advance_command_filter(player_input), speakers)
    agent_states = {cons: ctx.get("agent_state", {}) for cons, ctx in contexts.items()}
    runtime_scene_state = dict(scene)
    runtime_scene_state["canon_beat_index"] = state.canon_beat_index
    runtime_scene_state["runtime"] = {"run_no": run_no}
    gm_pacing = evaluate_gm_pacing(runtime_scene_state, player_input, scene.get("recent_log", []), agent_states, _load_map())
    bidding = bid_turn_taking(scene, player_input, agent_states, max_speakers=2)

    if auto_transition_after_canon and not gm_pacing.get("should_transition"):
        import scene_runtime
        target = scene_runtime._legal_transition_target(scene, _load_map())
        if target and not _is_same_scene_target(scene, scene_id, target):
            gm_pacing["should_transition"] = True
            gm_pacing["target"] = target
            gm_pacing["reason"] = "auto_transition_after_canon"

    if scene_over_flag and not gm_pacing.get("target"):
        import scene_runtime
        target = scene_runtime._legal_transition_target(scene, _load_map())
        if target and not _is_same_scene_target(scene, scene_id, target):
            gm_pacing["target"] = target

    active_exit_state = resolve_active_exit_state(state, contract_result or {})
    if active_exit_state:
        contract_result = dict(contract_result or {})
        contract_result["active_exit_state"] = active_exit_state["id"]
        contract_result["branch_gate"] = active_exit_state.get("branch_gate")
        contract_result["activated_paths"] = active_exit_state.get("activated_paths", [])
        contract_result["combine_threshold"] = active_exit_state.get("threshold")

    # 正典约束卡：当前未播的下一拍＝即兴锚点；人格铁律＝硬约束
    _cur_df = scene.get("dialogue_flow", [])
    _anchor_beat = _cur_df[state.canon_beat_index] if state.canon_beat_index < len(_cur_df) else None
    _hard_cons = _load_persona_constraints([item.get("cons") for item in scene.get("present_characters", [])])
    _present_cons = [item.get("cons") for item in scene.get("present_characters", []) if item.get("cons") and not item["cons"].startswith("C.player")]
    _turn_type = turn_type if 'turn_type' in locals() else classify_player_turn(player_input, state)
    if player_input:
        update_emotional_state(state, _present_cons, _turn_type, player_input)
    _player_lang_ja = detect_player_japanese(player_input)
    _soul_map = {
        c: {
            "mood": _seed_mood(state, c),
            "trust": _seed_trust(state, c),
            "last_spark": (state.last_spark or {}).get(c) if state else None,
            "player_lang_ja": _player_lang_ja,
            "repeat_count": getattr(state, "repeat_count", 0),
        }
        for c in _present_cons
    }
    # locked 段（高张力/语言镜像）禁止 gm_pacing 软转场旁白漏入
    if _anchor_beat and _anchor_beat.get("improv") == "locked":
        gm_pacing["should_transition"] = False
        gm_pacing["target"] = None

    slow_path = should_route_slow_path(req_data, scene, scene.get("recent_log", []), contract_result, gm_pacing)
    if released_exhausted_proceed_to_live:
        slow_path = False

    director_mode = "deterministic_fallback"
    contract_errors: list[str] = []
    
    # Auto bypass LLM on start_scene initial play or idle inputs
    force_fallback = bool(req_data.get("force_fallback"))
    if op == "start_scene" and state.canon_beat_index <= len(scene.get("dialogue_flow", [])) and len(fallback_rendered.get("messages", [])) > 0:
        force_fallback = True
    elif op == "player_say" and force_fallback_local:
        force_fallback = True

    if force_fallback:
        rendered = fallback_rendered
        if turn_source != "canon":
            turn_source = "local_fallback"
    elif slow_path:
        llm_output = _director_llm(group_prompt["prompt"], config)
        if llm_output is not None:
            llm_output = _normalize_director_output(llm_output, scene)
            ok, errors = validate_director_output(llm_output, scene, contexts)
            if ok:
                rendered = _messages_from_director_output(llm_output, scene, state.introduced)
                director_mode = "llm_contract_pass"
                turn_source = "llm"
                
                api_key = (config or {}).get("api_key") if config else None
                if api_key:
                    voice_contexts = group_prompt.get("speaker_voice_contexts", {})
                    narration = llm_output.get("narration") or ""
                    temp_scene = dict(scene)
                    if narration:
                        temp_scene["recent_log"] = list(temp_scene.get("recent_log") or []) + [{
                            "role": "director",
                            "speaker": "主持人",
                            "content": narration,
                        }]
                    actor_results, actor_llm_debug = _unwrap_actor_speak_result(_actor_speak_llm_concurrent(
                        bidding["speakers"], voice_contexts, temp_scene,
                        advance_command_filter(player_input), config or {},
                        next_canon_beat=_anchor_beat, hard_constraints=_hard_cons, soul_map=_soul_map,
                        include_debug=True,
                    ))
                    _check_actor_initiative_transition(actor_results, contexts, gm_pacing)
                    for item in actor_results:
                        rendered["messages"].append({
                            "role": "npc",
                            "cons": item.get("cons"),
                            "name": _speaker_name(scene, item.get("cons"), state.introduced),
                            "stage": item.get("stage", ""),
                            "content": item.get("dialogue", ""), "inner": item.get("inner", ""), "lang": item.get("lang", "zh"),
                        })
            else:
                rendered = fallback_rendered
                director_mode = "llm_contract_fail_fallback"
                turn_source = "local_fallback"
                contract_errors = errors
        else:
            rendered = fallback_rendered
            turn_source = "local_fallback"
    else:
        api_key = (config or {}).get("api_key") if config else None
        if api_key:
            voice_contexts = group_prompt.get("speaker_voice_contexts", {})
            actor_results, actor_llm_debug = _unwrap_actor_speak_result(_actor_speak_llm_concurrent(
                bidding["speakers"], voice_contexts, scene,
                advance_command_filter(player_input), config or {},
                next_canon_beat=_anchor_beat, hard_constraints=_hard_cons, soul_map=_soul_map,
                include_debug=True,
            ))
            _check_actor_initiative_transition(actor_results, contexts, gm_pacing)
            if actor_results:
                messages = []
                for item in actor_results:
                    messages.append({
                        "role": "npc",
                        "cons": item.get("cons"),
                        "name": _speaker_name(scene, item.get("cons"), state.introduced),
                        "stage": item.get("stage", ""),
                        "content": item.get("dialogue", ""), "inner": item.get("inner", ""), "lang": item.get("lang", "zh"),
                    })
                rendered = {
                    "messages": messages,
                    "needs_player_response": True,
                    "state_updates": {},
                }
                director_mode = "fastpath_actor_llm"
                turn_source = "actor_llm"
            else:
                if not bidding["speakers"]:
                    rendered = {
                        "messages": [],
                        "needs_player_response": True,
                        "state_updates": {},
                    }
                    director_mode = "fastpath_silence"
                    turn_source = "actor_llm"
                else:
                    rendered = fallback_rendered
                    director_mode = "fastpath_actor_fail_fallback"
                    turn_source = "local_fallback"
        else:
            rendered = fallback_rendered
            director_mode = "fastpath_deterministic_fallback"
            turn_source = "local_fallback"

    # Loop R1: Ensure at least one NPC voice if not transitioning
    # scene_over：终幕拍（走散）后不再补位生成 NPC 台词
    if rendered and rendered.get("messages") is not None and not gm_pacing.get("should_transition") and not scene_over_flag:
        has_npc_voice = any(msg.get("role") == "npc" and msg.get("content") for msg in rendered["messages"])
        if not has_npc_voice:
            fallback_speakers = bidding.get("speakers") if (bidding and bidding.get("speakers")) else speakers
            if not fallback_speakers:
                present_chars = scene.get("present_characters", [])
                if present_chars:
                    valid_chars = [item for item in present_chars if item.get("cons") and not item["cons"].startswith("C.player")]
                    if valid_chars:
                        fallback_speakers = [{"cons": valid_chars[0]["cons"]}]
            
            if fallback_speakers:
                api_key = (config or {}).get("api_key") if config else None
                if api_key:
                    voice_contexts = group_prompt.get("speaker_voice_contexts", {})
                    temp_scene = dict(scene)
                    narrations = [m.get("content") for m in rendered["messages"] if m.get("role") == "director" and m.get("content")]
                    if narrations:
                        temp_scene["recent_log"] = list(temp_scene.get("recent_log") or [])
                        for narr in narrations:
                            temp_scene["recent_log"].append({
                                "role": "director",
                                "speaker": "主持人",
                                "content": narr,
                            })
                    actor_results, actor_llm_debug = _unwrap_actor_speak_result(_actor_speak_llm_concurrent(
                        fallback_speakers, voice_contexts, temp_scene, player_input or "", config or {},
                        next_canon_beat=_anchor_beat, hard_constraints=_hard_cons, soul_map=_soul_map,
                        include_debug=True,
                    ))
                    _check_actor_initiative_transition(actor_results, contexts, gm_pacing)
                    for item in actor_results:
                        rendered["messages"].append({
                            "role": "npc",
                            "cons": item.get("cons"),
                            "name": _speaker_name(scene, item.get("cons"), state.introduced),
                            "stage": item.get("stage", ""),
                            "content": item.get("dialogue", ""), "inner": item.get("inner", ""), "lang": item.get("lang", "zh"),
                        })
                
                has_npc_voice_now = any(msg.get("role") == "npc" and msg.get("content") for msg in rendered["messages"])
                if not has_npc_voice_now:
                    fallback_msgs = _fallback_npc_turn(
                        scene,
                        player_input or "",
                        state,
                        refuse=(turn_type == "refuse" if 'turn_type' in locals() else False)
                    )
                    rendered["messages"].extend(fallback_msgs)
                    if turn_source != "canon":
                        turn_source = "local_fallback"

    _repair_repeated_npc_lines(rendered, scene, state, player_input)

    # B10: Check duplicate and progress
    recent_log_for_dup = scene.get("recent_log") or []
    committed_list = scene.get("committed") or []
    had_messages_before_filter = bool(rendered.get("messages"))
    # Load cross-scene run logs for deduplication
    run_logs = load_scene_log(_SCENE_LOG_PATH, run_no, scene_id=None, limit=500)
    filtered_msgs, force_transition = check_duplicate_and_progress(
        rendered["messages"], recent_log_for_dup, committed_list, run_logs=run_logs
    )
    rendered["messages"] = filtered_msgs
    canon_exhausted = state.canon_beat_index >= len(scene.get("dialogue_flow", []))
    if force_transition and canon_exhausted:
        gm_pacing["should_transition"] = True
        if not gm_pacing.get("target"):
            import scene_runtime
            target = scene_runtime._legal_transition_target(scene, _load_map())
            if target and not _is_same_scene_target(scene, scene_id, target):
                gm_pacing["target"] = target
        if gm_pacing.get("target") and not rendered["messages"]:
            rendered["messages"] = []
    if not rendered["messages"] and not gm_pacing.get("should_transition"):
        if had_messages_before_filter:
            # 强行推进下一拍正典，避免无限旁白空转 (INV-19)
            flow_msgs = _play_canon_beats(scene, state, limit=1, exit_state=_exit_state_for_beats)
            if flow_msgs:
                rendered["messages"] = flow_msgs
            else:
                present_chars = scene.get("present_characters", [])
                if present_chars:
                    temp_rendered = _render_turn(scene, [{"cons": present_chars[0]["cons"]}], player_input, state.introduced, state.canon_beat_index + getattr(state, "repeat_count", 0))
                    rendered["messages"] = temp_rendered["messages"]
                else:
                    rendered["messages"] = [{
                        "role": "director",
                        "name": "主持人",
                        "content": _hold_scene_narration(scene, player_input),
                    }]
        else:
            rendered["messages"] = [{
                "role": "director",
                "name": "主持人",
                "content": _hold_scene_narration(scene, player_input),
            }]

    # 1. Update state.committed from state_updates and save
    state_updates = rendered.get("state_updates") or {}
    new_committed = state_updates.get("committed")
    if new_committed:
        if isinstance(new_committed, list):
            for item in new_committed:
                if item not in state.committed:
                    state.committed.append(item)
        elif isinstance(new_committed, str) and new_committed:
            if new_committed not in state.committed:
                state.committed.append(new_committed)
        state.save()

    # 2. Update state transition
    if gm_pacing.get("should_transition") and not scene_over_flag:
        # Prevent "ghost turn-back" (鬼打墙) by filtering out already visited scenes from target
        curr_target = gm_pacing.get("target")
        if curr_target and isinstance(curr_target, dict):
            t_sid = curr_target.get("scene_id")
            if t_sid and t_sid != scene_id and _is_scene_visited(run_no, t_sid):
                gm_pacing["target"] = None

        if not gm_pacing.get("target"):
            import scene_runtime
            target = scene_runtime._legal_transition_target(scene, _load_map())
            if target:
                gm_pacing["target"] = target
        if _is_same_scene_target(scene, scene_id, gm_pacing.get("target")):
            gm_pacing["should_transition"] = False
            gm_pacing["target"] = None
            gm_pacing["narration"] = ""
        
        target = gm_pacing.get("target")
        if target:
            # Mark the old scene state as ended and save it under the old scene ID
            state.scene_ended = True
            state.canon_beat_index = len(scene.get("dialogue_flow", []))
            state.save()
            
            new_place = target.get("place")
            new_scene_id = target.get("scene_id")
            target_ch_anchor = int(target.get("ch_anchor") or ch_anchor)
            
            state.location = new_place
            state.scene_id = new_scene_id
            
            new_scene_def = _scene_def(new_scene_id, new_place, target_ch_anchor)
            state.present = new_scene_def.get("present_characters") or []
            state.ch_anchor = target_ch_anchor
            state.save()
            
            new_state = SceneState(run_no, new_scene_id)
            new_state.location = new_place
            new_state.time_of_day = new_scene_def.get("time_of_day", "")
            new_state.committed = list(state.committed)
            new_state.branch_progress = dict(getattr(state, "branch_progress", {}) or {})
            new_state.present = list(state.present)
            new_state.ch_anchor = target_ch_anchor
            new_state.canon_beat_index = 0
            _reset_introduced_for_scene(new_state, new_scene_def)
            merged_intro = SceneState.load_all_introduced(run_no)
            for k, v in merged_intro.items():
                if v:
                    new_state.introduced[k] = True
            new_state.save()
            
            scene["location"] = new_place
            scene["scene_id"] = new_scene_id
            scene["ch_anchor"] = target_ch_anchor
            scene_id = new_scene_id

        target = gm_pacing.get("target")
        if target:
            gm_pacing["narration"] = _in_world_transition_narration(scene, target)
        elif not gm_pacing.get("narration"):
            gm_pacing["narration"] = _in_world_transition_narration(scene, gm_pacing.get("target"))

        if gm_pacing.get("narration"):
            rendered["messages"].append({
                "role": "director",
                "name": "主持人",
                "content": gm_pacing["narration"],
                "transition_target": gm_pacing.get("target"),
            })

    if gm_pacing.get("should_transition"):
        scene_over_flag = True

    # B12: strip scratch fields from message content/stage
    for msg in rendered["messages"]:
        if "content" in msg and isinstance(msg["content"], str):
            msg["content"] = strip_scratch(msg["content"])
        if "stage" in msg and isinstance(msg["stage"], str):
            msg["stage"] = strip_scratch(msg["stage"])

    # B19: anonymize names in visibility layer before saving/persisting
    for msg in rendered["messages"]:
        msg_introduced = msg.pop("_introduced_snapshot", None)
        if msg_introduced is None:
            msg_introduced = state.introduced
        if "name" in msg and msg["name"]:
            msg["name"] = anonymize_text(msg["name"], msg_introduced)
        if msg.get("role") in ("director", "overhear"):
            if "content" in msg and msg["content"]:
                msg["content"] = anonymize_text(msg["content"], msg_introduced)
            if "stage" in msg and msg["stage"]:
                msg["stage"] = anonymize_text(msg["stage"], msg_introduced)
    if gm_pacing.get("narration"):
        gm_pacing["narration"] = anonymize_text(gm_pacing["narration"], state.introduced)

    persisted = []
    state_updates = rendered.get("state_updates") or {}
    runtime_props = list(state_updates.get("created_runtime_props") or [])
    visible_to = [item["cons"] for item in scene.get("present_characters", [])
                  if item.get("cons") and item["cons"] != "C.player.WMAIN"]
    for msg in rendered["messages"]:
        msg_runtime_props = runtime_props if not persisted else []
        persisted.append(append_scene_log(_SCENE_LOG_PATH, {
            "run_no": run_no,
            "scene_id": scene_id,
            "location": scene["location"],
            "speaker": msg.get("name") or msg.get("speaker") or msg.get("cons") or "主持人",
            "cons": msg.get("cons"),
            "role": msg.get("role"),
            "content": msg.get("content", ""),
            "visible_to": visible_to,
            "created_runtime_props": msg_runtime_props,
        }))
    runtime_props_recorded = ingest_created_runtime_props(
        [row for row in persisted if row.get("created_runtime_props")],
        store=_RUNTIME_KNOWLEDGE_PATH,
    )
    return {
        "build_version": _get_git_short_sha(),
        "director_mode": director_mode,
        "surface": _surface(scene),
        "scene": scene,
        "messages": rendered["messages"],
        "persisted": persisted,
        "delta_events": delta_events,
        "runtime_props_recorded": runtime_props_recorded,
        "contract_result": contract_result,
        "needs_player_response": rendered["needs_player_response"],
        "scene_over": scene_over_flag if scene_over_flag else None,
        "turn_source": turn_source,
        "speaker_plan": speakers,
        "bidding": bidding,
        "gm_pacing": gm_pacing,
        "transition_target": gm_pacing.get("target") if (gm_pacing.get("should_transition") or scene_over_flag) else None,
        "prompt_debug": {
            "pipeline": "scene_runtime",
            "director_mode": director_mode,
            "turn_source": turn_source,
            "force_fallback": force_fallback,
            "contract_errors": contract_errors,
            "participants": group_prompt["participants"],
            "hidden_runtime": group_prompt["hidden_runtime"],
            "contract_result": contract_result,
            "speaker_voice_contexts": group_prompt.get("speaker_voice_contexts", {}),
            "agent_states": agent_states,
            "bidding": bidding,
            "actor_llm_debug": actor_llm_debug,
            "gm_pacing": gm_pacing,
            "prompt_preview": group_prompt["prompt"][:1200],
        },
    }
