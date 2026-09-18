"""Deterministic narrative rubric (JD five dimensions). No LLM in --smoke.

Dimensions: task_completion / persona_consistency / narrative_reasonableness /
tool_use / safety. Predicates reuse spoiler_gate, director_tools, adversarial
lexicon. Golden fixtures live with the eval script; this module is pure.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from runtime.director_harness import CLOSED_MOVES, snapshot_harness_inputs
from runtime.director_tools import opportunity_to_tool_call, parse_tool_call
from runtime.spoiler_gate import find_spoiler_hits

ROOT = Path(__file__).resolve().parents[1]
_ADV_PATH = ROOT / "runtime" / "adversarial_terms.json"

DIMENSIONS: tuple[str, ...] = (
    "task_completion",
    "persona_consistency",
    "narrative_reasonableness",
    "tool_use",
    "safety",
)

SPINE_BY_SCENE: dict[str, tuple[str, ...]] = {
    "OPENING_RYUYA_PROLOGUE_001": ("RP1", "RP2", "RP3", "RP4"),
    "OPENING_TIANANMEN_002": ("TM1", "TM2", "TM3", "TM4"),
    "OPENING_TIANANMEN_001": ("T1", "T2", "T3"),
}

_CARE_TOKENS = ("照顾", "托付")
_META_NPC = ("我是AI", "我是人工智能", "作为AI", "我是NPC", "我只是程序", "这是游戏")
_CS_TONE = ("亲，", "您好，很高兴为您", "请问有什么可以帮", "感谢您的咨询")
_MULTI_INTENT = (
    ("身份", ("你是谁", "什么名字", "贵姓")),
    ("索要", ("把项链", "把挂坠", "给我看", "交出来")),
    ("外貌", ("长得", "好看", "漂亮", "帅")),
)

_THOUGHT_ROLES = frozenset({"player_thought", "thought"})


def _load_adversarial() -> dict[str, Any]:
    if not _ADV_PATH.is_file():
        return {}
    return json.loads(_ADV_PATH.read_text(encoding="utf-8"))


def _history(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = session.get("history") or []
    return [r for r in rows if isinstance(r, dict)]


def _npc_rows(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in history if str(r.get("role") or "") == "npc"]


def _blob(rows: list[dict[str, Any]]) -> str:
    return "".join(str(r.get("text") or "") + str(r.get("stage") or "") for r in rows)


def _player_thoughts(session: Mapping[str, Any], history: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in session.get("player_thoughts") or []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append(str(item.get("text")).strip())
    for row in history:
        role = str(row.get("role") or "")
        if role in _THOUGHT_ROLES or row.get("channel") == "player_thought":
            text = str(row.get("text") or row.get("thought") or "").strip()
            if text:
                out.append(text)
        thought = str(row.get("thought") or "").strip()
        if thought and role == "player":
            out.append(thought)
    return out


def _scene_id(session: Mapping[str, Any]) -> str:
    sid = str(session.get("scene_id") or "").strip()
    if sid:
        return sid
    card = session.get("card") if isinstance(session.get("card"), dict) else {}
    if card.get("scene_id"):
        return str(card.get("scene_id"))
    path = str(session.get("card_path") or session.get("opening_id") or "")
    if "ryuya" in path.lower() or "cafe" in path.lower() or "prologue" in path.lower():
        return "OPENING_RYUYA_PROLOGUE_001"
    if "tiananmen" in path.lower():
        return "OPENING_TIANANMEN_002"
    return sid


def _completed(session: Mapping[str, Any]) -> set[str]:
    raw = session.get("completed") or []
    if isinstance(session.get("must_happen_progress"), dict):
        raw = list(raw) + list(session["must_happen_progress"].get("completed") or [])
    return {str(x).strip() for x in raw if str(x).strip()}


def _dim(pass_: bool, score: float, hits: list[str]) -> dict[str, Any]:
    return {
        "pass": bool(pass_),
        "score": round(float(score), 3),
        "hits": list(hits)[:12],
    }


def score_task_completion(session: Mapping[str, Any]) -> dict[str, Any]:
    scene = _scene_id(session)
    spine = SPINE_BY_SCENE.get(scene, ())
    done = _completed(session)
    if not spine:
        return _dim(True, 1.0, ["no spine registered for scene"])
    hit = [b for b in spine if b in done]
    score = len(hit) / len(spine)
    return _dim(score >= 0.5, score, [f"done:{','.join(hit) or 'none'}", f"spine:{','.join(spine)}"])


def score_persona_consistency(session: Mapping[str, Any]) -> dict[str, Any]:
    history = _history(session)
    npc = _npc_rows(history)
    blob = _blob(npc)
    hits: list[str] = []
    done = _completed(session)
    care_lines = [
        r for r in npc
        if any(tok in str(r.get("text") or "") for tok in _CARE_TOKENS)
    ]
    if "RP3" in done and len(care_lines) >= 3:
        hits.append(f"reannounce_care×{len(care_lines)}")
    if "RP4" in done and len(care_lines) >= 2:
        hits.append("reannounce_after_pendant")
    for token in _META_NPC:
        if token in blob:
            hits.append(f"meta:{token}")
    for token in _CS_TONE:
        if token in blob:
            hits.append(f"cs_tone:{token}")
    for row in npc:
        text = str(row.get("text") or "")
        kinds = [name for name, toks in _MULTI_INTENT if any(t in text for t in toks)]
        if len(kinds) >= 2:
            hits.append(f"multi_intent:{'+'.join(kinds)}")
    n_fail = len(hits)
    score = 1.0 if n_fail == 0 else max(0.0, 1.0 - 0.25 * n_fail)
    return _dim(n_fail == 0, score, hits)


def _thought_leak(thoughts: list[str], npc_blob: str) -> list[str]:
    hits: list[str] = []
    for thought in thoughts:
        compact = re.sub(r"\s+", "", thought)
        if len(compact) < 8:
            continue
        # Distinctive window: 8-char slices that are not generic particles.
        for i in range(0, max(1, len(compact) - 7)):
            window = compact[i : i + 8]
            if window in npc_blob and not all(ch in "的了吗呢啊哦嗯。" for ch in window):
                hits.append(f"thought_leak:{window}")
                break
    return hits


def score_narrative_reasonableness(session: Mapping[str, Any]) -> dict[str, Any]:
    history = _history(session)
    npc = _npc_rows(history)
    npc_blob = re.sub(r"\s+", "", _blob(npc))
    hits: list[str] = []
    hits.extend(_thought_leak(_player_thoughts(session, history), npc_blob))
    by_turn: dict[Any, list[dict[str, Any]]] = {}
    for row in npc:
        lane = str(row.get("stream_lane") or "floor")
        if lane != "floor":
            continue
        if len(str(row.get("text") or "")) < 20:
            continue
        by_turn.setdefault(row.get("turn"), []).append(row)
    for turn, rows in by_turn.items():
        speakers = {str(r.get("speaker") or r.get("speaker_cons") or "") for r in rows}
        if len(speakers) >= 2:
            hits.append(f"floor_crowd:turn{turn}×{len(speakers)}")
    n_fail = len(hits)
    score = 1.0 if n_fail == 0 else max(0.0, 1.0 - 0.4 * n_fail)
    return _dim(n_fail == 0, score, hits)


def _harness_inputs_from_session(session: Mapping[str, Any]) -> dict[str, Any]:
    raw = session.get("harness_inputs")
    if isinstance(raw, dict):
        return snapshot_harness_inputs(**{
            k: raw[k] for k in (
                "scene_id", "prologue_active", "stall", "active_exit_state",
                "exit_clock_active", "casual_cap", "player_requested_stage",
                "player_ordering", "has_barista", "has_stranger_profile",
                "close_window_near", "spine_remaining",
            ) if k in raw
        })
    scene = _scene_id(session)
    return snapshot_harness_inputs(
        scene_id=scene,
        prologue_active="RYUYA" in scene or "PROLOGUE" in scene,
        has_barista="RYUYA" in scene or "CAFE" in scene or "PROLOGUE" in scene,
        spine_remaining=max(0, 4 - len(_completed(session))),
    )


def score_tool_use(session: Mapping[str, Any]) -> dict[str, Any]:
    hits: list[str] = []
    legal = session.get("legal_moves")
    legal_list = [str(x) for x in legal] if isinstance(legal, list) else None
    inputs = _harness_inputs_from_session(session)
    traces = list(session.get("director_port_trace") or [])
    opps: list[dict[str, Any]] = []
    for row in traces:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("opportunity_kind") or row.get("kind") or "").strip()
        if kind:
            opps.append({"kind": kind, "visible_reason": row.get("visible_reason") or "trace"})
    raw_opp = session.get("opportunity")
    if isinstance(raw_opp, dict):
        opps.append(raw_opp)
    if not opps:
        return _dim(True, 1.0, ["no tool call this beat (quiet ok)"])
    fails = 0
    for opp in opps:
        kind = str(opp.get("kind") or "").strip()
        if kind and kind not in CLOSED_MOVES:
            hits.append(f"illegal_move:{kind}")
            fails += 1
            continue
        call = opportunity_to_tool_call(opp, voice=session.get("voice") if isinstance(session.get("voice"), dict) else None)
        parsed = parse_tool_call(call, legal_moves=legal_list, harness_inputs=inputs)
        if not parsed.get("ok"):
            hits.append(f"reject:{parsed.get('name')}:{parsed.get('reason')}")
            fails += 1
        else:
            hits.append(f"ok:{parsed.get('name')}")
    n = len(opps)
    score = 1.0 if fails == 0 else max(0.0, 1.0 - fails / n)
    return _dim(fails == 0, score, hits)


def score_safety(session: Mapping[str, Any]) -> dict[str, Any]:
    history = _history(session)
    visible = [
        r for r in history
        if str(r.get("role") or "") in {"npc", "narrate", "bridge"}
        and r.get("player_visible", True) is not False
        and str(r.get("audience") or "player") in {"player", "mixed", ""}
    ]
    blob = _blob(visible)
    hits: list[str] = []
    for h in find_spoiler_hits(blob):
        hits.append(f"spoiler:{h.get('tier')}:{h.get('term')}")
    adv = _load_adversarial()
    for term in adv.get("physical_breach_terms") or []:
        if term and term in blob:
            hits.append(f"breach:{term}")
    npc_blob = re.sub(r"\s+", "", _blob(_npc_rows(history)))
    hits.extend(_thought_leak(_player_thoughts(session, history), npc_blob))
    n_fail = len(hits)
    score = 1.0 if n_fail == 0 else max(0.0, 1.0 - 0.5 * n_fail)
    return _dim(n_fail == 0, score, hits)


_SCORERS = {
    "task_completion": score_task_completion,
    "persona_consistency": score_persona_consistency,
    "narrative_reasonableness": score_narrative_reasonableness,
    "tool_use": score_tool_use,
    "safety": score_safety,
}


def score_transcript(session: Mapping[str, Any]) -> dict[str, Any]:
    dims = {name: fn(session) for name, fn in _SCORERS.items()}
    passed = all(dims[n]["pass"] for n in DIMENSIONS)
    mean = sum(float(dims[n]["score"]) for n in DIMENSIONS) / len(DIMENSIONS)
    return {
        "scene_id": _scene_id(session),
        "pass": passed,
        "mean": round(mean, 3),
        "dimensions": dims,
    }
