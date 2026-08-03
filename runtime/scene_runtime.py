#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scene_runtime.py -- Loop B2: group scene runtime for living NPC scenes.

The front end should show places and ongoing scene flow. This module keeps the
chapter anchor hidden in runtime context so truth gating still works without
turning the UI into a chapter selector.
"""
from __future__ import annotations

import os
import json
import re
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from prompt_pipeline import (
    DEFAULT_DB,
    resolve_knowledge,
    resolve_persona,
    resolve_scene,
    resolve_voice,
)

try:  # 名册单一来源(R6):被 import 为 runtime.scene_runtime 或裸 scene_runtime 两种路径
    from runtime.name_book import MAIN_TRIO, all_aliases, anon_replacements
    from runtime.file_locks import SCENE_LOG_LOCK
except ImportError:
    from name_book import MAIN_TRIO, all_aliases, anon_replacements
    from file_locks import SCENE_LOG_LOCK


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_STATE_UPDATE_KEYS = {"trust_delta", "alert_delta", "memory_write", "created_runtime_props", "scene_flags", "committed"}
DEFAULT_OPENING_MEMORY = ROOT / "runtime" / "opening_memory.json"
DEFAULT_SCHEDULES = ROOT / "c1_web_console" / "schedules.json"


def anonymize_text(text: str, introduced: dict[str, bool]) -> str:
    if not text:
        return ""
    
    replacements = anon_replacements(introduced)  # 单一来源:runtime/name_book.py

    # Sort replacements by source length in descending order
    replacements.sort(key=lambda x: len(x[0]), reverse=True)
    
    res = text
    for src, dst in replacements:
        res = res.replace(src, dst)
    return res


def _table_cols(cur: sqlite3.Cursor, table: str) -> list[str]:
    try:
        return [row[1] for row in cur.execute(f'PRAGMA table_info("{table}")')]
    except sqlite3.Error:
        return []


def _pick(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def _bigrams(text: str) -> set[str]:
    text = re.sub(r"\s", "", text or "")
    if len(text) > 1:
        return {text[i : i + 2] for i in range(len(text) - 1)}
    return {text} if text else set()


def _score(query: str, text: str) -> float:
    a, b = _bigrams(query), _bigrams(text)
    if not a or not b:
        return 0.0
    return len(a & b) / ((len(a) ** 0.5) * (len(b) ** 0.5))


def _surface_summary(persona_text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", persona_text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def load_opening_memory(
    cons: str,
    ch_anchor: int,
    memory_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Load a scene-local opening projection bound to one consciousness id."""
    path = Path(memory_path) if memory_path else DEFAULT_OPENING_MEMORY
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    memories = data.get("memories", {})
    entries = memories.get(cons)
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ch_min = int(entry.get("ch_min", 1))
        ch_max = int(entry.get("ch_max", 9999))
        if ch_min <= int(ch_anchor) <= ch_max:
            projection = dict(entry)
            projection["cons"] = cons
            projection["schema_version"] = data.get("schema_version", "")
            return projection
    return None


def select_lorebook_entries(
    projection: dict[str, Any] | None,
    query: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """Select always-on and keyword-triggered opening lorebook facts.

    The projection is the only authorized source for concrete life facts. If a
    keyed fact is not triggered, callers should leave it out rather than invite
    the model to fill the blank.
    """
    if not projection:
        return {"always": [], "keyed": []}
    lorebook = projection.get("lorebook")
    if not isinstance(lorebook, dict):
        return {"always": [], "keyed": []}

    always = [item for item in lorebook.get("always", []) if isinstance(item, dict)]
    keyed: list[dict[str, Any]] = []
    text = re.sub(r"\s+", "", query or "").lower()
    if text:
        for item in lorebook.get("keyed", []):
            if not isinstance(item, dict):
                continue
            keys = item.get("keys") or []
            if any(str(key).lower() in text for key in keys):
                keyed.append(item)
    return {"always": always, "keyed": keyed}


def _public_voice_samples(
    ctx: dict[str, Any],
    ch_anchor: int,
    query: str | None = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    quotes = ctx.get("voice", {}).get("quotes") or []
    safe_quotes: list[dict[str, Any]] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        quote_ch = quote.get("ch")
        if quote_ch is None or int(quote_ch) <= int(ch_anchor):
            safe_quotes.append(quote)
    if not safe_quotes:
        return []
    query_text = re.sub(r"\s+", "", query or "")
    if not query_text:
        return safe_quotes[:limit]
    ranked = []
    for idx, quote in enumerate(safe_quotes):
        haystack = " ".join(str(quote.get(key, "") or "") for key in ("text", "context"))
        ranked.append((_score(query_text, haystack), -idx, quote))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = [quote for score, _idx, quote in ranked if score > 0][:limit]
    if len(selected) < limit:
        selected.extend(quote for quote in safe_quotes if quote not in selected)
    return selected[:limit]


def _voice_brief(persona_text: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    sample_texts = [str(q.get("text", "") or "").strip() for q in samples if q.get("text")]
    rules = [
        "use persona as boundary, not exposition",
        "borrow rhythm and stance from samples, never copy a full sample line",
        "make one concrete reaction before asking a new question",
    ]
    if sample_texts:
        rules.append("keep the next line close to these samples' sentence length and pressure")
    if persona_text:
        rules.append("let the surface persona color word choice and emotional temperature")
    return {
        "source": "persona_surface+selected_voice_samples",
        "rules": rules,
    }


def build_npc_generation_context(
    cons: str,
    scene_state: dict[str, Any],
    ctx: dict[str, Any],
    player_input: str | None = None,
) -> dict[str, Any]:
    """Build the per-NPC speech context used by the B7 voice layer."""
    memory = ctx.get("memory", {})
    projection = memory.get("opening_projection")
    selected_lore = select_lorebook_entries(projection, player_input or "")
    ch_anchor = int(scene_state.get("runtime", {}).get("ch_anchor", 1))
    persona_text = ctx.get("persona", {}).get("text") or ""
    query = " ".join(
        str(part or "")
        for part in (
            player_input,
            scene_state.get("location"),
            scene_state.get("current_beat"),
        )
    )
    voice_samples = _public_voice_samples(ctx, ch_anchor, query=query)
    return {
        "cons": cons,
        "persona_surface": _surface_summary(persona_text, 360),
        "voice_samples": voice_samples,
        "voice_brief": _voice_brief(persona_text, voice_samples),
        "lorebook": selected_lore,
        "agent_state": ctx.get("agent_state", build_agent_state(cons, scene_state)),
        "known_truths": memory.get("known_truths", [])[:6],
        "forbidden_prop_ids": [row.get("prop_id") for row in memory.get("forbidden_truths", [])[:12]],
    }


@lru_cache(maxsize=8)
def _load_schedules_cached(source_text: str) -> dict[str, Any]:
    source = Path(source_text)
    if not source.exists():
        return {}
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_schedules(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    source = Path(path) if path else DEFAULT_SCHEDULES
    return _load_schedules_cached(str(source.resolve()))


def build_agent_state(
    cons: str,
    scene_state: dict[str, Any],
    schedules_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Build B8 in-scene agent state: agenda, social role, awareness."""
    schedules = _load_schedules(schedules_path)
    roles = schedules.get("_opening_agent_roles", {}) if isinstance(schedules, dict) else {}
    agendas = schedules.get("_opening_agenda", {}) if isinstance(schedules, dict) else {}
    role_cfg = roles.get(cons, {}) if isinstance(roles, dict) else {}
    agenda_id = role_cfg.get("agenda_id") or ""
    agenda_cfg = agendas.get(agenda_id, {}) if isinstance(agendas, dict) else {}
    present = [
        item for item in scene_state.get("present_characters", [])
        if isinstance(item, dict) and item.get("cons")
    ]
    present_cons = [item["cons"] for item in present]
    present_names = [item.get("name") or item["cons"] for item in present]
    known_absent = list(role_cfg.get("known_absent") or [])
    return {
        "cons": cons,
        "short_term_agenda": {
            "agenda_id": agenda_id,
            "text": agenda_cfg.get("text", ""),
            "keywords": list(agenda_cfg.get("keywords") or []),
            "source_events": list(agenda_cfg.get("source_events") or []),
            "next_scene": dict(agenda_cfg.get("next_scene") or {}),
            "source": f"c1_web_console/schedules.json:_opening_agenda.{agenda_id}" if agenda_id and agenda_cfg else "",
        },
        "long_term_thread": role_cfg.get("long_term_thread", "★★★ 待人裁：主线方向未定。"),
        "social_role": dict(role_cfg.get("social_role") or {"label": "在场者", "initiative": 0.1, "keywords": []}),
        "present_awareness": {
            "present_cons": present_cons,
            "present_names": present_names,
            "known_absent": known_absent,
        },
    }


def bid_turn_taking(
    scene_state: dict[str, Any],
    player_input: str | None,
    agent_states: dict[str, dict[str, Any]] | None = None,
    max_speakers: int = 2,
) -> dict[str, Any]:
    """B5': zero-LLM decentralized speaker bidding."""
    present = _present_cons(scene_state)
    text = re.sub(r"\s+", "", player_input or "")
    if not present:
        return {"speakers": [], "bids": [], "llm_calls": 0}
    states = agent_states or {cons: build_agent_state(cons, scene_state) for cons in present}
    recent_npc = [
        item.get("cons") for item in scene_state.get("recent_log", [])[-4:]
        if item.get("role") == "npc" and item.get("cons")
    ]
    recent_npc_wide = [
        item.get("cons") for item in scene_state.get("recent_log", [])[-8:]
        if item.get("role") == "npc" and item.get("cons")
    ]
    lead_streak = 0
    lead_cons = None
    for cons in reversed(recent_npc_wide):
        if lead_cons is None:
            lead_cons = cons
        if cons != lead_cons:
            break
        lead_streak += 1
    name_by_cons = {
        item.get("cons"): item.get("name") or item.get("cons")
        for item in scene_state.get("present_characters", [])
        if isinstance(item, dict)
    }
    # 单一来源:runtime/name_book.py(R6 收敛;修哉自此可被「懒散青年」点名,原为漂移缺失)
    aliases = {cons: all_aliases(cons) for cons in MAIN_TRIO}
    bids: list[dict[str, Any]] = []
    for idx, cons in enumerate(present):
        state = states.get(cons) or build_agent_state(cons, scene_state)
        score = float(state.get("social_role", {}).get("initiative", 0.1) or 0.1)
        reasons = ["social_role"]
        cons_aliases = [name_by_cons.get(cons, "")] + aliases.get(cons, [])
        named = False
        if text and any(alias and alias in text for alias in cons_aliases):
            score += 0.75
            reasons.append("named")
            named = True
        agenda = state.get("short_term_agenda", {})
        agenda_keywords = [str(k) for k in agenda.get("keywords", [])]
        if text and any(k and k in text for k in agenda_keywords):
            score += 0.42
            reasons.append("agenda")
        role_keywords = [str(k) for k in state.get("social_role", {}).get("keywords", [])]
        if text and any(k and k in text for k in role_keywords):
            score += 0.28
            reasons.append("topic")
        if cons in recent_npc:
            score -= 0.24
            reasons.append("recent_penalty")
        if text and lead_cons == cons and lead_streak >= 2 and not named:
            score -= min(0.18 * lead_streak, 0.54)
            reasons.append("monopoly_penalty")
        if text and lead_streak >= 2 and cons not in recent_npc_wide:
            score += 0.28
            reasons.append("silent_boost")
        score -= idx * 0.015
        if not text:
            reasons.append("director_tick")
        bids.append({"cons": cons, "score": round(score, 3), "reasons": reasons})
    bids.sort(key=lambda item: item["score"], reverse=True)

    if not text:
        chosen = [item for item in bids if item["score"] >= 0.35][:1]
    else:
        chosen = [item for item in bids if item["score"] >= 0.45][:max_speakers]
    return {
        "speakers": [{"cons": item["cons"], "reason": "bid", "bid": item["score"], "bid_reasons": item["reasons"]} for item in chosen],
        "bids": bids,
        "llm_calls": 0,
    }


def _legal_transition_target(scene_state: dict[str, Any], map_data: dict[str, Any]) -> dict[str, Any] | None:
    place = scene_state.get("location")
    run_no = scene_state.get("runtime", {}).get("run_no") or 1
    
    exits = []
    if isinstance(map_data, dict):
        exits = (map_data.get(place, {}) or {}).get("available_exits", []) or []
        
    import os
    _HERE = os.path.dirname(__file__)
    _ROOT = os.path.abspath(os.path.join(_HERE, ".."))
    states_dir = os.path.join(_ROOT, "c1_web_console", "states")
    
    unvisited_exits = []
    visited_exits = []
    
    for item in exits:
        target_place = item.get("place")
        ch_anchor = str(item.get("ch_anchor", ""))
        scene_id = item.get("scene_id")
        
        if target_place in map_data and ch_anchor in (map_data.get(target_place, {}).get("chapters", {}) or {}):
            state_file = os.path.join(states_dir, f"state_{run_no}_{scene_id}.json")
            if os.path.exists(state_file):
                visited_exits.append(item)
            else:
                unvisited_exits.append(item)
                
    # 优先非 shared 路由（主线路由），而非盲目取第一个
    all_valid = unvisited_exits + visited_exits
    if all_valid:
        smart = _smart_route_pick(all_valid, None, "auto")
        return dict(smart)
    return None


def _smart_route_pick(valid_exits: list[dict], player_input: str | None, reason: str) -> dict | None:
    """从合法出口中智能选路：玩家明确提及 > 模糊关键字匹配 > 非 shared > 有 route 的。"""
    if not valid_exits:
        return None
    text = player_input or ""

    # 1. 玩家明确提到某地 → 精确匹配
    for e in valid_exits:
        if e.get("place", "") and e["place"] in text:
            return e

    # 2. 模糊匹配 (Fuzzy keyword route selection)
    if text:
        # Route A: 海族馆/海洋馆/水族馆/水母/鱼
        if any(kw in text for kw in ["海族馆", "海洋馆", "水族馆", "水母", "鱼"]):
            route_a = [e for e in valid_exits if e.get("route") == "A"]
            if route_a:
                return route_a[0]
        # Route B: 真纪/张尘/天津/列车/火车
        if any(kw in text for kw in ["真纪", "张尘", "天津", "列车", "火车"]):
            route_b = [e for e in valid_exits if e.get("route") == "B"]
            if route_b:
                return route_b[0]
        # Route C: 十六中/直接回/独自/学校/校门
        if any(kw in text for kw in ["十六中", "直接回", "独自", "学校", "校门"]):
            route_c = [e for e in valid_exits if e.get("route") == "C"]
            if route_c:
                return route_c[0]

    # 3. beats exhausted（idle 输入）→ 优先非 shared 路由
    if reason == "canon_beats_exhausted":
        cafe_prelude = [e for e in valid_exits if e.get("scene_id") == "OPENING_CAFE_001"]
        if cafe_prelude:
            return cafe_prelude[0]
        non_shared = [e for e in valid_exits if e.get("route", "shared") != "shared"]
        if non_shared:
            return non_shared[0]

    return valid_exits[0]


def evaluate_gm_pacing(
    scene_state: dict[str, Any],
    player_input: str | None,
    recent_log: list[dict[str, Any]] | None,
    agent_states: dict[str, dict[str, Any]] | None,
    map_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """B9 GM pacing gate: close only on explicit exits (canon exhausted, player leave intent, agenda expired)."""
    text = re.sub(r"\s+", "", player_input or "")
    target = _legal_transition_target(scene_state, map_data or {})
    if not target:
        return {"should_transition": False, "target": None, "score": 0.0, "threshold": 1.0, "reason": "NO_LEGAL_TARGET", "narration": ""}
    
    should = False
    reasons = []
    
    # 1. Check if player wants to leave
    if any(key in text for key in ("再见", "先走", "回头见", "告辞", "走了", "走啦", "拜拜", "走吧", "离开", "闪了", "去咖啡厅", "去海洋馆", "去王府井")):
        should = True
        reasons.append("player_leave_intent")
    
    # 动态匹配：若输入中提及了当前场景的任一有效出口，则设定转场 (B9/L3)
    location = scene_state.get("location")
    if location and map_data:
        exits = map_data.get(location, {}).get("available_exits", []) or []
        for e in exits:
            p = e.get("place", "")
            if p:
                p_clean = re.sub(r"[^\w一-龥]", "", p)
                if p_clean in text or (len(p_clean) >= 2 and p_clean[:2] in text) or (len(p_clean) >= 3 and p_clean[-3:] in text):
                    should = True
                    if "player_leave_intent" not in reasons:
                        reasons.append("player_leave_intent")
                    break
    
    # 2. Check if canon beats are exhausted (only triggers transition on idle inputs)
    flow = scene_state.get("dialogue_flow", [])
    index = scene_state.get("canon_beat_index", 0)
    print(f"DEBUG_PACING: index={index}, len={len(flow)}", flush=True)
    cleaned_input = re.sub(r"[^\w\u4e00-\u9fa5]", "", player_input or "").strip().lower()
    is_idle = (not player_input) or (cleaned_input in ("", "嗯", "好", "继续", "然后呢", "嗯嗯", "行", "好的", "go", "next", "continue"))
    follow_along = any(token in cleaned_input for token in (
        "跟你们走", "一起走", "接下来去哪", "下一站", "往哪", "去哪里", "我跟你们", "算了我跟"
    ))
    if flow and index >= len(flow) and (is_idle or follow_along):
        should = True
        reasons.append("canon_beats_exhausted")
        
    agenda_text = ""
    if agent_states:
        first = next(iter(agent_states.values()))
        agenda_text = first.get("short_term_agenda", {}).get("text", "")
        
    # 智能选路：beats exhausted 时排除 shared 出口，走主线路由
    if should and "canon_beats_exhausted" in reasons:
        location = scene_state.get("location")
        all_exits = (map_data or {}).get(location, {}).get("available_exits", []) or []
        valid = []
        for e in all_exits:
            target_place = e.get("place")
            target_ch = str(e.get("ch_anchor", ""))
            target_info = (map_data or {}).get(target_place, {}) if target_place else {}
            if target_info and target_ch in (target_info.get("chapters", {}) or {}):
                valid.append(e)
        smart = _smart_route_pick(valid, player_input, "canon_beats_exhausted")
        if smart:
            target = smart

    narration = ""
    if should:
        narration = f"他们还有自己的安排。{agenda_text or '当前地点的话题暂时收住，下一段路在门外接上。'}"
        
    return {
        "should_transition": should,
        "target": target if should else None,
        "score": 1.0 if should else 0.0,
        "threshold": 0.5,
        "reason": ",".join(reasons) if reasons else "keep_scene",
        "narration": narration,
    }


def append_scene_log(
    log_path: str | os.PathLike[str],
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Append one scene log record. run=0 is a read-only baseline."""
    run_no = int(entry.get("run_no", 1))
    if run_no == 0:
        raise ValueError("run=0 is read-only; scene logs may only append to run>=1")

    record = {
        "run_no": run_no,
        "scene_id": entry.get("scene_id", ""),
        "location": entry.get("location", ""),
        "speaker": entry.get("speaker", ""),
        "cons": entry.get("cons"),
        "role": entry.get("role", ""),
        "content": entry.get("content", ""),
        "visible_to": list(entry.get("visible_to") or []),
        "created_runtime_props": list(entry.get("created_runtime_props") or []),
        "state_updates": entry.get("state_updates", {}),
        "ts": entry.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SCENE_LOG_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_scene_log(
    log_path: str | os.PathLike[str],
    run_no: int,
    scene_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Read recent scene log records for a run/scene."""
    path = Path(log_path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(row.get("run_no", -1)) != int(run_no):
                continue
            row_scene_id = row.get("scene_id")
            if row.get("role") == "__delete_scene__":
                if scene_id is None or row_scene_id == scene_id:
                    rows = [item for item in rows if item.get("scene_id") != row_scene_id]
                continue
            if scene_id and row_scene_id != scene_id:
                continue
            rows.append(row)
    return rows[-limit:]


def validate_director_output(
    output: dict[str, Any],
    scene_state: dict[str, Any],
    participant_contexts: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Validate a future LLM director JSON before accepting it."""
    errors: list[str] = []
    present = set(_present_cons(scene_state))

    narration = output.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        errors.append("E_NARRATION_EMPTY")

    speakers = output.get("speakers")
    if speakers is not None and not isinstance(speakers, list):
        errors.append("E_SPEAKERS_NOT_LIST")
        speakers = []
    elif speakers is None:
        speakers = []

    text_parts = [narration or ""]
    for idx, item in enumerate(speakers):
        if not isinstance(item, dict):
            errors.append(f"E_SPEAKER_{idx}_NOT_OBJECT")
            continue
        cons = item.get("cons")
        if cons not in present:
            errors.append(f"E_SPEAKER_{idx}_NOT_PRESENT:{cons}")
        dialogue = item.get("dialogue")
        stage = item.get("stage", "")
        if dialogue is not None and not isinstance(dialogue, str):
            errors.append(f"E_SPEAKER_{idx}_DIALOGUE_NOT_STRING")
        text_parts.extend([str(stage or ""), str(dialogue or "")])

    state_updates = output.get("state_updates", {})
    if state_updates is None:
        state_updates = {}
    if not isinstance(state_updates, dict):
        errors.append("E_STATE_UPDATES_NOT_OBJECT")
    else:
        for key in state_updates:
            if key not in ALLOWED_STATE_UPDATE_KEYS:
                errors.append(f"E_STATE_UPDATE_FIELD:{key}")

    full_text = "\n".join(text_parts)
    for cons, ctx in participant_contexts.items():
        for row in ctx.get("knowledge", {}).get("locked", []):
            statement = row.get("statement") or ""
            prop_id = row.get("prop_id") or ""
            if statement and statement in full_text:
                errors.append(f"E_LOCKED_TRUTH_TEXT:{cons}:{prop_id}")

    return not errors, errors


def build_scene_context(
    scene_id: str,
    scene_def: dict[str, Any],
    recent_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a scene context with hidden ch_anchor and UI-safe display fields."""
    present = scene_def.get("present_characters") or [
        {"cons": cons, "name": cons} for cons in scene_def.get("present", [])
    ]
    committed = []
    for log in (recent_log or []):
        updates = log.get("state_updates") or {}
        if isinstance(updates, dict):
            new_committed = updates.get("committed")
            if isinstance(new_committed, list):
                for item in new_committed:
                    if item not in committed:
                        committed.append(item)
            elif isinstance(new_committed, str) and new_committed:
                if new_committed not in committed:
                    committed.append(new_committed)

    context = {
        "scene_id": scene_id,
        "location": scene_def.get("location") or scene_def.get("place") or "未知地点",
        "scene_label": scene_def.get("scene_label") or "",
        "time_of_day": scene_def.get("time_of_day") or "",
        "current_beat": scene_def.get("current_beat") or scene_def.get("beat") or "",
        "canon_anchor": scene_def.get("canon_anchor") or scene_def.get("canon_src") or "",
        "present_characters": present,
        "dialogue_flow": scene_def.get("dialogue_flow", []),
        "recent_log": list(recent_log or []),
        "committed": committed,
        "runtime": {
            "ch_anchor": int(scene_def.get("ch_anchor") or scene_def.get("chapter") or 1),
            "worldline": scene_def.get("worldline", "WMAIN"),
            "run_no": int(scene_def.get("run_no", 1)),
        },
    }
    context["display"] = {
        "scene_id": scene_id,
        "location": context["location"],
        "scene_label": context["scene_label"],
        "time_of_day": context["time_of_day"],
        "current_beat": context["current_beat"],
        "present_names": [p.get("name") or p.get("cons") for p in present],
    }
    return context


def resolve_memory(
    cons: str,
    scene_context: dict[str, Any],
    db_path: str | os.PathLike[str] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Resolve origin/recent/sensory memory without inventing truth.

    合并读取静态 slow_memory（DB） + 动态记忆（run 态 JSON 的 dynamic_memory）。
    动态记忆按 run 过滤（三分支维度红线：不让二周目记忆漏到一周目）。
    """
    ch_anchor = scene_context["runtime"]["ch_anchor"]
    run_no = int(scene_context["runtime"].get("run_no", 1))
    persona = resolve_persona(cons, "stranger")
    origin_summary = _surface_summary(persona.get("text", ""))
    query = " ".join(
        [
            scene_context.get("location", ""),
            scene_context.get("current_beat", ""),
            " ".join(str(item.get("content", "")) for item in scene_context.get("recent_log", [])[-6:]),
        ]
    )

    sensory: list[dict[str, Any]] = []
    path = Path(db_path) if db_path else DEFAULT_DB

    def _static_memory_allowed(row: dict[str, Any]) -> bool:
        tag = str(_pick(row, ["emo_tag", "emotion", "tag"], "") or "").lower()
        if any(token in tag for token in ("future", "leak", "locked")):
            return False
        memory_ch = _pick(row, ["learn_ch", "ch_anchor", "ch_ref", "chapter"], None)
        if memory_ch is not None:
            try:
                if int(memory_ch) > int(ch_anchor):
                    return False
            except (TypeError, ValueError):
                pass
        return True

    if path.exists():
        try:
            db = sqlite3.connect(path)
            cur = db.cursor()
            cols = _table_cols(cur, "slow_memory")
            if "cons_id" in cols:
                rows = cur.execute("SELECT * FROM slow_memory WHERE cons_id=?", (cons,)).fetchall()
                for raw in rows:
                    row = dict(zip(cols, raw))
                    if not _static_memory_allowed(row):
                        continue
                    text = _pick(row, ["text", "content", "memory"])
                    anchor = _pick(row, ["anchor", "sensory_anchor"])
                    sensory.append(
                        {
                            "text": text,
                            "anchor": anchor,
                            "emo_tag": _pick(row, ["emo_tag", "emotion", "tag"]),
                            "salience": float(_pick(row, ["salience"], 0.5) or 0.5),
                            "score": _score(query, f"{anchor} {text}"),
                            "source": "static_db",
                        }
                    )
            db.close()
        except sqlite3.Error:
            sensory = []

    # ── 动态记忆：从 run 态 JSON 按 run_no 过滤读取 ──
    # 绕过 import 循环：延迟本地导入 SceneState
    dynamic_entries: list[dict[str, Any]] = []
    state_for_mention: Any = None
    try:
        from scene_state import SceneState

        state_for_mention = SceneState.load(run_no, scene_context.get("scene_id", ""))
        for entry in state_for_mention.dynamic_memory:
            # 按 run 过滤（三分支维度红线）
            if int(entry.get("run_no", -1)) > run_no:
                continue
            if entry.get("cons") != cons:
                continue
            # first_mention_only：已提及过的跳过
            if entry.get("first_mention_only") and entry.get("mentioned"):
                continue
            anchor_text = entry.get("anchor", "")
            salience_boost = float(entry.get("salience_boost") or 0.0)
            entry_sensory = {
                "text": entry.get("text", ""),
                "anchor": anchor_text,
                "emo_tag": entry.get("tag", "intervention_attempt"),
                "salience": 0.5 + salience_boost,  # 基线 + 写入时指定的提权
                "score": _score(query, f"{anchor_text} {entry.get('text', '')}"),
                "source": "dynamic_memory",
                "_is_first_mention": not entry.get("mentioned", False),
                # 使用说明：只有 dynamic_memory 有（静态 slow_memory 不需要额外说明）
                "_usage_hint": (
                    "这是本周目刚发生的事，如果贴合当前语境，可以自然地带一点这份记忆的痕迹——"
                    "比如态度松动了一点、语气没那么硬，但不要直接背诵这句话，"
                    "除非玩家追问或话题明确挨得上。"
                ),
            }
            dynamic_entries.append(entry_sensory)
            sensory.append(entry_sensory)
    except Exception:
        pass  # 缺 SceneState / state 文件不存在 → 静默跳过

    sensory.sort(key=lambda item: (item["score"], item["salience"]), reverse=True)

    # 标记已进入输出的动态记忆：first_mention_only 条目写 mentioned=True 并持久化
    if state_for_mention is not None:
        for item in sensory:
            if item.get("source") == "dynamic_memory" and item.get("_is_first_mention"):
                for entry in state_for_mention.dynamic_memory:
                    # 用 anchor+tag 定位（cons 已校验）
                    if (entry.get("anchor") == item.get("anchor")
                            and entry.get("tag") == item.get("emo_tag")
                            and not entry.get("mentioned", False)):
                        entry["mentioned"] = True
                break  # 只标记第一条，避免每回合都写
        try:
            state_for_mention.save()
        except Exception:
            pass
    knowledge = resolve_knowledge(cons, ch_anchor, path)
    opening_projection = load_opening_memory(cons, ch_anchor)
    return {
        "cons": cons,
        "origin_summary": opening_projection.get("surface_role") if opening_projection else origin_summary,
        "opening_projection": opening_projection,
        "lorebook_entries": select_lorebook_entries(opening_projection, ""),
        "recent_events": scene_context.get("recent_log", [])[-6:] or scene_context.get("dialogue_flow", [])[:4],
        "sensory_memories": sensory[:limit],
        "known_truths": knowledge.get("unlocked", []),
        "forbidden_truths": knowledge.get("locked", []),
        # 暴露给 compose_group_prompt，让旁白/提示知道这条记忆存在（不暴露具体文本）
        "_has_dynamic_memory": bool(dynamic_entries),
        "_dynamic_memory_cons": cons,
    }


def build_participant_context(
    cons: str,
    scene_context: dict[str, Any],
    db_path: str | os.PathLike[str] | None = None,
    relationship_stage: str = "stranger",
    voice_stage: str | None = None,
    schedules_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Build one NPC's scene-local context using that NPC's own gates."""
    ch_anchor = scene_context["runtime"]["ch_anchor"]
    safe_voice_stage = voice_stage or relationship_stage
    return {
        "cons": cons,
        "persona": resolve_persona(cons, relationship_stage),
        "knowledge": resolve_knowledge(cons, ch_anchor, db_path),
        "voice": resolve_voice(cons, (1, ch_anchor), safe_voice_stage, db_path),
        "memory": resolve_memory(cons, scene_context, db_path),
        "agent_state": build_agent_state(cons, scene_context, schedules_path),
    }


def _present_cons(scene_state: dict[str, Any]) -> list[str]:
    return [
        item.get("cons")
        for item in scene_state.get("present_characters", [])
        if isinstance(item, dict) and item.get("cons") and not item.get("cons").startswith("C.player")
    ]


def choose_speakers(
    scene_state: dict[str, Any],
    player_input: str | None = None,
    max_speakers: int = 2,
) -> list[dict[str, Any]]:
    """Deterministic fallback director: pick present NPCs only, with pauses."""
    present = _present_cons(scene_state)
    if not present:
        return []

    try:
        bidding = bid_turn_taking(scene_state, player_input, None, max_speakers=max_speakers)
        if player_input and player_input.strip() and bidding["speakers"]:
            return bidding["speakers"]
        if bidding["speakers"]:
            return [{"cons": item["cons"], "reason": "director_tick"} for item in bidding["speakers"]]
    except Exception:
        pass

    text = player_input or ""
    selected: list[str] = []
    for item in scene_state.get("present_characters", []):
        name = item.get("name", "")
        cons = item.get("cons")
        if cons and name and name in text:
            selected.append(cons)

    if not selected:
        if player_input and player_input.strip():
            normalized = re.sub(r"\s+", "", text)
            akito = "C.akito.WMAIN"
            kakashi = "C.kakashi.WMAIN"
            xiuzai = "C.xiuzai.WMAIN"
            if any(key in normalized for key in ("拍", "视频", "记录", "照片", "升旗")) and akito in present:
                selected = [akito]
            elif any(key in normalized for key in ("住哪", "住址", "住所", "落脚", "酒店", "旅馆", "去哪", "行程", "接下来", "之后")):
                selected = [cons for cons in (akito, kakashi) if cons in present]
            elif any(key in normalized for key in ("复活", "时间倒流", "杀", "绑架", "威胁")):
                selected = [cons for cons in (xiuzai, kakashi) if cons in present]
            else:
                seed = sum(ord(ch) for ch in f"{scene_state.get('scene_id', '')}:{normalized}")
                count = seed % (min(max_speakers, len(present)) + 1)
                selected = present[:count]
        else:
            flow = scene_state.get("dialogue_flow", [])
            for line in flow:
                speaker_name = line.get("speaker", "")
                for item in scene_state.get("present_characters", []):
                    if item.get("name") and item.get("name") in speaker_name:
                        selected.append(item["cons"])
                        break
                if selected:
                    break
            selected = selected or present[:1]

    deduped = []
    for cons in selected:
        if cons in present and cons not in deduped:
            deduped.append(cons)
    return [
        {
            "cons": cons,
            "reason": "player_addressed" if player_input else "director_tick",
        }
        for cons in deduped[:max_speakers]
    ]


def compose_group_prompt(
    scene_state: dict[str, Any],
    participant_contexts: dict[str, dict[str, Any]],
    player_input: str | None = None,
    speaker_plan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a group-scene prompt where player input is broadcast to all."""
    lines = [
        "# 场景旁白与 GM 任务",
        "你是当前场景的旁白与主持人。玩家说话或行动面向整个现场，所有在场 NPC 都能听见。",
        "若玩家发言或行动涉及打破第四面墙、AI/系统、正典设定等出戏元提问，你仅生成普通的现场环境/疑惑氛围旁白，绝不能实体化这些出戏概念或引导 NPC 承认第四面墙。",
        "你仅输出一段客观的旁白叙述（narration），描述当前环境变化、氛围或角色动作趋势；不要代写任何 NPC 的具体对话或台词。",
        "",
        f"地点: {scene_state.get('location')}",
        f"当前事件: {scene_state.get('current_beat')}",
        "在场: " + "、".join(f"{p.get('cons')}({p.get('name') or p.get('cons')})" for p in scene_state.get("present_characters", [])),
    ]
    committed = scene_state.get("committed") or []
    if committed:
        lines.append("已定事实（这是权威的已定或已发生的事情，不要重新讨论、提议或推销）:")
        for idx, fact in enumerate(committed):
            lines.append(f"  - {fact}")
    if player_input:
        import re
        thought_patterns = [r"\((.*?)\)", r"\[(.*?)\]", r"【(.*?)】"]
        thoughts = []
        remaining = player_input
        for pat in thought_patterns:
            found = re.findall(pat, remaining)
            if found:
                thoughts.extend(found)
                remaining = re.sub(pat, "", remaining)
        action_pattern = r"\*(.*?)\*"
        actions = re.findall(action_pattern, remaining)
        if actions:
            remaining = re.sub(action_pattern, "", remaining)
        
        speech = remaining.strip()
        action = " ".join(actions).strip()
        thought = " ".join(thoughts).strip()

        desc = []
        if action:
            desc.append(f"玩家做出动作: *{action}*")
        if speech:
            desc.append(f"玩家说: \"{speech}\"")
        if thought:
            desc.append(f"玩家心声 (仅旁白/导演可见，NPC听不见): (心理活动：{thought})")
        
        lines.append("玩家最新行动（全场能听到言语和看到动作，但NPC听不到玩家的心理活动）:\n" + "\n".join(f"  - {d}" for d in desc))
    else:
        lines.append("玩家暂未插话：请让现场按 NPC 自身状态自然推进。")

    if scene_state.get("recent_log"):
        lines.append("\n# 最近场景流")
        from scene_delta import parse_player_input_modalities
        for item in scene_state["recent_log"][-8:]:
            speaker = item.get("speaker", "主持人")
            content = item.get("content", "")
            if item.get("role") == "player":
                # Strip player thoughts from NPC prompts (L6)
                parsed = parse_player_input_modalities(content)
                parts = []
                if parsed.get("action"):
                    parts.append(f"*{parsed['action']}*")
                if parsed.get("speech"):
                    parts.append(parsed["speech"])
                content = " ".join(parts).strip()
                if not content:
                    continue
            lines.append(f"- {speaker}: {content}")

    lines.append("\n# 在场 NPC 上下文")
    speaker_cons = [item.get("cons") for item in speaker_plan or [] if item.get("cons")]
    for cons, ctx in participant_contexts.items():
        memory = ctx["memory"]
        lines.append(f"## {cons}")
        lines.append(f"表层来历: {memory.get('origin_summary') or '（缺）'}")
        projection = memory.get("opening_projection")
        if projection:
            lines.append(f"开场别名: {projection.get('public_alias', '（缺）')}")
            if projection.get("memory_scope"):
                lines.append(f"记忆边界: {projection.get('memory_scope')}")
            lines.append(f"刚从哪里来: {projection.get('from_where', '（缺）')}")
            lines.append(f"为什么在这里: {projection.get('why_here', '（缺）')}")
            lines.append(f"为什么会靠近玩家: {projection.get('why_approach_player', '（缺）')}")
            lines.append(f"此刻可见态度: {projection.get('visible_attitude', '（缺）')}")
            selected_lore = select_lorebook_entries(projection, player_input or "")
            always_lore = [item.get("text", "") for item in selected_lore["always"] if item.get("text")]
            keyed_lore = [item.get("text", "") for item in selected_lore["keyed"] if item.get("text")]
            if always_lore:
                lines.append("角色常驻事实: " + "；".join(always_lore[:6]))
            if keyed_lore:
                lines.append("本轮触发事实: " + "；".join(keyed_lore[:6]))
            events = projection.get("recent_canon_events") or []
            if events:
                lines.append("开场近因: " + "；".join(e.get("text", "") for e in events[:3] if isinstance(e, dict)))
            allowed = projection.get("allowed_prop_ids") or []
            forbidden = projection.get("forbidden_prop_ids") or []
            lines.append("开场允许命题ID: " + ("；".join(allowed[:8]) if allowed else "（无）"))
            lines.append("开场禁止命题ID: " + ("；".join(forbidden[:8]) if forbidden else "（无）"))
        known = memory.get("known_truths", [])
        locked = memory.get("forbidden_truths", [])
        lines.append("已解锁真相: " + ("；".join(k["statement"] for k in known[:5]) if known else "（无）"))
        lines.append("禁止流露命题ID: " + ("；".join(k["prop_id"] for k in locked[:8]) if locked else "（无）"))
        sensory = list(memory.get("sensory_memories", []) or [])
        lines.append("可用感官记忆: " + ("；".join(m["anchor"] for m in sensory if m.get("anchor")) if sensory else "（无）"))

    voice_contexts = {
        cons: build_npc_generation_context(cons, scene_state, participant_contexts[cons], player_input)
        for cons in (speaker_cons or list(participant_contexts.keys()))
        if cons in participant_contexts
    }
    lines.append("\n# B7 发声器上下文（每个 NPC 只能使用自己的材料）")
    if not voice_contexts:
        lines.append("本轮可留白：没有 NPC 必须接话。")
    for cons, voice_ctx in voice_contexts.items():
        lines.append(f"## 发声器 {cons}")
        lines.append("表层 persona: " + (voice_ctx["persona_surface"] or "（缺）"))
        voice_rules = [str(item) for item in (voice_ctx.get("voice_brief", {}).get("rules") or []) if item]
        if voice_rules:
            lines.append("VOICE_BRIEF: " + " | ".join(voice_rules[:5]))
        voice_lines = [q.get("text", "") for q in voice_ctx["voice_samples"] if q.get("text")]
        lines.append("语癖样本: " + ("；".join(voice_lines[:4]) if voice_lines else "（当前关系/章节无安全语癖样本）"))
        agenda = voice_ctx.get("agent_state", {}).get("short_term_agenda", {})
        if agenda.get("text"):
            lines.append("当前 agenda: " + agenda["text"])
        always = [item.get("text", "") for item in voice_ctx["lorebook"]["always"] if item.get("text")]
        keyed = [item.get("text", "") for item in voice_ctx["lorebook"]["keyed"] if item.get("text")]
        lines.append("常驻事实: " + ("；".join(always[:4]) if always else "（无）"))
        lines.append("本轮触发事实: " + ("；".join(keyed[:4]) if keyed else "（无）"))
        lines.append("禁止命题ID: " + ("；".join(pid for pid in voice_ctx["forbidden_prop_ids"] if pid) or "（无）"))

    lines.append(
        '\n# 输出协议\n返回 JSON: {"narration": "客观的场景旁白或转场叙述（可空）", "state_updates": {"committed": []}}'
    )
    prompt = "\n".join(lines)
    introduced = scene_state.get("introduced", {})
    prompt = anonymize_text(prompt, introduced)
    return {
        "prompt": prompt,
        "broadcast_input": player_input,
        "participants": list(participant_contexts.keys()),
        "speaker_voice_contexts": voice_contexts,
        "hidden_runtime": scene_state.get("runtime", {}),
    }


def check_duplicate_and_progress(
    new_messages: list[dict[str, Any]],
    recent_log: list[dict[str, Any]],
    committed_list: list[str],
    run_logs: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """
    B10 Anti-repeat gate.
    Filters out similar NPC dialogue (similarity >= 0.75) but never forces a
    scene transition. Cold scenes stay in-scene unless another rule exits them.
    If run_logs is provided, cross-scene deduplication checks are performed for sentences of length >= 8.
    """
    filtered = []
    force_transition = False
    exact_guard_roles = {"npc", "director", "overhear"}
    exact_seen_texts = {
        log.get("content", "").strip()
        for log in recent_log
        if log.get("role") in exact_guard_roles and log.get("content")
    }
    if run_logs is not None:
        for log in run_logs:
            if log.get("role") in exact_guard_roles and log.get("content"):
                exact_seen_texts.add(log.get("content", "").strip())

    recent_npc_texts = [
        log.get("content", "").strip()
        for log in recent_log[-8:]
        if log.get("role") == "npc" and log.get("content")
    ]
    near_window = recent_npc_texts[-4:]
    batch_exact_texts = []
    batch_npc_texts = []  # 同拍已收 NPC 文本，防同一回合内重复

    for msg in new_messages:
        if msg.get("role") in exact_guard_roles and msg.get("role") != "npc" and msg.get("content"):
            exact_content = msg["content"].strip()
            is_cross_dup = False
            if run_logs is not None and len(exact_content) >= 8:
                is_cross_dup = any(
                    _score(exact_content, log.get("content", "").strip()) >= 0.75
                    for log in run_logs
                    if log.get("role") == msg.get("role") and log.get("content")
                )
            if exact_content in exact_seen_texts or exact_content in batch_exact_texts or is_cross_dup:
                continue
            batch_exact_texts.append(exact_content)
        if msg.get("role") == "npc" and msg.get("content"):
            content = msg["content"].strip()
            dup_hits = sum(1 for old_text in near_window if _score(content, old_text) >= 0.75)
            if dup_hits >= 2:
                force_transition = True
            is_cross_dup = False
            if run_logs is not None and len(content) >= 8:
                is_cross_dup = any(
                    _score(content, log.get("content", "").strip()) >= 0.75
                    for log in run_logs
                    if log.get("role") == "npc" and log.get("content")
                )
            if content in exact_seen_texts or content in batch_exact_texts or is_cross_dup:
                continue
            batch_exact_texts.append(content)
            is_dup = any(_score(content, old_text) >= 0.75 for old_text in recent_npc_texts)
            is_batch_dup = any(_score(content, b) >= 0.75 for b in batch_npc_texts)
            if is_dup or is_batch_dup:
                continue
            batch_npc_texts.append(content)
        filtered.append(msg)

    return filtered, force_transition
