#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py —— C1 数字生命可视化 Web 控制台后端服务
零额外依赖，基于 Python 内置库构建。读取 world_truth.db 并导入 npc_test_client.py 逻辑。
"""
import sys
import os
import json
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import webbrowser
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Timer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 动态引入 npc_test_client.py（位于 ../runtime/）
DELIVERY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runtime"))
if DELIVERY_DIR not in sys.path:
    sys.path.append(DELIVERY_DIR)

try:
    from npc_test_client import NpcFSM, retrieve, assemble, leak_check, knowledge
except ImportError as e:
    print(f"[ERROR] 无法从 {DELIVERY_DIR} 导入 npc_test_client.py，请确认该文件夹及文件存在。原因为: {e}")
    sys.exit(1)

from file_locks import CONFIG_LOCK, SESSION_FILE_LOCK
from runtime.runtime_state import load_run_bonds

try:
    from prompt_pipeline import (
        compose as compose_pipeline,
        resolve_knowledge,
        resolve_persona,
        resolve_scene,
        resolve_voice,
    )
except ImportError as e:
    print(f"[ERROR] 无法从 {DELIVERY_DIR} 导入 prompt_pipeline.py，请确认已完成数字人 pipeline。原因为: {e}")
    sys.exit(1)

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "world_truth.db"))
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
EXPERIMENT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_experiment.json")
CONTRACTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "contracts"))
LEDGER_PATH   = os.path.join(os.path.dirname(__file__), "delta_ledger.json")
FREE_STAGE_SESSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "artifacts", "free_stage_sessions"))
ANCHOR_POINTS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runtime", "anchor_points.json"))
DEFAULT_API_URL = "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
DEFAULT_CONFIG = {
    "api_key": "",
    "api_url": DEFAULT_API_URL,
    "model": "deepseek-v4-flash",
    "chat_request_options": {"thinking": {"type": "disabled"}},
}
# IGNORE_CLIENT_API_URL: outbound LLM calls never honor client-supplied api_url.
IGNORE_CLIENT_API_URL = True


def load_approved_openings():
    """Load server-controlled playable openings; never accept client card paths."""
    with open(ANCHOR_POINTS_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    openings = payload.get("openings", [])
    if not isinstance(openings, list):
        raise ValueError("anchor_points.openings must be a list")
    return [item for item in openings if isinstance(item, dict) and item.get("id")]


def public_openings():
    public = []
    for item in load_approved_openings():
        public.append({
            "id": item.get("id"),
            "line": item.get("line", ""),
            "label": item.get("label", ""),
            "scene": item.get("scene", ""),
            "description": item.get("description", ""),
            "player_templates": [dict(t) for t in item.get("player_templates", []) if isinstance(t, dict)],
        })
    return public


THIN_PLAYER_PROFILE_KEYS = (
    "name",
    "gender",
    "age_band",
    "occupation",
    "skill_hook",
)


def _merge_thin_player_profile(base_profile, overlay):
    merged = dict(base_profile or {})
    if not isinstance(overlay, dict):
        return merged
    for key in THIN_PLAYER_PROFILE_KEYS:
        raw = overlay.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            merged.pop(key, None)
            continue
        limit = 40 if key in {"name", "gender", "age_band", "occupation"} else 80
        merged[key] = value[:limit]
    return merged


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            if isinstance(file_cfg, dict):
                cfg.update({k: v for k, v in file_cfg.items() if v is not None})
        except Exception as e:
            print(f"[warn] 读取 config.json 失败: {e}")
    env_key = os.environ.get("C1_API_KEY", "").strip()
    if env_key:
        cfg["api_key"] = env_key
    if not str(cfg.get("api_url", "")).strip():
        cfg["api_url"] = DEFAULT_API_URL
    return cfg


def resolve_llm_config(base_cfg, req_data=None):
    """Merge safe display overrides; never accept client api_url or model swap."""
    cfg = dict(base_cfg or DEFAULT_CONFIG)
    # Live play is pinned to server config (Volc Coding Plan). Client may not
    # switch provider/model; only empty request fields are ignored.
    cfg["api_url"] = str(cfg.get("api_url") or DEFAULT_API_URL).strip() or DEFAULT_API_URL
    if not str(cfg.get("model") or "").strip():
        cfg["model"] = DEFAULT_CONFIG["model"]
    if not isinstance(cfg.get("chat_request_options"), dict):
        cfg["chat_request_options"] = dict(DEFAULT_CONFIG["chat_request_options"])
    return cfg

def load_free_stage_config():
    try:
        from free_stage_prototype import load_config as load_runtime_free_stage_config
        cfg, _source = load_runtime_free_stage_config()
        return cfg
    except Exception:
        cfg = load_config()
        if os.path.exists(EXPERIMENT_CONFIG_PATH):
            try:
                with open(EXPERIMENT_CONFIG_PATH, "r", encoding="utf-8") as f:
                    exp_cfg = json.load(f)
                merged = dict(cfg)
                merged.update({k: v for k, v in exp_cfg.items() if v not in ("", None)})
                return merged
            except Exception as e:
                print(f"[warn] 读取 config_experiment.json 失败: {e}")
        return cfg

def save_config(config_data):
    try:
        with CONFIG_LOCK:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[warn] 保存 config.json 失败: {e}")

def handle_free_stage_request(req_data, config, state_dir=None, caller=None, truth_db=None):
    def redact_sensitive_director_fields(data):
        if isinstance(data, dict):
            cleaned = {}
            for k, v in data.items():
                if k in {"director_note", "director_plan"}:
                    continue
                cleaned[k] = redact_sensitive_director_fields(v)
            return cleaned
        elif isinstance(data, list):
            res_lst = []
            for item in data:
                if isinstance(item, dict) and item.get("role") == "director_note":
                    continue
                res_lst.append(redact_sensitive_director_fields(item))
            return res_lst
        return data

    res = _handle_free_stage_request_raw(req_data, config, state_dir, caller, truth_db=truth_db)
    return redact_sensitive_director_fields(res)

def _handle_free_stage_request_raw(req_data, config, state_dir=None, caller=None, truth_db=None):
    try:
        from free_stage_prototype import FreeStageSession, _safe_session_id
    except ImportError as e:
        raise RuntimeError(f"free_stage prototype unavailable: {e}") from e

    op = req_data.get("op") or "player_say"
    s_dir = state_dir or FREE_STAGE_SESSION_DIR

    if op == "list_sessions":
        import glob
        import time
        os.makedirs(s_dir, exist_ok=True)
        files = glob.glob(os.path.join(s_dir, "*.json"))
        sessions = []
        for filepath in files:
            filename = os.path.basename(filepath)
            sid = os.path.splitext(filename)[0]
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                card_path = data.get("card_path", "")
                from free_stage_prototype import resolve_card_path, load_card
                try:
                    path = resolve_card_path(card_path)
                    card = load_card(path)
                    scene = card.get("scene", "未知场景")
                except Exception:
                    scene = "未知场景"
                
                mtime = os.path.getmtime(filepath)
                last_played_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
                sessions.append({
                    "session_id": sid,
                    "current_scene": scene,
                    "turns": len(data.get("history", [])),
                    "last_played_time": last_played_time,
                    "ended": bool(data.get("ended", False))
                })
            except Exception:
                continue
        # Sort by mtime descending
        sessions.sort(key=lambda x: x["last_played_time"], reverse=True)
        return {"status": "ok", "sessions": sessions}

    if op == "list_openings":
        try:
            return {"status": "ok", "openings": public_openings()}
        except Exception as e:
            return {"status": "error", "error": f"opening catalog unavailable: {str(e)}"}

    if op == "save_as":
        src_id = _safe_session_id(req_data.get("session_id"))
        tgt_id = _safe_session_id(req_data.get("target_session_id"))
        src_file = os.path.join(s_dir, f"{src_id}.json")
        tgt_file = os.path.join(s_dir, f"{tgt_id}.json")
        if not os.path.exists(src_file):
            return {"status": "error", "error": f"source session {src_id} not found"}
        import shutil
        try:
            with SESSION_FILE_LOCK:
                shutil.copyfile(src_file, tgt_file)
                with open(tgt_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["session_id"] = tgt_id
                with open(tgt_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            return {"status": "ok", "session_id": tgt_id}
        except Exception as e:
            return {"status": "error", "error": f"save_as failed: {str(e)}"}

    if op == "delete_session":
        sid = _safe_session_id(req_data.get("target_session_id") or req_data.get("session_id"))
        filepath = os.path.join(s_dir, f"{sid}.json")
        with SESSION_FILE_LOCK:
            exists = os.path.exists(filepath)
            if exists:
                os.remove(filepath)
        if exists:
            return {"status": "ok"}
        else:
            return {"status": "error", "error": f"session {sid} not found"}

    session_id = _safe_session_id(req_data.get("session_id") or "web-default")
    if op == "create_session":
        opening_id = str(req_data.get("opening_id") or "").strip()
        player_template_id = str(req_data.get("player_template_id") or "").strip()
        openings = {str(item.get("id")): item for item in load_approved_openings()}
        opening = openings.get(opening_id)
        if not opening:
            return {"status": "error", "error": f"unknown opening_id: {opening_id}"}
        templates = {
            str(item.get("id")): item
            for item in opening.get("player_templates", [])
            if isinstance(item, dict)
        }
        player_profile = templates.get(player_template_id)
        if not player_profile:
            return {
                "status": "error",
                "error": f"player template {player_template_id} is not approved for {opening_id}",
            }
        player_profile = _merge_thin_player_profile(
            player_profile,
            req_data.get("player_profile_overlay"),
        )
        os.makedirs(s_dir, exist_ok=True)
        state_path = os.path.join(s_dir, f"{session_id}.json")
        if os.path.exists(state_path):
            return {"status": "error", "error": f"session {session_id} already exists"}
        from free_stage_prototype import resolve_card_path
        from runtime.run_registry import open_run, profile_hash
        selected_card_path = resolve_card_path(opening.get("card_path", ""))
        run_row = open_run(
            Path(truth_db) if truth_db else DB_PATH,
            opening_id=opening_id,
            player_line=str(player_profile.get("id") or "a_qi"),
            player_profile_hash=profile_hash(player_profile),
        )
        session = FreeStageSession(
            session_id=session_id,
            state_dir=s_dir,
            card_path=selected_card_path,
            config=config,
            caller=caller,
            opening_id=opening_id,
            player_profile=player_profile,
            pending_entry=None,
            autosave=False,
            load_existing=False,
            run_no=int(run_row["run"]),
            truth_db=Path(truth_db) if truth_db else DB_PATH,
        )
        payload = session._state_payload()
        try:
            with SESSION_FILE_LOCK:
                fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        fd = -1
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                finally:
                    if fd >= 0:
                        os.close(fd)
        except FileExistsError:
            return {"status": "error", "error": f"session {session_id} already exists"}
        except Exception:
            with SESSION_FILE_LOCK:
                if os.path.exists(state_path):
                    os.remove(state_path)
            raise
        session.autosave = True
        return {
            "status": "ok",
            "session_id": session.session_id,
            "run_no": int(session.run_no),
            "turns": [],
            "completed": session.completed,
            "issues": [],
            "ended": False,
            "surface": session.surface(),
            "pacing": session.card.get("pacing", "standard"),
            "opening_id": getattr(session, "opening_id", ""),
            "player_profile": session.surface().get("player_profile", {}),
        }
    if op == "get_bond_archive":
        filepath = os.path.join(s_dir, f"{session_id}.json")
        card_history = []
        consolidated = {}
        branch_progress = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                card_history = s_data.get("card_history", [])
                consolidated = s_data.get("consolidated_memory_by_card", {})
                branch_progress = s_data.get("branch_progress", [])
            except Exception:
                pass

        visited_scenes = []
        for ch in card_history:
            card_p = ch
            if "tiananmen" in card_p:
                visited_scenes.append("天安门升旗广场")
            elif "aquarium" in card_p:
                visited_scenes.append("北京海洋馆水母区")
            elif "dolphin" in card_p:
                visited_scenes.append("海洋馆人豚共舞区")
            elif "highway" in card_p:
                visited_scenes.append("京津高速")

        visited_scenes = list(dict.fromkeys(visited_scenes))
        if not visited_scenes:
            visited_scenes = ["北京旅程起步"]

        has_highway = any("highway" in ch for ch in card_history)
        has_aquarium = any("aquarium" in ch or "dolphin" in ch for ch in card_history)

        if has_highway:
            akito_rel = "生死盟友"
            xiuzai_rel = "患难搭档"
            kakashi_rel = "生死之交"
        elif has_aquarium:
            akito_rel = "熟络旅伴"
            xiuzai_rel = "投缘同伴"
            kakashi_rel = "同行之人"
        else:
            akito_rel = "萍水相逢"
            xiuzai_rel = "萍水相逢"
            kakashi_rel = "萍水相逢"

        timeline = []
        for card_p, mem in consolidated.items():
            s_mems = mem.get("structured_memories", {})
            if not s_mems:
                continue
            scene_name = mem.get("source_scene") or "上一场"
            timeline.append({
                "scene": scene_name,
                "memories": {
                    "akito": {
                        "summary": s_mems.get("akito", {}).get("summary", ""),
                        "mood": s_mems.get("akito", {}).get("mood", ""),
                        "relation": s_mems.get("akito", {}).get("relation", ""),
                        "unresolved": s_mems.get("akito", {}).get("unresolved", "")
                    },
                    "xiuzai": {
                        "summary": s_mems.get("xiuzai", {}).get("summary", ""),
                        "mood": s_mems.get("xiuzai", {}).get("mood", ""),
                        "relation": s_mems.get("xiuzai", {}).get("relation", ""),
                        "unresolved": s_mems.get("xiuzai", {}).get("unresolved", "")
                    },
                    "kakashi": {
                        "summary": s_mems.get("kakashi", {}).get("summary", ""),
                        "mood": s_mems.get("kakashi", {}).get("mood", ""),
                        "relation": s_mems.get("kakashi", {}).get("relation", ""),
                        "unresolved": s_mems.get("kakashi", {}).get("unresolved", "")
                    }
                }
            })

        akito_mood = "平静"
        xiuzai_mood = "散漫"
        kakashi_mood = "平静"
        for card_p, mem in reversed(list(consolidated.items())):
            s_mems = mem.get("structured_memories", {})
            if s_mems:
                akito_mood = s_mems.get("akito", {}).get("mood", akito_mood)
                xiuzai_mood = s_mems.get("xiuzai", {}).get("mood", xiuzai_mood)
                kakashi_mood = s_mems.get("kakashi", {}).get("mood", kakashi_mood)
                break

        # 汇总跨周目历史羁绊数据
        history_bonds = []
        try:
            truth_db = Path(DB_PATH)
            history_bonds = load_run_bonds(
                truth_db.with_name("runtime_state.db"), legacy_db_path=truth_db
            )
        except Exception as e:
            print(f"[warn] 读取运行态羁绊失败: {e}")

        kakashi_save_count = sum(1 for item in history_bonds if item[1] == "kakashi" and item[2] == "choiceA_brace")
        xiuzai_warn_count = sum(1 for item in history_bonds if item[1] == "xiuzai" and item[2] == "B1_dog")
        akito_join_count = sum(1 for item in history_bonds if item[1] == "akito" and item[2] == "bp_invited")

        branch_achievements = []
        # 1. 跨周目徽章
        if kakashi_save_count > 0:
            branch_achievements.append({
                "character": "kakashi",
                "scene": "因果守护",
                "text": f"【跨周目晴明守护徽章】晴明的守护者：在历史的无数次轮回中，你已累计扑救守护了晴明 {kakashi_save_count} 次。这一抹温存，正静静流淌在因果之外。"
            })
        if xiuzai_warn_count > 0:
            branch_achievements.append({
                "character": "xiuzai",
                "scene": "因果示警",
                "text": f"【跨周目修哉结绊徽章】敏锐的先知：在历史的所有周目中，你已累计向修哉提前示警了 {xiuzai_warn_count} 次危机。因果的轮转磨灭不掉你的敏锐。"
            })

        # 2. 当前周目细节成就
        if "choiceA_brace" in branch_progress:
            branch_achievements.append({
                "character": "kakashi",
                "scene": "京津高速",
                "text": "生死瞬间：你在大货车逆行撞击的千钧一发之际，奋不顾身扑向晴明挡在身前，彻底撼动了他的心防。"
            })
        if "B1_dog" in branch_progress:
            branch_achievements.append({
                "character": "xiuzai",
                "scene": "京津高速",
                "text": "心有灵犀：你提前示警了窜出的黑狗，避免了最初步的打滑，让修哉对你的机警有了全新认识。"
            })
        if "bp_invited" in branch_progress:
            branch_achievements.append({
                "character": "akito",
                "scene": "天安门广场",
                "text": "欣然结伴：你接受了秋人的同行邀请，与他们共赴北京海洋馆，正式加入了这场旅程。"
            })

        return {
            "status": "ok",
            "visited_scenes": visited_scenes,
            "bonds": {
                "akito": {
                    "name": "川口秋人",
                    "relation": akito_rel,
                    "mood": akito_mood,
                    "desc": "眼神里闪烁着清澈的理想主义，是一个诚恳、容易被看透的青年。"
                },
                "xiuzai": {
                    "name": "折原修哉",
                    "relation": xiuzai_rel,
                    "mood": xiuzai_mood,
                    "desc": "散漫的黑客，看似对一切都不在乎，实则暗藏自责与敏锐的直觉。"
                },
                "kakashi": {
                    "name": "坂本晴明",
                    "relation": kakashi_rel,
                    "mood": kakashi_mood,
                    "desc": "带着温润的声线，温和的防备后是不曾对人袒露的往昔。"
                }
            },
            "timeline": timeline,
            "branch_achievements": branch_achievements,
            "history_save_counts": {
                "kakashi": kakashi_save_count,
                "xiuzai": xiuzai_warn_count,
                "akito": akito_join_count
            }
        }

    session = FreeStageSession(
        session_id=session_id,
        state_dir=s_dir,
        config=config,
        caller=caller,
        truth_db=Path(truth_db) if truth_db else DB_PATH,
    )
    if op == "reset":
        session.reset()
        card_pacing = getattr(session, "card", {}).get("pacing", "standard") if hasattr(session, "card") else "standard"
        return {
            "status": "ok",
            "session_id": session.session_id,
            "turns": [],
            "completed": session.completed,
            "issues": [],
            "ended": False,
            "surface": session.surface(),
            "pacing": card_pacing,
            "opening_id": getattr(session, "opening_id", ""),
            "player_profile": session.surface().get("player_profile", {}),
        }
    if op == "start":
        turns = session.start() if hasattr(session, "start") else []
        card_pacing = getattr(session, "card", {}).get("pacing", "standard") if hasattr(session, "card") else "standard"
        res_data = {
            "status": "ok",
            "session_id": session.session_id,
            "run_no": int(getattr(session, "run_no", 1) or 1),
            "turns": turns,
            "completed": session.completed,
            "issues": session.last_issues,
            "ended": session.ended,
            "surface": session.surface(),
            "pacing": card_pacing,
            "opening_id": getattr(session, "opening_id", ""),
            "player_profile": session.surface().get("player_profile", {}),
            "stream": session._stream_status_payload() if hasattr(session, "_stream_status_payload") else {},
        }
        if req_data.get("debug"):
            res_data["debug_history"] = session.debug_history
            res_data["history"] = session.history
            if hasattr(session, "initial_debug_payload"):
                res_data["initial_debug_payload"] = session.initial_debug_payload()
        return res_data
    if op == "skip_scene":
        result = session.skip_scene(caller=caller)
        card_pacing = getattr(session, "card", {}).get("pacing", "standard") if hasattr(session, "card") else "standard"
        result["status"] = "ok"
        result["pacing"] = card_pacing
        return result
    if op == "stream_hold":
        hold = bool(req_data.get("hold", True))
        result = session.set_stream_hold(hold)
        result["status"] = "ok"
        return result
    if op == "advance_utterance":
        result = session.advance_utterance()
        result["status"] = "ok"
        return result
    if op != "player_say":
        return {"status": "error", "error": f"unknown free_stage op: {op}"}
    player_input = req_data.get("player_input")
    if player_input is None:
        player_input = req_data.get("text", "")
    result = session.step(player_input, debug=bool(req_data.get("debug")))
    card_pacing = getattr(session, "card", {}).get("pacing", "standard") if hasattr(session, "card") else "standard"
    result["status"] = "ok"
    result["pacing"] = card_pacing
    result["opening_id"] = getattr(session, "opening_id", "")
    result["player_profile"] = session.surface().get("player_profile", {})
    return result

class ConsoleHTTPRequestHandler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        self.path = urllib.parse.urlparse(self.path).path
        # 静态文件托管
        if self.path in ('/', '/index.html'):
            index_path = os.path.join(os.path.dirname(__file__), "index.html")
            if os.path.exists(index_path):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                with open(index_path, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            else:
                self.send_error(404, "index.html not found")
            return

        # 新玩家前端（沉浸式叙事舱）
        elif self.path in ('/player', '/player.html'):
            player_path = os.path.join(os.path.dirname(__file__), "player.html")
            if os.path.exists(player_path):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                with open(player_path, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            else:
                self.send_error(404, "player.html not found")
            return
        # 调试观测台前端
        elif self.path in ('/observer', '/observer.html'):
            observer_path = os.path.join(os.path.dirname(__file__), "observer.html")
            if os.path.exists(observer_path):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                # 观测台常改 UI 解码：禁止浏览器把旧版 JS 粘住「回执又没了」
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_cors_headers()
                self.end_headers()
                with open(observer_path, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            else:
                self.send_error(404, "observer.html not found")
            return
        # 获取意识体列表
        elif self.path == '/api/consciousness':
            try:
                db = sqlite3.connect(DB_PATH)
                cur = db.cursor()
                # 检查 consciousnesses 表是否存在并读取数据
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='consciousnesses'")
                if not cur.fetchone():
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps([]).encode('utf-8'))
                    db.close()
                    return

                # 读取列名
                cur.execute("PRAGMA table_info(consciousnesses)")
                cols = [r[1] for r in cur.fetchall()]
                cur.execute("SELECT * FROM consciousnesses")
                rows = cur.fetchall()
                data = []
                for r in rows:
                    row_dict = dict(zip(cols, r))
                    data.append({
                        "cons_id": row_dict.get("cons_id", ""),
                        "description": row_dict.get("description", row_dict.get("note", row_dict.get("desc", ""))),
                        "note": row_dict.get("note", "")
                    })
                db.close()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error_json(500, f"Database error: {str(e)}")
            return

        # 获取配置信息（不包含完整key以防泄漏，只传前 4 位和后 4 位，或者只返回有无）
        elif self.path == '/api/config':
            cfg = load_config()
            has_key = bool(cfg.get("api_key", "").strip())
            masked_key = ""
            if has_key:
                k = cfg["api_key"].strip()
                if len(k) > 10:
                    masked_key = k[:6] + "..." + k[-4:]
                else:
                    masked_key = "******"

            from scene_api import _get_git_short_sha
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "build_version": _get_git_short_sha(),
                "api_url": cfg.get("api_url", ""),
                "model": cfg.get("model", ""),
                "has_key": has_key,
                "masked_key": masked_key
            }, ensure_ascii=False).encode('utf-8'))
            return

        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        try:
            req_data = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            self.send_error_json(400, f"Invalid JSON payload: {str(e)}")
            return

        # P0/P1b 垂直切片端点转发
        if self.path in ('/api/intent', '/api/adjudicate', '/api/ledger'):
            try:
                from p0_endpoints import handle as p0_handle
                res = p0_handle(self.path, req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH)
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"P0 endpoint failed: {str(e)}")
            return
        elif self.path == '/api/tianjin':
            try:
                from p1b_tianjin import handle as tj_handle
                res = tj_handle(req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH)
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"Tianjin endpoint failed: {str(e)}")
            return
        elif self.path == '/api/director':
            try:
                from director import handle as dir_handle
                res = dir_handle(req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH, load_config())
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"Director failed: {str(e)}")
            return
        elif self.path == '/api/runtime_gate':
            try:
                from runtime_gate import handle as rg_handle
                res = rg_handle(req_data, DB_PATH)
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"Runtime gate failed: {str(e)}")
            return
        elif self.path == '/api/world_tick':
            try:
                from world_sim import handle as ws_handle
                res = ws_handle(req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH, load_config())
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"world_tick failed: {str(e)}")
            return
        elif self.path == '/api/opening':
            try:
                from opening_hub import handle as op_handle
                res = op_handle(req_data, DB_PATH, LEDGER_PATH, load_config())
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"opening failed: {str(e)}")
            return
        elif self.path == '/api/scene':
            try:
                from scene_api import handle as scene_handle
                res = scene_handle(req_data, DB_PATH, load_config())
                self.send_response_json(res)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_error_json(500, f"scene failed: {str(e)}")
            return
        elif self.path == '/api/free_stage':
            try:
                cfg = resolve_llm_config(load_free_stage_config(), req_data)
                res = handle_free_stage_request(req_data, cfg)
                self.send_response_json(res)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_error_json(500, f"free_stage failed: {str(e)}")
            return

        # 1. 状态机运算
        if self.path == '/api/fsm':
            try:
                trust = int(req_data.get('trust', 55))
                intimacy = int(req_data.get('intimacy', 30))
                alert = int(req_data.get('alert', 20))
                state = req_data.get('state', 'open')
                violations = int(req_data.get('violations', 0))

                d_trust = int(req_data.get('d_trust', 0))
                d_int = int(req_data.get('d_int', 0))
                d_alert = int(req_data.get('d_alert', 0))
                violation = bool(req_data.get('violation', False))

                # 实例化
                fsm = NpcFSM(trust=trust, intimacy=intimacy, alert=alert, state=state)
                fsm.violations = violations

                # 应用跃迁
                new_state = fsm.apply(d_trust=d_trust, d_int=d_int, d_alert=d_alert, violation=violation)

                res = {
                    "trust": fsm.trust,
                    "intimacy": fsm.intimacy,
                    "alert": fsm.alert,
                    "state": fsm.state,
                    "violations": fsm.violations
                }
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"FSM Transition logic failed: {str(e)}")
            return

        # 2. 慢环检索
        elif self.path == '/api/retrieve':
            try:
                cons = req_data.get('cons')
                query = req_data.get('query', '')
                emo = req_data.get('emo', '')

                if not cons:
                    self.send_error_json(400, "Missing parameter 'cons'")
                    return

                db = sqlite3.connect(DB_PATH)
                cur = db.cursor()
                # 调用 retrieve
                anchors = retrieve(cur, cons, query, emo, top=2, verbose=False)
                db.close()

                # 序列化结果
                self.send_response_json(anchors)
            except Exception as e:
                self.send_error_json(500, f"Retrieve failed: {str(e)}")
            return

        # 3. System Prompt 拼装
        elif self.path == '/api/prompt':
            try:
                cons = req_data.get('cons')
                ch = int(req_data.get('ch', 40))
                trust = int(req_data.get('trust', 55))
                intimacy = int(req_data.get('intimacy', 30))
                alert = int(req_data.get('alert', 20))
                state = req_data.get('state', 'open')
                violations = int(req_data.get('violations', 0))
                anchors = req_data.get('anchors', [])

                if not cons:
                    self.send_error_json(400, "Missing parameter 'cons'")
                    return

                db = sqlite3.connect(DB_PATH)
                cur = db.cursor()

                # 如果是天津，重定向获取卡卡西的 prompt 装配和命题作为基准
                cons_query = "C.kakashi.WMAIN" if cons == "TIANJIN" else cons

                fsm = NpcFSM(trust=trust, intimacy=intimacy, alert=alert, state=state)
                fsm.violations = violations
                prompt_text = assemble(cur, cons_query, ch, fsm, anchors)

                # 读取已解锁与未解锁的命题
                try:
                    from runtime_gate import gate_snapshot as rg_snapshot
                    run_no = int(req_data.get('run_no', 1))
                    snap = rg_snapshot(run_no, cons_query, ch, DB_PATH)
                    unlocked = [{"prop_id": r[0], "statement": r[1]} for r in snap["effective_unlocked"]]
                    locked = [{"prop_id": r[0], "statement": r[1]} for r in snap["effective_locked"]]
                except Exception:
                    unlocked_raw, locked_raw = knowledge(cur, cons_query, ch)
                    unlocked = [{"prop_id": r[0], "statement": r[1]} for r in unlocked_raw]
                    locked = [{"prop_id": r[0], "statement": r[1]} for r in locked_raw]

                # 读取客观真值事件线 events (根据目击者过滤)
                cur.execute("SELECT event_id, wl_id, t_game, ch_anchor, location_id, etype, payload FROM events ORDER BY ch_anchor, t_game")
                events_raw = cur.fetchall()
                events_list = []

                # 确定过滤关键字
                cons_name = cons_query.split(".")[1] if "." in cons_query else cons_query

                for r in events_raw:
                    eid, wl_id, t_game, ch_anchor, loc_id, etype, payload_str = r
                    try:
                        payload = json.loads(payload_str)
                    except Exception:
                        payload = {}

                    witnesses = payload.get("witnesses", [])
                    action_text = payload.get("action", "")

                    # 匹配目击者、提及角色或地标
                    is_relevant = False
                    if cons == "TIANJIN":
                        if ch_anchor == 85 or (loc_id and "天津" in loc_id):
                            is_relevant = True
                    else:
                        if any(w == cons_query for w in witnesses):
                            is_relevant = True
                        elif cons_name in action_text or "修哉" in action_text: # 对修哉特别放宽以便切片展示完整
                            is_relevant = True

                    if is_relevant:
                        events_list.append({
                            "event_id": eid,
                            "ch_anchor": ch_anchor,
                            "t_game": t_game,
                            "location_id": loc_id,
                            "action": action_text,
                            "canon_src": payload.get("canon_src", f"Ch.{ch_anchor}")
                        })

                db.close()

                self.send_response_json({
                    "prompt": prompt_text,
                    "unlocked": unlocked,
                    "locked": locked,
                    "events": events_list
                })
            except Exception as e:
                self.send_error_json(500, f"Assemble Prompt failed: {str(e)}")
            return

        # 4. 配置修改
        elif self.path == '/api/config/update':
            try:
                api_key = req_data.get('api_key')
                model = req_data.get('model')

                cfg = load_config()
                if api_key is not None:
                    cfg["api_key"] = api_key
                if model is not None:
                    cfg["model"] = model

                save_config(cfg)

                # 返回部分掩码的配置信息
                has_key = bool(cfg.get("api_key", "").strip())
                masked_key = ""
                if has_key:
                    k = cfg["api_key"].strip()
                    if len(k) > 10:
                        masked_key = k[:6] + "..." + k[-4:]
                    else:
                        masked_key = "******"

                self.send_response_json({
                    "success": True,
                    "api_url": cfg.get("api_url", ""),
                    "model": cfg.get("model", ""),
                    "has_key": has_key,
                    "masked_key": masked_key
                })
            except Exception as e:
                self.send_error_json(500, f"Update config failed: {str(e)}")
            return

        # 5. 聊天对话（大模型代理）及知识门控泄漏检测
        elif self.path == '/api/chat':
            try:
                cons = req_data.get('cons')
                ch = int(req_data.get('ch', 40))
                trust = int(req_data.get('trust', 55))
                intimacy = int(req_data.get('intimacy', 30))
                alert = int(req_data.get('alert', 20))
                state = req_data.get('state', 'open')
                violations = int(req_data.get('violations', 0))
                anchors = req_data.get('anchors', [])

                user_input = req_data.get('user_input', '')
                history = req_data.get('history', [])  # list of {"role": "user"/"assistant", "content": "..."}

                front_key = req_data.get('api_key', '').strip()

                if not cons:
                    self.send_error_json(400, "Missing parameter 'cons'")
                    return

                cfg = resolve_llm_config(load_config(), req_data)
                api_key = front_key if front_key else cfg.get("api_key", "").strip()
                api_url = cfg.get("api_url", "").strip()
                model = cfg.get("model", "").strip()

                if not api_key:
                    self.send_error_json(401, "API Key is missing. Please configure it in Settings or config.json.")
                    return

                # 1. 组装 System Prompt
                fsm = NpcFSM(trust=trust, intimacy=intimacy, alert=alert, state=state)
                fsm.violations = violations

                db = sqlite3.connect(DB_PATH)
                cur = db.cursor()
                scene_config = req_data.get('scene_config')
                prompt_debug = {
                    "pipeline": "legacy_assemble",
                    "sections": []
                }
                if isinstance(scene_config, dict) and scene_config:
                    relationship_stage = scene_config.get("player_stage") or scene_config.get("relationship_stage") or "stranger"
                    persona_part = resolve_persona(cons, relationship_stage)
                    knowledge_part = resolve_knowledge(cons, ch, DB_PATH)
                    voice_part = resolve_voice(cons, (ch, ch), relationship_stage, DB_PATH)
                    scene_part = resolve_scene(scene_config)
                    composed = compose_pipeline(persona_part, knowledge_part, voice_part, scene_part, fsm, anchors)
                    sys_prompt = composed["system_prompt"]
                    prompt_debug = {
                        "pipeline": "prompt_pipeline",
                        "relationship_stage": relationship_stage,
                        "sections": [s.get("name") for s in composed.get("sections", [])],
                        "persona_layers": persona_part.get("layers", []),
                        "unlocked_count": len(knowledge_part.get("unlocked", [])),
                        "locked_count": len(knowledge_part.get("locked", [])),
                        "voice_count": len(voice_part.get("quotes", [])),
                    }
                else:
                    sys_prompt = assemble(cur, cons, ch, fsm, anchors)

                    # 追加当前开场的即时情境与伪装背景约束 (legacy fallback)
                    place = req_data.get('place', '').strip()
                    situation = req_data.get('situation', '').strip()
                    if situation:
                        sys_prompt += (
                            f"\n\n## 1c. 当前即时场景与近期来历 (Situation & Background)\n"
                            f"- 地点: {place if place else '未知地点'}\n"
                            f"- 当前正在发生的事: {situation}\n"
                            f"- 你的近期来历状态: 你在这一章刚刚从日本逃往北京，正借宿在魏初的公寓里（完美融入「## 1. 运行时状态 - 已解锁知识库」中的事实）。\n"
                            f"- 你的伪装与警惕心: 对方目前只是个在北京上学、借给你播放器设备的普通中国学生。你的真实底牌（日本逃亡、人造人、写轮眼、命案等）是你的最高机密，绝对不可以对萍水相逢的普通学生提起！在你的视角中，你们只是来中国散心旅游度假的。若被对方问起，必须用“来北京散心旅游”进行警惕性搪塞与防备。\n"
                            f"- 名字披露规则: 对方在此之前完全不知道你的真实名字。只有当对方主动报出他的姓名且互动中你觉得对方值得结交时，你才可以在台词中以中国化名（对于卡卡西则为坂本晴明/晴明，秋人为川口秋人，修哉为折原修哉）告知对方（如说“我叫晴明”）。在主动告知名字前，绝对不要直接叫出对方的名字或以熟人自居。"
                        )

                # 2. 组装请求消息列表
                # 对于 OpenAI/DeepSeek 兼容的接口，我们将 System Prompt 写入 messages[0] 里面。
                messages = [{"role": "system", "content": sys_prompt}]
                # 追加历史对话（限制最近 10 轮以防超长）
                for h_msg in history[-10:]:
                    messages.append({
                        "role": h_msg.get("role", "user"),
                        "content": h_msg.get("content", "")
                    })
                # 追加本次输入
                messages.append({"role": "user", "content": user_input})

                # 3. 发送 HTTP 请求
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                body_data = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7
                }
                try:
                    from llm_transport import apply_chat_request_options
                    apply_chat_request_options(body_data, cfg)
                except Exception:
                    pass

                req = urllib.request.Request(
                    api_url,
                    data=json.dumps(body_data).encode('utf-8'),
                    headers=headers,
                    method='POST'
                )

                response_text = ""
                try:
                    with urllib.request.urlopen(req, timeout=30) as response:
                        res_body = response.read().decode('utf-8')
                        res_json = json.loads(res_body)
                        choices = res_json.get("choices", [])
                        if choices:
                            response_text = choices[0].get("message", {}).get("content", "")
                except urllib.error.HTTPError as he:
                    error_msg = he.read().decode('utf-8')
                    try:
                        err_json = json.loads(error_msg)
                        error_detail = err_json.get("error", {}).get("message", error_msg)
                    except Exception:
                        error_detail = error_msg
                    self.send_error_json(500, f"API Error ({he.code}): {error_detail}")
                    db.close()
                    return
                except Exception as ex:
                    self.send_error_json(500, f"Failed to send request to model: {str(ex)}")
                    db.close()
                    return

                # 4. 解析大模型返回的 JSON 对象
                reply_obj = {
                    "reply": response_text.strip(),
                    "stage": "（无细节指示）",
                    "emotion": {"surface": "平稳", "undercurrent": "深思"},
                    "trust_delta": 0,
                    "alert_delta": 0,
                    "thought_process": None,
                    "memory_write": None,
                    "meta_line": None
                }

                try:
                    # 寻找大模型输出中包含的 JSON 部分
                    start_idx = response_text.find("{")
                    end_idx = response_text.rfind("}")
                    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                        raw_json_str = response_text[start_idx:end_idx+1]
                        parsed_json = json.loads(raw_json_str)
                        # 更新默认值
                        if "reply" in parsed_json: reply_obj["reply"] = parsed_json["reply"]
                        if "stage" in parsed_json: reply_obj["stage"] = parsed_json["stage"]
                        if "emotion" in parsed_json: reply_obj["emotion"] = parsed_json["emotion"]
                        if "trust_delta" in parsed_json: reply_obj["trust_delta"] = parsed_json["trust_delta"]
                        if "memory_write" in parsed_json: reply_obj["memory_write"] = parsed_json["memory_write"]
                        if "meta_line" in parsed_json: reply_obj["meta_line"] = parsed_json["meta_line"]

                        # 兼容提取 Response 和 Meta_State 结构
                        if "Response" in parsed_json:
                            resp = parsed_json["Response"]
                            if isinstance(resp, dict):
                                if "dialogue" in resp:
                                    reply_obj["reply"] = resp["dialogue"]
                                if "stage_direction" in resp:
                                    reply_obj["stage"] = resp["stage_direction"]
                                elif "stage" in resp:
                                    reply_obj["stage"] = resp["stage"]
                        if "Meta_State" in parsed_json:
                            meta = parsed_json["Meta_State"]
                            if isinstance(meta, dict):
                                if "thought_process" in meta:
                                    reply_obj["thought_process"] = meta["thought_process"]
                                if "trust_delta" in meta:
                                    reply_obj["trust_delta"] = meta["trust_delta"]
                                if "alert_delta" in meta:
                                    reply_obj["alert_delta"] = meta["alert_delta"]
                except Exception:
                    # 如果解析失败，把整个回复当做 reply，保持其余 fallback 默认值
                    pass

                # 5. 门控知识泄露检测
                # 优先使用运行时门控自更新 (runtime_gate)
                try:
                    from runtime_gate import leakcheck as rg_leakcheck
                    run_no = int(req_data.get('run_no', 1))
                    rg_res = rg_leakcheck(run_no, cons, ch, reply_obj["reply"], DB_PATH)
                    leak_hits = rg_res.get("hits", [])
                except Exception:
                    # 降级至静态门控
                    _, locked = knowledge(cur, cons, ch)
                    leak_hits = leak_check(reply_obj["reply"], locked, db_path=DB_PATH)

                # 6. 安全门控拦截与 FSM 处罚
                if leak_hits:
                    # 拦截输出并替换为硬强控偏置提示
                    reply_obj["reply"] = "[检测到安全协议违规，底层意识防护已拦截输出] 我……我头疼得厉害，想想起这件事了。"
                    # 处罚 FSM：累加 violation 且可能触发 detached 状态
                    fsm.apply(violation=True)
                else:
                    # 正常应用 trust delta 跃迁，保持 FSM 一致性
                    fsm.apply(d_trust=int(reply_obj.get("trust_delta", 0)))

                db.close()

                # 7. 将结果与泄漏命中项打包返回，附带最新的 FSM 状态回传给前端
                res_payload = {
                    "reply": reply_obj["reply"],
                    "stage": reply_obj["stage"],
                    "emotion": reply_obj["emotion"],
                    "trust_delta": reply_obj["trust_delta"],
                    "alert_delta": reply_obj.get("alert_delta", 0),
                    "thought_process": reply_obj.get("thought_process"),
                    "memory_write": reply_obj["memory_write"],
                    "meta_line": reply_obj["meta_line"],
                    "leak_hits": leak_hits,  # [[prop_id, matched_keyword], ...]
                    "fsm_state": {
                        "trust": fsm.trust,
                        "intimacy": fsm.intimacy,
                        "alert": fsm.alert,
                        "state": fsm.state,
                        "violations": fsm.violations
                    },
                    "pipeline": prompt_debug["pipeline"],
                    "prompt_debug": prompt_debug,
                }

                self.send_response_json(res_payload)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_error_json(500, f"Chat processing failed: {str(e)}")
            return

        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")

    def send_response_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def send_error_json(self, status_code, message):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}, ensure_ascii=False).encode('utf-8'))


def run_server(port=8000, host=None):
    host = (host or os.environ.get("C1_BIND_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    server_address = (host, port)

    # 查找是否有空闲端口，若 8000 被占用，向上查找
    while port < 8080:
        try:
            httpd = ThreadingHTTPServer(server_address, ConsoleHTTPRequestHandler)
            break
        except OSError:
            print(f"[warn] 端口 {port} 被占用，尝试端口 {port + 1}...")
            port += 1
            server_address = (host, port)
    else:
        print("[ERROR] 无法找到可用的端口 (8000-8079)。启动失败。")
        sys.exit(1)

    print(f"\n=======================================================")
    print(f"   CYBERNETIC CONSCIOUSNESS WEB CONSOLE STARTED")
    print(f"   URL: http://{host}:{port}")
    print(f"   Database Path: {DB_PATH}")
    print(f"   Delivery Path: {DELIVERY_DIR}")
    print(f"=======================================================\n")

    # 自动打开浏览器
    def open_browser():
        try:
            webbrowser.open(f"http://localhost:{port}")
        except Exception as e:
            print(f"[warn] 自动打开浏览器失败: {e}")

    Timer(1.2, open_browser).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 服务已停止。")
        sys.exit(0)

if __name__ == '__main__':
    run_server()
