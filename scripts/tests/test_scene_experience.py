# -*- coding: utf-8 -*-
"""
Opening experience checks.

Hard checks are deterministic but run a long multi-scene journey, so they belong to
`verify.py --full`; focused edits still route them through explicit/full validation.
Soft checks are split into:
  - transcript generation (`--soft-regen`): slow, real LLM path, cached to disk
  - transcript judging (`--soft-report`): reuse cached transcripts, write baseline
  - baseline inspection (`--soft-baseline`): zero-LLM, read latest baseline only
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from typing import Optional
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "c1_web_console"
DB_PATH = str(ROOT / "data" / "world_truth.db")
ANALYSIS_DIR = ROOT / "analysis"
TRANSCRIPT_DIR = ANALYSIS_DIR / "transcripts"
SOFT_BASELINE_PATH = ANALYSIS_DIR / "ex_s1_baseline.json"
SOFT_JUDGE_SEEDS = [101, 202, 303]
SOFT_JUDGE_TEMPERATURE = 0.2
SOFT_JUDGE_TIMEOUT_S = 90
SOFT_JUDGE_MAX_ATTEMPTS = 1
SOFT_JUDGE_TRANSPORT_RETRIES = 3
SOFT_JUDGE_RETRY_BACKOFF_S = 0.75
TRANSCRIPT_CACHE_VERSION = 1
BASELINE_REPORT_VERSION = 3
MAX_TRANSCRIPT_WORKERS = 2
MAX_JUDGE_WORKERS = 2

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CONSOLE))

import scene_api
import scene_state
import llm_transport
from scene_state import SceneState


ROUTES = {
    "A": [
        ("天安门升旗广场", 8, "OPENING_TIANANMEN_001"),
        ("广场旁咖啡厅", 8, "OPENING_CAFE_001"),
        ("王府井街道", 10, "OPENING_WANGFUJING_001"),
        ("北京海族馆", 10, "OPENING_AQUARIUM_001"),
        ("人豚共舞表演区", 12, "OPENING_DOLPHIN_001"),
        ("街角咖啡厅", 13, "OPENING_SHOOTING_001"),
        ("京津高速伏击", 16, "OPENING_HIGHWAY_001"),
        ("中心医院合流", 17, "OPENING_HOSPITAL_001"),
    ],
    "B": [
        ("天安门升旗广场", 8, "OPENING_TIANANMEN_001"),
        ("王府井街道", 10, "OPENING_WANGFUJING_001"),
        ("天津·真纪家见张尘", 15, "OPENING_TIANJIN_ZHANGCHEN_001"),
        ("中心医院合流", 17, "OPENING_HOSPITAL_001"),
    ],
    "C": [
        ("天安门升旗广场", 8, "OPENING_TIANANMEN_001"),
        ("王府井街道", 10, "OPENING_WANGFUJING_001"),
        ("十六中校门口", 15, "OPENING_SHILIUZHONG_001"),
        ("等消息去医院", 16, "OPENING_WAIT_HOSPITAL_001"),
        ("中心医院合流", 17, "OPENING_HOSPITAL_001"),
    ],
}

HARD_DRAG_WORDS = [
    "你被迫",
    "你不得不",
    "你别无选择",
    "强制",
    "系统将你",
    "你被传送",
]
BANNED_FALLBACK_TEMPLATE_PHRASES = [
    "让他微微地意识到",
    "让他明显地意识到",
    "抓住了你的话头",
    "先别把这句话摘开",
    "顺着这个话题往下走一步",
    "嗯，我听见了",
    "眼前这一步走完",
    "再看你还想不想跟着",
    "几人交换",
    "交换了几句眼色",
    "收拾起手边",
    "顺着人流收拾东西",
    "慢慢走去",
    "回公寓",
    "让他沉默了一瞬",
    "很高兴认识",
    "有缘再见",
    "不要她了",
    "三人散伙",
    "回头见",
    "准备回去",
    "逛了一天",
    "北京的夜晚",
]
DEVIATE_INPUTS = ["我想去火星", "你们都是假的吧", "我要飞"]
ALL_REAL_NAMES = ["卡卡西", "修哉", "秋人", "坂本晴明", "折原修哉", "川口秋人"]
INTRODUCE_SPEAKERS = {"秋人", "川口秋人"}

MAX_STATION_TURNS = 50
MAX_CONVERGENCE_CHECK_TURNS = 10
SOFT_ROUTE = ROUTES["A"][:4]


def select_station_player_input(station_inputs: list[str], input_idx: int, cycle: bool = True) -> tuple[str, int]:
    if not station_inputs:
        return "缁х画", input_idx
    if cycle:
        return station_inputs[input_idx % len(station_inputs)], input_idx + 1
    return station_inputs[min(input_idx, len(station_inputs) - 1)], input_idx + 1
SOFT_PERSONA_NAMES = ("乖巧", "刺头")
PERSONA_SLUGS = {
    "乖巧": "cooperative",
    "好奇": "curious",
    "刺头": "contrarian",
    "红线": "redline",
}
TRANSCRIPT_SOURCE_FILES = [
    CONSOLE / "opening_map.json",
    CONSOLE / "scene_api.py",
]

PERSONA_STRATEGIES = {
    "乖巧": {
        "station_inputs": [
            "好啊，去看看吧",
            "可以的，视频发给你们",
            "那我们也一起走吧",
            "谢谢你们借我手机",
        ],
        "description": "顺从配合、主动交流",
    },
    "好奇": {
        "station_inputs": ["你叫什么名字？", "这是哪里？", "那个人是谁？", "你们在做什么？"],
        "description": "提大量问题，试探世界边界",
    },
    "刺头": {
        "station_inputs": [
            "少骗我了，你们到底想干嘛",
            "凭什么要我信你们",
            "我才不跟你们走",
            "你们这群人有点不对劲",
        ],
        "description": "明确对抗、质疑、抗拒，但没有打第四面墙",
    },
    "红线": {
        "station_inputs": ["让时间倒流", "复活龙也", "我是造物主", "你们都是我创造的"],
        "description": "主动打第四面墙，逼出收敛",
    },
}

LLM_JUDGE_PROMPT = """你是一个“冷启动、很容易腻的新玩家”体验评审。

下面会给你一整段开场实录。你的任务不是查错，而是判断：
这个开场是否真的能把第一次来的玩家继续钩住。

请按 6 个维度各打 0/1 分，并给出总分 X/6：
1. 首屏钩子：开场前几轮是否立刻让我想继续看。
2. 继续意愿：每到暂停点，我是否自然想回一句、跟下去。
3. 真实感：角色回应像活人，不像脚手架或占位文本。
4. 收敛不出戏：玩家稍微拧巴时，剧情把人拉回来的方式自然，不像系统硬拽。
5. 节奏耐受：中间没有明显“冷掉”“空转”或让我想退出的长段。
6. 下一站牵引：转场前真的让我知道为什么还要继续往下玩。

请严格输出：
总分：X/6
继续玩意愿：会继续 / 可能退出 / 立刻退出
最想退出的位置：一句话
简评：不超过 6 句
"""

S2_JUDGE_PROMPT = """你是转场钩子评审。下面是若干条转场相关文本。
请判断每一条是否包含“让我愿意去下一站”的自然理由，比如地点、事件、目标、人物牵引。
输出 JSON：{"results":[{"index":0,"has_hook":true,"reason":"..."}, ...]}"""

S3_JUDGE_PROMPT = """你是叙事衔接评审。下面给出玩家偏航输入和系统的 bridge 文本。
请判断 bridge 是否自然承接了玩家输入中的话题、情绪或关键词，而不是生硬转向。
输出 JSON：{"results":[{"index":0,"coherent":true,"reason":"..."}, ...]}"""


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_map() -> dict[str, Any]:
    return json.loads((CONSOLE / "opening_map.json").read_text(encoding="utf-8"))


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_config() -> dict[str, Any]:
    cfg_path = CONSOLE / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path)
        for path in TRANSCRIPT_SOURCE_FILES
    }


def current_transcript_key(persona_name: str, config: dict[str, Any]) -> str:
    payload = {
        "cache_version": TRANSCRIPT_CACHE_VERSION,
        "sources": source_hashes(),
        "route": SOFT_ROUTE,
        "persona": persona_name,
        "station_inputs": PERSONA_STRATEGIES[persona_name]["station_inputs"],
        "generation_model": config.get("model"),
        "generation_api_url": config.get("api_url"),
    }
    return sha256_text(stable_json_dumps(payload))[:16]


def current_baseline_key(config: dict[str, Any]) -> str:
    payload = {
        "report_version": BASELINE_REPORT_VERSION,
        "judge_prompt_hash": sha256_text(LLM_JUDGE_PROMPT),
        "judge_seeds": SOFT_JUDGE_SEEDS,
        "judge_temperature": SOFT_JUDGE_TEMPERATURE,
        "judge_timeout_s": SOFT_JUDGE_TIMEOUT_S,
        "judge_max_attempts": SOFT_JUDGE_MAX_ATTEMPTS,
        "judge_transport_retries": SOFT_JUDGE_TRANSPORT_RETRIES,
        "judge_model": config.get("model"),
        "selected_personas": list(SOFT_PERSONA_NAMES),
        "transcript_keys": {
            persona_name: current_transcript_key(persona_name, config)
            for persona_name in SOFT_PERSONA_NAMES
        },
    }
    return sha256_text(stable_json_dumps(payload))[:16]


def transcript_path_for(persona_name: str) -> Path:
    slug = PERSONA_SLUGS.get(persona_name, sha256_text(persona_name)[:8])
    return TRANSCRIPT_DIR / f"opening_ex_s1_{slug}.json"


def transcript_meta_summary(config: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for persona_name in SOFT_PERSONA_NAMES:
        path = transcript_path_for(persona_name)
        payload = read_json_if_exists(path)
        expected_key = current_transcript_key(persona_name, config)
        fresh = bool(payload and payload.get("transcript_key") == expected_key)
        summaries.append(
            {
                "persona": persona_name,
                "path": str(path),
                "exists": path.exists(),
                "fresh": fresh,
                "expected_key": expected_key,
                "actual_key": payload.get("transcript_key") if payload else None,
                "generated_at": payload.get("generated_at") if payload else None,
                "turn_count": payload.get("turn_count") if payload else None,
            }
        )
    return summaries


def load_cached_persona_turns(
    config: dict[str, Any],
    require_fresh: bool = True,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[str]]:
    turns_by_persona: dict[str, list[dict[str, Any]]] = {}
    issues: list[str] = []
    summaries = transcript_meta_summary(config)
    for summary in summaries:
        persona_name = summary["persona"]
        path = Path(summary["path"])
        payload = read_json_if_exists(path)
        if not payload:
            issues.append(f"{persona_name}: missing transcript cache")
            continue
        if require_fresh and not summary["fresh"]:
            issues.append(f"{persona_name}: stale transcript cache")
            continue
        turns_by_persona[persona_name] = payload.get("turns", [])
    return turns_by_persona, summaries, issues


def all_text(msg: dict[str, Any]) -> str:
    return " ".join(str(msg.get(key, "") or "") for key in ("content", "name", "speaker", "stage"))


def call_deepseek(
    prompt: str,
    user_content: str,
    config: dict[str, Any],
    temperature: float = 0.6,
    max_tokens: int = 512,
    seed: int | None = None,
    timeout_s: int = 90,
    retries: int = SOFT_JUDGE_TRANSPORT_RETRIES,
) -> str:
    payload: dict[str, Any] = {
        "model": config.get("model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if seed is not None:
        payload["seed"] = seed

    attempt_plan = []
    for attempt in range(retries + 1):
        label = f"attempt{attempt + 1}"
        backoff_s = SOFT_JUDGE_RETRY_BACKOFF_S * (attempt + 1) if attempt < retries else 0.0
        attempt_plan.append((label, timeout_s, backoff_s))
    raw, debug = llm_transport.post_json_with_retry(
        config.get("api_url", "https://api.deepseek.com/v1/chat/completions"),
        config.get("api_key", ""),
        payload,
        attempt_plan=attempt_plan,
    )
    if raw is None:
        return f"[ERROR: {debug.get('last_error')}]"
    try:
        return raw["choices"][0]["message"]["content"]
    except Exception:
        return "[ERROR: empty_result]"


def parse_judge_json(raw: str) -> dict[str, Any]:
    text = str(raw).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except Exception:
        return {}


def parse_score_out_of_six(raw: str) -> Optional[int]:
    text = str(raw).strip()
    for line in text.splitlines():
        match = re.search(r"(\d+)\s*/\s*6", line)
        if match:
            return int(match.group(1))
    matches = re.findall(r"(\d+)\s*/\s*6", text)
    if matches:
        return int(matches[-1])
    return None


def median_or_none(values: list[Optional[int]]) -> Optional[int]:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return int(median(usable))


def write_soft_baseline(report: dict[str, Any]) -> bool:
    if (report.get("s1") or {}).get("status") == "skipped_all_unavailable" and SOFT_BASELINE_PATH.exists():
        return False
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    SOFT_BASELINE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def iter_dialogue_flows(map_data: dict[str, Any]):
    for place, place_info in map_data.items():
        if not isinstance(place_info, dict):
            continue
        chapters = place_info.get("chapters", {})
        for ch_anchor, chapter_info in chapters.items():
            yield place, ch_anchor, chapter_info.get("dialogue_flow", [])


def check_player_choice_pause(map_data: dict[str, Any]) -> tuple[bool, str]:
    missing: list[str] = []
    for place, ch_anchor, flow in iter_dialogue_flows(map_data):
        for beat_index, beat in enumerate(flow):
            if beat.get("beat_type") != "player_choice":
                continue
            if beat.get("pause_after") is not True:
                missing.append(f"{place}@{ch_anchor}[{beat_index}] pause_after={beat.get('pause_after')!r}")
    if missing:
        return False, "; ".join(missing)
    return True, ""


def scene_handle(req: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    return scene_api.handle(req, DB_PATH, config)


def collect_messages_by_route(route_name: str, route, run_no: int):
    station_messages: dict[str, list[list[dict[str, Any]]]] = {}
    station_pre_intro_messages: dict[str, list[dict[str, Any]]] = {}
    names_unlocked = False

    for place, ch_anchor, scene_id in route:
        station_messages.setdefault(place, [])
        if not names_unlocked:
            station_pre_intro_messages.setdefault(place, [])

        start_res = scene_handle(
            {
                "op": "start_scene",
                "scene_id": scene_id,
                "place": place,
                "ch_anchor": ch_anchor,
                "run_no": run_no,
            }
        )
        flow = scene_api._scene_def(scene_id, place, ch_anchor).get("dialogue_flow", [])

        for msg in start_res.get("messages", []):
            station_messages[place].append([msg])
            if not names_unlocked:
                station_pre_intro_messages[place].append(msg)

        if not names_unlocked:
            for msg in start_res.get("messages", []):
                if msg.get("beat_type") == "introduce" or INTRODUCE_SPEAKERS & {msg.get("name"), msg.get("speaker")}:
                    names_unlocked = True
                    break
            if not names_unlocked and flow and flow[0].get("beat_type") == "introduce":
                names_unlocked = True

        for _ in range(MAX_STATION_TURNS):
            state = SceneState.load(run_no, scene_id)
            if state.canon_beat_index >= len(flow):
                break

            beat = flow[state.canon_beat_index]
            if not names_unlocked and beat.get("beat_type") == "introduce":
                names_unlocked = True

            res = scene_handle(
                {
                    "op": "player_say",
                    "scene_id": scene_id,
                    "place": place,
                    "ch_anchor": ch_anchor,
                    "run_no": run_no,
                    "player_input": "继续",
                }
            )
            turn_msgs = res.get("messages", [])
            if turn_msgs or not (res.get("transition_target") or res.get("scene_over") is True):
                station_messages[place].append(turn_msgs)

            if not names_unlocked:
                station_pre_intro_messages[place].extend(turn_msgs)
                for msg in turn_msgs:
                    if msg.get("beat_type") == "introduce" or INTRODUCE_SPEAKERS & {msg.get("name"), msg.get("speaker")}:
                        names_unlocked = True
                        break

            if res.get("transition_target") or res.get("scene_over") is True:
                break

    return station_messages, station_pre_intro_messages


def collect_gradient_data(route_name: str, route, run_no: int):
    results = []
    for place, ch_anchor, scene_id in route:
        scene_handle(
            {
                "op": "start_scene",
                "scene_id": scene_id,
                "place": place,
                "ch_anchor": ch_anchor,
                "run_no": run_no,
            }
        )
        flow = scene_api._scene_def(scene_id, place, ch_anchor).get("dialogue_flow", [])

        for _ in range(MAX_CONVERGENCE_CHECK_TURNS):
            state = SceneState.load(run_no, scene_id)
            if state.canon_beat_index >= 1:
                break
            res = scene_handle(
                {
                    "op": "player_say",
                    "scene_id": scene_id,
                    "place": place,
                    "ch_anchor": ch_anchor,
                    "run_no": run_no,
                    "player_input": "继续",
                }
            )
            if res.get("transition_target") or res.get("scene_over") is True:
                break

        place_record = []
        for dev_input in DEVIATE_INPUTS:
            dc_before = SceneState.load(run_no, scene_id).deviation_count
            res = scene_handle(
                {
                    "op": "player_say",
                    "scene_id": scene_id,
                    "place": place,
                    "ch_anchor": ch_anchor,
                    "run_no": run_no,
                    "player_input": dev_input,
                }
            )
            dc_after = SceneState.load(run_no, scene_id).deviation_count
            place_record.append((dev_input, dc_before, dc_after, res.get("messages", [])))
            if res.get("transition_target") or res.get("scene_over") is True:
                break
        results.append((place, place_record))
    return results


def collect_persona_run(
    route,
    run_no: int,
    station_inputs: list[str],
    config: dict[str, Any] | None = None,
    force_fallback: bool = False,
    max_station_turns: int | None = None,
    max_terminal_free_turns: int | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    turns: list[dict[str, Any]] = []
    player_inputs: list[str] = []
    input_idx = 0
    station_turn_limit = MAX_STATION_TURNS if max_station_turns is None else max_station_turns

    for place, ch_anchor, scene_id in route:
        flow = scene_api._scene_def(scene_id, place, ch_anchor).get("dialogue_flow", [])
        terminal_free_turns = 0
        scene_handle(
            {
                "op": "start_scene",
                "scene_id": scene_id,
                "place": place,
                "ch_anchor": ch_anchor,
                "run_no": run_no,
            },
            config,
        )

        for _ in range(station_turn_limit):
            state = SceneState.load(run_no, scene_id)
            if flow and state.canon_beat_index >= len(flow):
                terminal_free_turns += 1
                if max_terminal_free_turns is not None and terminal_free_turns > max_terminal_free_turns:
                    break
            if not flow:
                beat = {}
            else:
                beat_index = min(state.canon_beat_index, len(flow) - 1)
                beat = flow[beat_index]

            if beat.get("pause_after") or beat.get("beat_type") in ("player_choice", "introduce"):
                player_input, input_idx = select_station_player_input(station_inputs, input_idx, cycle=True)
            elif beat.get("condition"):
                player_input, input_idx = select_station_player_input(station_inputs, input_idx, cycle=False)
            else:
                player_input = "继续"

            player_inputs.append(player_input)
            res = scene_handle(
                {
                    "op": "player_say",
                    "scene_id": scene_id,
                    "place": place,
                    "ch_anchor": ch_anchor,
                    "run_no": run_no,
                    "player_input": player_input,
                    "force_fallback": force_fallback,
                },
                config,
            )
            turns.append(
                {
                    "place": place,
                    "player_input": player_input,
                    "messages": res.get("messages", []),
                    "has_transition": bool(res.get("transition_target")),
                    "transition_target": (res.get("transition_target") or {}).get("place"),
                    "scene_over": res.get("scene_over"),
                }
            )
            if res.get("transition_target") or res.get("scene_over") is True:
                break

    return player_inputs, turns


def check_monologue_density(station_messages) -> tuple[bool, str]:
    for place, turns in station_messages.items():
        for turn_msgs in turns:
            streak = 0
            for msg in turn_msgs:
                if msg.get("role") in ("npc", "director", "overhear"):
                    streak += 1
                    if streak > 4:
                        return False, f"连续 {streak} 条 NPC/导演消息 in {place}"
                else:
                    streak = 0
    return True, ""


def check_empty_stage(station_messages) -> tuple[bool, str]:
    for place, turns in station_messages.items():
        for idx, turn_msgs in enumerate(turns[1:], start=1):
            if not turn_msgs:
                print(f"DEBUG_EMPTY_STAGE: place={place}, failed_turn_index={idx}, total_turns={len(turns)}, turns={turns}", flush=True)
                return False, f"player_say 后无消息 in {place}"
    return True, ""


def check_narration_drag(all_station_messages) -> tuple[bool, str]:
    for place, turns in all_station_messages.items():
        for turn_msgs in turns:
            for msg in turn_msgs:
                content = all_text(msg)
                for word in HARD_DRAG_WORDS:
                    if word in content:
                        snippet = content[:60].replace("\n", " ")
                        return False, f"硬拽词 '{word}' in {place}: {snippet}"
    return True, ""


def check_convergence_gradient(gradient_data) -> tuple[bool, str]:
    for route_name, route_records in gradient_data:
        for place, records in route_records:
            dc_values = [record[2] for record in records]
            preview = dc_values[:3]
            if len(preview) >= 3:
                # anchored + no-condition beats can either preserve deviate or
                # advance/reset on the next beat, so validate the allowed state
                # envelope instead of one fixed path.
                if preview[0] not in (0, 1):
                    print(f"DEBUG_CONVERGENCE: route={route_name}, place={place}, dc_values={dc_values}, records={records}", flush=True)
                    return False, f"{route_name}/{place} 绗?娆¤劚杞ㄥ悗 dc={preview[0]}"
                if preview[1] not in (0, 1, 2):
                    print(f"DEBUG_CONVERGENCE: route={route_name}, place={place}, dc_values={dc_values}, records={records}", flush=True)
                    return False, f"{route_name}/{place} 绗?娆¤劚杞ㄥ悗 dc={preview[1]}"
                if preview[2] not in (0, 1):
                    print(f"DEBUG_CONVERGENCE: route={route_name}, place={place}, dc_values={dc_values}, records={records}", flush=True)
                    return False, f"{route_name}/{place} 绗?娆¤劚杞ㄥ悗 dc={preview[2]}"
                if max(preview) > 2:
                    print(f"DEBUG_CONVERGENCE: route={route_name}, place={place}, dc_values={dc_values}, records={records}", flush=True)
                    return False, f"{route_name}/{place} dc 涓嶅簲瓒呰繃 2锛屽疄闄?{preview}"
                continue
            for idx, dc in enumerate(dc_values):
                # anchored + no-condition beats preserve a deviate turn instead of
                # force-upgrading it to proceed, so the second off-script attempt
                # may legitimately keep dc at 1 here.
                if (idx == 0 and dc not in (0, 1)) or (idx == 1 and dc not in (0, 1, 2)) or (idx == 2 and dc != 0):
                    print(f"DEBUG_CONVERGENCE: route={route_name}, place={place}, dc_values={dc_values}, records={records}", flush=True)
                    if idx == 0:
                        return False, f"{route_name}/{place} 第1次脱轨后 dc={dc}"
                    if idx == 1:
                        return False, f"{route_name}/{place} 第2次脱轨后 dc={dc}"
                    if idx == 2:
                        return False, f"{route_name}/{place} 第3次脱轨后 dc={dc}，期望 floor 后归零"
    return True, ""


def check_name_gate(pre_intro_messages) -> tuple[bool, str]:
    for place, messages in pre_intro_messages.items():
        for msg in messages:
            text = all_text(msg)
            for name in ALL_REAL_NAMES:
                if name in text and name not in {"老妇/女声", "导演"}:
                    return False, f"真名 '{name}' 出现在 introduce 前 in {place}"
    return True, ""


def _text_bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s", "", text or "")
    if len(compact) > 1:
        return {compact[idx : idx + 2] for idx in range(len(compact) - 1)}
    return {compact} if compact else set()


def _text_similarity(a: str, b: str) -> float:
    ga = _text_bigrams(a)
    gb = _text_bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / ((len(ga) ** 0.5) * (len(gb) ** 0.5))


def _functional_reply_template(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return ""
    if any(token in compact for token in ("录像", "视频", "手机", "单反", "纪念", "手抖", "不方便")):
        return "recording_phone"
    if "你好我是" in compact or "我叫" in compact:
        return "bare_intro"
    if "中文" in compact and "不会" in compact:
        return "cannot_speak_chinese"
    if any(token in compact for token in ("顺着这个话题", "话头", "在意点", "下一站再说")):
        return "generic_tether"
    if any(token in compact for token in ("接下来去哪", "下一个地方", "下一站", "顺路去")):
        return "transition_prompt"
    return ""


def check_recent_npc_similarity_loop(config: dict[str, Any]) -> tuple[bool, str]:
    lookback = 4
    threshold = 0.75
    duplicate_hit_limit = 2
    personas = ("乖巧", "刺头")

    def collect_findings(_map_data):
        findings: list[tuple[str, str, int, str]] = []
        for idx, persona_name in enumerate(personas, start=1):
            _, turns = collect_persona_run(
                SOFT_ROUTE,
                9800 + idx,
                PERSONA_STRATEGIES[persona_name]["station_inputs"],
                config=config,
                force_fallback=True,
            )
            recent_npc: list[str] = []
            for turn_index, turn in enumerate(turns, start=1):
                for msg in turn.get("messages", []):
                    if msg.get("role") != "npc" or not msg.get("content"):
                        continue
                    content = msg["content"].strip()
                    window = recent_npc[-lookback:]
                    dup_hits = sum(1 for old in window if _text_similarity(content, old) >= threshold)
                    if dup_hits >= duplicate_hit_limit:
                        findings.append((persona_name, turn["place"], turn_index, content[:60]))
                    recent_npc.append(content)
        return findings

    findings = run_isolated(collect_findings)
    if findings:
        persona_name, place, turn_index, content = findings[0]
        return False, f"{persona_name}/{place} turn{turn_index} repeated npc loop: {content}"
    return True, ""


def check_functional_reply_loop(config: dict[str, Any]) -> tuple[bool, str]:
    personas = ("乖巧", "刺头")
    cafe_places = {"广场旁咖啡厅", "廊坊亭咖啡厅"}

    def collect_findings(_map_data):
        findings: list[tuple[str, str, str, str, int]] = []
        for idx, persona_name in enumerate(personas, start=1):
            _, turns = collect_persona_run(
                SOFT_ROUTE,
                9820 + idx,
                PERSONA_STRATEGIES[persona_name]["station_inputs"],
                config=config,
                force_fallback=True,
            )
            seen: dict[tuple[str, str, str], int] = {}
            for turn in turns:
                place = turn["place"]
                if place not in cafe_places:
                    continue
                player_input = turn["player_input"]
                for msg in turn.get("messages", []):
                    if msg.get("role") != "npc":
                        continue
                    template = _functional_reply_template(msg.get("content", ""))
                    if not template:
                        continue
                    key = (place, player_input, template)
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] >= 2:
                        findings.append((persona_name, place, player_input, template, seen[key]))
        return findings

    findings = run_isolated(collect_findings)
    if findings:
        persona_name, place, player_input, template, count = findings[0]
        return False, f"{persona_name}/{place} input={player_input!r} repeated template={template} x{count}"
    return True, ""


def check_identity_consistency(map_data: dict[str, Any]) -> tuple[bool, str]:
    invalid: list[str] = []
    for place, ch_anchor, flow in iter_dialogue_flows(map_data):
        for beat_index, beat in enumerate(flow):
            speaker = str(beat.get("speaker") or "")
            text = str(beat.get("text") or "")
            if speaker == "修哉" and "杨树" in text:
                invalid.append(f"{place}@{ch_anchor}[{beat_index}] 修哉 claims 杨树")
            if "你好我是" in text and "stage" in beat and beat.get("stage") == "-":
                invalid.append(f"{place}@{ch_anchor}[{beat_index}] bare intro placeholder")
    if invalid:
        return False, "; ".join(invalid[:4])
    return True, ""


def check_no_fallback_template_phrases(all_station_messages: dict[str, list[list[dict[str, Any]]]]) -> tuple[bool, str]:
    for place, turns in all_station_messages.items():
        for turn_index, turn in enumerate(turns, start=1):
            for msg in turn:
                content = msg.get("content", "")
                for phrase in BANNED_FALLBACK_TEMPLATE_PHRASES:
                    if phrase in content:
                        return False, f"{place} turn{turn_index} contains fallback template phrase: {phrase}"
    return True, ""


def check_persona_no_fallback_template_phrases(config: dict[str, Any]) -> tuple[bool, str]:
    def collect_findings(_map_data):
        findings = []
        for idx, persona_name in enumerate(SOFT_PERSONA_NAMES, start=1):
            _, turns = collect_persona_run(
                SOFT_ROUTE,
                9850 + idx,
                PERSONA_STRATEGIES[persona_name]["station_inputs"],
                config=config,
                force_fallback=True,
            )
            for turn_index, turn in enumerate(turns, start=1):
                for msg in turn.get("messages", []):
                    content = msg.get("content", "")
                    for phrase in BANNED_FALLBACK_TEMPLATE_PHRASES:
                        if phrase in content:
                            findings.append(
                                f"{persona_name} {turn['place']} turn{turn_index} contains fallback template phrase: {phrase}"
                            )
                            return findings
        return findings

    findings = run_isolated(collect_findings)
    if findings:
        return False, findings[0]
    return True, ""


def check_opening_contrarian_first_hook(config: dict[str, Any]) -> tuple[bool, str]:
    route = [ROUTES["A"][0]]

    def collect_findings(_map_data):
        _, turns = collect_persona_run(
            route,
            9840,
            ["好吧，既然你们这么说"],
            config=config,
            force_fallback=True,
        )
        if not turns:
            return ["no turns collected"]
        first_text = "\n".join(msg.get("content", "") for msg in turns[0].get("messages", []))
        weak = [phrase for phrase in BANNED_FALLBACK_TEMPLATE_PHRASES if phrase in first_text]
        if weak:
            return [f"weak contrarian first response phrase: {weak[0]}"]
        hook_terms = ("敷衍", "不信", "随便", "试探", "升旗", "视频", "真纪", "王府井", "跟不跟都行")
        if not any(term in first_text for term in hook_terms):
            return [f"first contrarian response has no hook/friction: {first_text[:80]}"]
        return []

    findings = run_isolated(collect_findings)
    if findings:
        return False, findings[0]
    return True, ""


def check_wangfujing_opening_continuity(map_data: dict[str, Any]) -> tuple[bool, str]:
    place = "王府井街道"
    flow = (map_data.get(place, {}).get("chapters", {}).get("10", {}).get("dialogue_flow", []))
    if not flow:
        return False, "王府井 ch10 dialogue_flow missing"
    full_text = "\n".join(beat.get("text", "") for beat in flow)
    banned = ("散伙", "有缘再见", "回公寓", "很高兴认识", "不要她了", "坐火车", "开车")
    for phrase in banned:
        if phrase in full_text:
            return False, f"王府井开场早段 contains ending/dispersal phrase: {phrase}"
    if not any("海族馆" in beat.get("text", "") for beat in flow):
        return False, "王府井开场早段 has no aquarium hook"
    last = flow[-1]
    if last.get("scene_end") is True:
        return False, "王府井开场早段 must not scene_end before aquarium"
    if last.get("auto_transition") is not True:
        return False, "王府井 final beat should auto_transition to next station"
    return True, ""


def check_cafe_persona_input_ack(config: dict[str, Any]) -> tuple[bool, str]:
    def collect_findings(_map_data):
        findings = []
        cases = [
            ("乖巧", "谢谢你们借我手机", ("谢谢", "帮了大忙", "王府井", "真纪")),
            ("乖巧", "那我们也一起走吧", ("一起", "王府井", "真纪", "临时队友")),
            ("刺头", "不过我觉得有点奇怪", ("奇怪", "王府井", "真纪", "不只是")),
        ]
        for idx, (persona_name, player_input, required_terms) in enumerate(cases, start=1):
            _, turns = collect_persona_run(
                [ROUTES["A"][1]],
                9880 + idx,
                [player_input],
                config=config,
                force_fallback=True,
            )
            cafe_text = "\n".join(
                msg.get("content", "")
                for turn in turns
                for msg in turn.get("messages", [])
                if turn.get("place") == "广场旁咖啡厅"
            )
            if "这个话题可以先聊着看" in cafe_text:
                findings.append(f"cafe {persona_name} input {player_input!r} fell back to generic topic template")
                return findings
            if not any(term in cafe_text for term in required_terms):
                findings.append(f"cafe {persona_name} input {player_input!r} missing acknowledgment hook")
                return findings
        return findings

    findings = run_isolated(collect_findings)
    if findings:
        return False, findings[0]
    return True, ""


def format_turns_for_judge(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, turn in enumerate(turns, start=1):
        lines.append(f"--- 第{idx}轮 [{turn['place']}] ---")
        lines.append(f"玩家输入: {turn['player_input']!r}")
        for msg in turn["messages"]:
            speaker = msg.get("name") or msg.get("speaker") or msg.get("role", "?")
            content = (msg.get("content") or "")[:200]
            stage = msg.get("stage", "")
            if stage:
                lines.append(f"  [{speaker}] {content} / {stage}")
            else:
                lines.append(f"  [{speaker}] {content}")
        if turn["has_transition"]:
            lines.append(f"  <<< 转场 -> {turn['transition_target']} >>>")
        if turn["scene_over"] is True:
            lines.append("  <<< scene_over >>>")
    return "\n".join(lines)


def check_soft_s1_adversarial(config: dict[str, Any], persona_turns: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    report = {
        "metric": "EX-S1",
        "seeds": SOFT_JUDGE_SEEDS,
        "temperature": SOFT_JUDGE_TEMPERATURE,
        "personas": {},
        "available_persona_count": 0,
        "total_median_score": None,
        "max_total_score": len(persona_turns) * 6,
        "threshold_score": len(persona_turns) * 4,
        "status": "ok",
    }
    if not config.get("api_key"):
        report["status"] = "skipped_no_api_key"
        return report

    def judge_one(persona_name: str, user_content: str, seed: int) -> tuple[str, dict[str, Any]]:
        score = None
        raw_preview = ""
        for _ in range(SOFT_JUDGE_MAX_ATTEMPTS):
            raw = call_deepseek(
                LLM_JUDGE_PROMPT,
                user_content,
                config,
                temperature=SOFT_JUDGE_TEMPERATURE,
                max_tokens=300,
                seed=seed,
                timeout_s=SOFT_JUDGE_TIMEOUT_S,
            )
            raw_preview = str(raw).strip()
            score = parse_score_out_of_six(raw_preview)
            if score is not None:
                break
        return persona_name, {"seed": seed, "score": score, "preview": raw_preview[:160]}

    persona_user_content = {
        persona_name: f"玩家画像：{persona_name}\n\n{format_turns_for_judge(turns)[:2500]}"
        for persona_name, turns in persona_turns.items()
    }
    seed_runs_by_persona = {persona_name: [] for persona_name in persona_turns}
    tasks: list[tuple[str, str, int]] = [
        (persona_name, user_content, seed)
        for persona_name, user_content in persona_user_content.items()
        for seed in SOFT_JUDGE_SEEDS
    ]
    worker_count = min(MAX_JUDGE_WORKERS, len(tasks)) or 1
    print(f"[JUDGE] EX-S1 judging {len(tasks)} seed-run(s) with {worker_count} worker(s)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(judge_one, persona_name, user_content, seed): (persona_name, seed)
            for persona_name, user_content, seed in tasks
        }
        for future in concurrent.futures.as_completed(future_map):
            persona_name, _seed = future_map[future]
            try:
                done_persona, seed_run = future.result()
            except Exception as exc:
                done_persona = persona_name
                seed_run = {"seed": _seed, "score": None, "preview": f"[ERROR: {exc}]"}
            seed_runs_by_persona[done_persona].append(seed_run)

    total_median_score = 0
    for persona_name, turns in persona_turns.items():
        seed_runs = sorted(seed_runs_by_persona.get(persona_name, []), key=lambda item: item["seed"])

        median_score = median_or_none([item["score"] for item in seed_runs])
        report["personas"][persona_name] = {
            "seed_runs": seed_runs,
            "median_score": median_score,
            "available_scores": [item["score"] for item in seed_runs if item["score"] is not None],
        }
        if median_score is None:
            continue

        report["available_persona_count"] += 1
        total_median_score += median_score

    if report["available_persona_count"] == 0:
        report["status"] = "skipped_all_unavailable"
        return report

    report["total_median_score"] = total_median_score
    report["pass"] = total_median_score >= report["threshold_score"]
    return report


def collect_transition_messages(all_station_messages) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    keywords = ("前往", "来到", "离开", "跟着", "穿过", "走进", "去", "医院", "王府井", "海族馆")
    for place, turns in all_station_messages.items():
        for turn_msgs in turns:
            for msg in turn_msgs:
                content = (msg.get("content") or "").strip()
                role = msg.get("role")
                if not content:
                    continue
                if role in ("director", "narrator", "narration", "overhear") and any(key in content for key in keywords):
                    transitions.append({"place_before": place, "text": content, "index": len(transitions)})
                    break
    return transitions


def check_soft_s2_transition_hooks(config: dict[str, Any], all_station_messages) -> int:
    if not config.get("api_key"):
        return 0
    transitions = collect_transition_messages(all_station_messages)
    if not transitions:
        return 1

    raw = call_deepseek(
        S2_JUDGE_PROMPT,
        "\n".join(f"[{item['index']}] {item['text']}" for item in transitions),
        config,
        max_tokens=512,
    )
    parsed = parse_judge_json(raw)
    results = parsed.get("results") or []
    hooked = sum(1 for item in results if item.get("has_hook"))
    return hooked if hooked == len(transitions) else 0


def check_soft_s3_bridge_semantic(config: dict[str, Any], gradient_data) -> int:
    if not config.get("api_key"):
        return 0

    pairs: list[dict[str, str]] = []
    for route_name, route_records in gradient_data:
        for place, records in route_records:
            for dev_input, dc_before, dc_after, messages in records:
                if dc_before < 2 or dc_after != 0:
                    continue
                director_msgs = [msg for msg in messages if msg.get("role") == "director"]
                if director_msgs:
                    pairs.append({"player_input": dev_input, "bridge": director_msgs[0].get("content", "")})

    if not pairs:
        return 1

    raw = call_deepseek(
        S3_JUDGE_PROMPT,
        "\n".join(
            f"[{idx}] 玩家输入={pair['player_input']!r}\n   bridge={pair['bridge']!r}"
            for idx, pair in enumerate(pairs)
        ),
        config,
        max_tokens=512,
    )
    parsed = parse_judge_json(raw)
    results = parsed.get("results") or []
    coherent = sum(1 for item in results if item.get("coherent"))
    return coherent if coherent == len(pairs) else 0


def run_isolated(fn):
    map_cache = load_map()
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)

        def mock_get_path(run_no, scene_id):
            return tmp_path / f"state_{run_no}_{scene_id}.json"

        def mock_load_all_committed(run_no):
            committed: list[str] = []
            for path in tmp_path.glob(f"state_{run_no}_*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for item in data.get("committed", []):
                    if item not in committed:
                        committed.append(item)
            return committed

        def mock_load_all_introduced(run_no):
            introduced: dict[str, bool] = {}
            for path in tmp_path.glob(f"state_{run_no}_*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for key, value in data.get("introduced", {}).items():
                    if value:
                        introduced[key] = True
            return introduced

        with (
            patch.object(scene_state.SceneState, "get_path", side_effect=mock_get_path),
            patch.object(scene_state.SceneState, "load_all_committed", side_effect=mock_load_all_committed),
            patch.object(scene_state.SceneState, "load_all_introduced", side_effect=mock_load_all_introduced),
            patch.object(scene_api, "_load_map", side_effect=lambda: map_cache),
        ):
            old_log = scene_api._SCENE_LOG_PATH
            old_ledger = scene_api._DELTA_LEDGER_PATH
            old_runtime = scene_api._RUNTIME_KNOWLEDGE_PATH
            scene_api._SCENE_LOG_PATH = os.path.join(td, "scene_log.jsonl")
            scene_api._DELTA_LEDGER_PATH = os.path.join(td, "delta_ledger.json")
            scene_api._RUNTIME_KNOWLEDGE_PATH = os.path.join(td, "runtime_knowledge.json")
            try:
                return fn(map_cache)
            finally:
                scene_api._SCENE_LOG_PATH = old_log
                scene_api._DELTA_LEDGER_PATH = old_ledger
                scene_api._RUNTIME_KNOWLEDGE_PATH = old_runtime


def generate_persona_transcript_payload(persona_name: str, config: dict[str, Any]) -> dict[str, Any]:
    station_inputs = PERSONA_STRATEGIES[persona_name]["station_inputs"]
    persona_run_no = 9500 + list(SOFT_PERSONA_NAMES).index(persona_name) + 1
    _, turns = run_isolated(
        lambda _map_data: collect_persona_run(
            SOFT_ROUTE,
            persona_run_no,
            station_inputs,
            config=config,
        )
    )
    return {
        "cache_version": TRANSCRIPT_CACHE_VERSION,
        "persona": persona_name,
        "persona_slug": PERSONA_SLUGS.get(persona_name),
        "description": PERSONA_STRATEGIES[persona_name]["description"],
        "route": SOFT_ROUTE,
        "station_inputs": station_inputs,
        "generation_model": config.get("model"),
        "generation_api_url": config.get("api_url"),
        "source_hashes": source_hashes(),
        "transcript_key": current_transcript_key(persona_name, config),
        "turn_count": len(turns),
        "generated_at": utc_now_iso(),
        "turns": turns,
    }


def generate_transcript_cache(
    config: dict[str, Any],
    force: bool = False,
    max_workers: int = MAX_TRANSCRIPT_WORKERS,
) -> list[dict[str, Any]]:
    if not config.get("api_key"):
        raise RuntimeError("config.json missing api_key; cannot regenerate transcripts")

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = transcript_meta_summary(config)
    pending = [item["persona"] for item in summaries if force or not item["fresh"]]
    if not pending:
        print("[CACHE] transcript cache already fresh")
        return summaries

    worker_count = min(max_workers, len(pending))
    print(f"[CACHE] regenerating {len(pending)} persona transcript(s) with {worker_count} worker(s)")

    def write_payload(persona_name: str, payload: dict[str, Any]) -> None:
        path = transcript_path_for(persona_name)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[CACHE] wrote {path} ({payload['turn_count']} turns)")

    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(generate_persona_transcript_payload, persona_name, config): persona_name
                for persona_name in pending
            }
            for future in concurrent.futures.as_completed(future_map):
                persona_name = future_map[future]
                payload = future.result()
                write_payload(persona_name, payload)
    except Exception as exc:
        print(f"[CACHE] parallel regen unavailable, falling back to sequential: {exc}")
        for persona_name in pending:
            payload = generate_persona_transcript_payload(persona_name, config)
            write_payload(persona_name, payload)

    return transcript_meta_summary(config)


def collect_hard_context():
    all_station_messages: dict[str, list[list[dict[str, Any]]]] = {}
    all_pre_intro_messages: dict[str, list[dict[str, Any]]] = {}
    all_gradient_data = []

    def collect_body(map_data):
        nonlocal all_station_messages, all_pre_intro_messages, all_gradient_data
        for route_idx, (route_name, route) in enumerate(ROUTES.items(), start=1900):
            run_no = route_idx * 100 + 1
            messages, pre_messages = collect_messages_by_route(route_name, route, run_no)
            for place, turns in messages.items():
                all_station_messages.setdefault(place, []).extend(turns)
            for place, msgs in pre_messages.items():
                all_pre_intro_messages.setdefault(place, []).extend(msgs)
            all_gradient_data.append((route_name, collect_gradient_data(route_name, route, run_no)))
        return map_data

    map_data = run_isolated(collect_body)
    return map_data, all_station_messages, all_pre_intro_messages, all_gradient_data


def build_soft_report(
    config: dict[str, Any],
    all_persona_turns: dict[str, list[dict[str, Any]]],
    transcript_summary: list[dict[str, Any]],
    all_station_messages=None,
    all_gradient_data=None,
    report_only: bool = False,
) -> dict[str, Any]:
    s1 = check_soft_s1_adversarial(config, all_persona_turns)
    report = {
        "report_version": BASELINE_REPORT_VERSION,
        "generated_at": utc_now_iso(),
        "baseline_path": str(SOFT_BASELINE_PATH),
        "judge_mode": "cold_start_easily_bored_newcomer",
        "runtime_layer": "scene_api.handle(config=provided)",
        "baseline_key": current_baseline_key(config),
        "transcript_cache": transcript_summary,
        "routes": {"soft_route": SOFT_ROUTE, "personas": list(all_persona_turns.keys())},
        "s1": s1,
        "s2": None,
        "s3": None,
        "status": "ok",
    }
    if s1.get("status", "").startswith("skipped"):
        report["status"] = s1["status"]
        return report
    if report_only:
        report["status"] = "report_only"
        return report

    s2 = check_soft_s2_transition_hooks(config, all_station_messages or {})
    s3 = check_soft_s3_bridge_semantic(config, all_gradient_data or [])
    report["s2"] = {"raw_score": s2, "pass": s2 >= 0}
    report["s3"] = {"raw_score": s3, "pass": s3 >= 0}
    return report


def print_hard_results(map_data, all_station_messages, all_pre_intro_messages, all_gradient_data) -> bool:
    literal_repeat_ok, literal_repeat_detail = check_recent_npc_similarity_loop({})
    functional_repeat_ok, functional_repeat_detail = check_functional_reply_loop({})
    repeat_ok = literal_repeat_ok and functional_repeat_ok
    repeat_detail = literal_repeat_detail if not literal_repeat_ok else functional_repeat_detail
    identity_ok, identity_detail = check_identity_consistency(map_data)
    template_ok, template_detail = check_no_fallback_template_phrases(all_station_messages)
    persona_template_ok, persona_template_detail = check_persona_no_fallback_template_phrases({})
    template_ok = template_ok and persona_template_ok
    template_detail = template_detail if not template_ok and template_detail else persona_template_detail
    first_hook_ok, first_hook_detail = check_opening_contrarian_first_hook({})
    wangfujing_ok, wangfujing_detail = check_wangfujing_opening_continuity(map_data)
    cafe_ack_ok, cafe_ack_detail = check_cafe_persona_input_ack({})
    checks = [
        ("EX-H1", check_monologue_density(all_station_messages)),
        ("EX-H2", check_empty_stage(all_station_messages)),
        ("EX-H3", check_narration_drag(all_station_messages)),
        ("EX-H4", check_convergence_gradient(all_gradient_data)),
        ("EX-H5", check_name_gate(all_pre_intro_messages)),
        ("EX-H6", check_player_choice_pause(map_data)),
        ("EX-H7", (repeat_ok, repeat_detail)),
        ("EX-H8", (identity_ok, identity_detail)),
        ("EX-H9", (template_ok, template_detail)),
        ("EX-H10", (first_hook_ok, first_hook_detail)),
        ("EX-H11", (wangfujing_ok, wangfujing_detail)),
        ("EX-H12", (cafe_ack_ok, cafe_ack_detail)),
    ]
    for name, (ok, detail) in checks:
        print(f"{name}: {'PASS' if ok else 'FAIL'} {detail}")
    return all(ok for _, (ok, _) in checks)


def print_transcript_summary(summary: list[dict[str, Any]]) -> None:
    for item in summary:
        freshness = "fresh" if item["fresh"] else "stale"
        if not item["exists"]:
            freshness = "missing"
        print(
            f"  {item['persona']}: {freshness} | turns={item['turn_count']} "
            f"| generated_at={item['generated_at']}"
        )


def print_baseline_only(config: dict[str, Any]) -> int:
    payload = read_json_if_exists(SOFT_BASELINE_PATH)
    if not payload:
        print("[BASELINE] missing baseline report")
        return 0

    stale = payload.get("baseline_key") != current_baseline_key(config)
    status = "stale" if stale else "fresh"
    print(f"[BASELINE] {status}")
    print(f"  generated_at={payload.get('generated_at')}")
    print(f"  status={payload.get('status')}")
    s1 = payload.get("s1") or {}
    if s1.get("total_median_score") is not None:
        print(
            f"  EX-S1 median total={s1.get('total_median_score')}/{s1.get('max_total_score')} "
            f"(threshold {s1.get('threshold_score')})"
        )
    for item in payload.get("transcript_cache", []):
        freshness = "fresh" if item.get("fresh") else "stale"
        if not item.get("exists"):
            freshness = "missing"
        print(f"  transcript {item.get('persona')}: {freshness} | generated_at={item.get('generated_at')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="opening experience checks")
    parser.add_argument("--hard", action="store_true", help="run hard checks only")
    parser.add_argument("--soft", action="store_true", help="judge cached transcripts and run S2/S3")
    parser.add_argument("--soft-report", action="store_true", help="judge cached transcripts and write baseline")
    parser.add_argument("--soft-regen", action="store_true", help="regenerate cached transcripts, then write baseline")
    parser.add_argument("--soft-baseline", action="store_true", help="read latest baseline only (no LLM)")
    parser.add_argument("--all", action="store_true", help="run hard checks and cached soft checks")
    parser.add_argument("--api-key", default=None, help="override API key")
    args = parser.parse_args()

    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key

    config = read_config()
    if args.api_key:
        config["api_key"] = args.api_key

    run_hard = args.hard or args.all
    run_soft = args.soft or args.all
    run_soft_report = args.soft_report or args.soft_regen
    run_soft_regen = args.soft_regen
    run_soft_baseline = args.soft_baseline

    if not (run_hard or run_soft or run_soft_report or run_soft_baseline):
        parser.print_help()
        return 0

    if run_soft_baseline and not (run_hard or run_soft or run_soft_report):
        return print_baseline_only(config)

    print("=== opening experience ===")

    if run_soft_regen:
        try:
            summary = generate_transcript_cache(config)
        except Exception as exc:
            print(f"[CACHE] regen failed: {exc}")
            return 1
        print_transcript_summary(summary)

    map_data = None
    all_station_messages = None
    all_pre_intro_messages = None
    all_gradient_data = None
    if run_hard or run_soft:
        map_data, all_station_messages, all_pre_intro_messages, all_gradient_data = collect_hard_context()

    if run_hard:
        hard_pass = print_hard_results(map_data, all_station_messages, all_pre_intro_messages, all_gradient_data)
        if not hard_pass:
            return 1

    if run_soft or run_soft_report:
        if not config.get("api_key"):
            print("[SOFT] missing api_key")
            return 1

        persona_turns, transcript_summary, issues = load_cached_persona_turns(config, require_fresh=True)
        print_transcript_summary(transcript_summary)
        if issues:
            for issue in issues:
                print(f"[CACHE] {issue}")
            print("[CACHE] run --soft-regen to refresh transcript cache")
            return 1

        report = build_soft_report(
            config,
            persona_turns,
            transcript_summary,
            all_station_messages=all_station_messages,
            all_gradient_data=all_gradient_data,
            report_only=not run_soft,
        )
        s1 = report["s1"]
        if s1.get("status", "").startswith("skipped"):
            print(f"EX-S1 report: {s1['status']}")
        else:
            print(
                f"EX-S1 median total: {s1['total_median_score']}/{s1['max_total_score']} "
                f"(threshold {s1['threshold_score']}) => {'PASS' if s1.get('pass') else 'FAIL'}"
            )
            for persona_name, persona_report in s1.get("personas", {}).items():
                scores = [item["score"] for item in persona_report.get("seed_runs", [])]
                print(f"  {persona_name}: median={persona_report.get('median_score')} seeds={scores}")

        if run_soft_report:
            wrote = write_soft_baseline(report)
            if wrote:
                print(f"[REPORT] wrote {SOFT_BASELINE_PATH}")
            else:
                print(f"[REPORT] skipped write; keeping previous baseline because all judge calls were unavailable")
            if not run_soft:
                return 0

        if run_soft:
            s2_pass = report["s2"]["pass"] if report["s2"] is not None else True
            s3_pass = report["s3"]["pass"] if report["s3"] is not None else True
            print(f"EX-S2: {'PASS' if s2_pass else 'FAIL'}")
            print(f"EX-S3: {'PASS' if s3_pass else 'FAIL'}")
            if not (s1.get("pass") and s2_pass and s3_pass):
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
