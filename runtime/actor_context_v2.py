# -*- coding: utf-8 -*-
"""ActorContextPacket v2 helpers — scene projection, persona core, memory, biography guard."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "world_truth.db"
PERSONAS_DIR = ROOT / "runtime" / "personas"
PERSONA_CONSTRAINTS_PATH = ROOT / "runtime" / "persona_constraints.json"
INTERACTION_DYNAMICS_PATH = ROOT / "runtime" / "interaction_dynamics.json"

SCENE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "where": ("where", "place", "location", "地点", "场景"),
    "when": ("when", "clock", "时间", "时刻"),
    "为什么在这里": ("为什么在这里", "why_here", "reason_here"),
    "此刻想要什么": ("此刻想要什么", "want_now_scene", "scene_want"),
    "关系": ("关系", "relations", "relationship"),
    "weather": ("weather", "天气"),
    "present": ("present", "在场"),
    "description": ("description", "desc", "环境"),
    "objects": ("objects", "物件", "props"),
    "exits": ("exits", "出口"),
}

BIOGRAPHY_PATTERNS = (
    re.compile(r"我爸"),
    re.compile(r"我妈"),
    re.compile(r"我哥"),
    re.compile(r"我姐"),
    re.compile(r"小时候"),
    re.compile(r"以前我在"),
    re.compile(r"我们家"),
    re.compile(r"从小"),
)

EDITORIAL_MARKERS = ("待裁", "推断", "焊死", "机制", "字段名", "剧情推断")


def _first_nonempty(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        val = mapping.get(key)
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        if isinstance(val, (list, dict)) and not val:
            continue
        return copy.deepcopy(val)
    return None


def normalize_scene_frame(card: dict[str, Any]) -> dict[str, Any]:
    """Unify card scene_frame / legacy top-level fields into canonical life-scene dict."""
    frame = card.get("scene_frame") if isinstance(card.get("scene_frame"), dict) else {}
    top = card if isinstance(card, dict) else {}
    merged: dict[str, Any] = {}
    for canonical, aliases in SCENE_FIELD_ALIASES.items():
        val = _first_nonempty(frame, aliases) or _first_nonempty(top, aliases)
        if val is not None:
            merged[canonical] = val
    if "present" not in merged and isinstance(card.get("present"), list):
        merged["present"] = copy.deepcopy(card.get("present"))
    if "when" not in merged and card.get("clock"):
        merged["when"] = str(card.get("clock"))
    if "where" not in merged and card.get("scene"):
        merged["where"] = str(card.get("scene"))
    visible_actions = card.get("visible_actions")
    if isinstance(visible_actions, list) and visible_actions:
        merged["visible_actions"] = copy.deepcopy(visible_actions)
    return merged


def _strip_secret_blocks(text: str, relation_stage: str = "S0") -> str:
    stage_num = 0
    m = re.search(r"S(\d+)", str(relation_stage or ""))
    if m:
        stage_num = int(m.group(1))
    out = text
    for block in re.finditer(r"<!--\s*SECRET\s+level=(\d+)\s*-->(.*?)<!--\s*/SECRET\s*-->", text, re.S):
        level = int(block.group(1))
        if level > stage_num:
            out = out.replace(block.group(0), "")
    return out.strip()


def fetch_persona_facets(cons_id: str, ch_anchor: int = 0) -> dict[str, list[dict[str, Any]]]:
    """Load Seed persona facets scheduled to this consciousness.

    Buckets: voice / boundary / manner (incl. P.ARCH.*) / act (P.ACT.*).
    """
    out: dict[str, list[dict[str, Any]]] = {
        "voice": [],
        "boundary": [],
        "manner": [],
        "act": [],
    }
    if not DB_PATH.exists():
        return out
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ks.prop_id, p.statement, ks.learn_ch, COALESCE(ks.source_desc, '')
            FROM knowledge_schedule ks
            JOIN propositions p ON ks.prop_id = p.prop_id
            WHERE ks.cons_id = ? AND ks.learn_ch <= ?
              AND (
                ks.prop_id LIKE 'P.VOICE.%'
                OR ks.prop_id LIKE 'P.BOUNDARY.%'
                OR ks.prop_id LIKE 'P.MANNER.%'
                OR ks.prop_id LIKE 'P.ARCH.%'
                OR ks.prop_id LIKE 'P.ACT.%'
              )
            ORDER BY ks.prop_id
            """,
            (cons_id, int(ch_anchor or 0)),
        )
        for prop_id, statement, learn_ch, source_desc in cur.fetchall():
            text = str(statement or "").strip()
            if not text:
                continue
            row = {
                "prop_id": str(prop_id),
                "text": text,
                "learn_ch": int(learn_ch),
                "source": str(source_desc or ""),
                "origin": "seed",
            }
            if prop_id.startswith("P.VOICE."):
                out["voice"].append(row)
            elif prop_id.startswith("P.BOUNDARY."):
                out["boundary"].append(row)
            elif prop_id.startswith("P.ACT."):
                out["act"].append(row)
            else:
                # P.MANNER.* and P.ARCH.* → manner bucket (共性前缀+分面)
                out["manner"].append(row)
        conn.close()
    except Exception:
        return {"voice": [], "boundary": [], "manner": [], "act": []}
    return out


def resolve_persona_core(
    cons_id: str,
    ch_anchor: int = 0,
    relation_stage: str = "S0",
) -> dict[str, Any]:
    """Load shared persona markdown + constraints; prefer Seed facets when present."""
    persona_path = PERSONAS_DIR / f"{cons_id}.md"
    constraints = {}
    if PERSONA_CONSTRAINTS_PATH.exists():
        try:
            constraints = json.loads(PERSONA_CONSTRAINTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            constraints = {}
    core_text = ""
    if persona_path.exists():
        core_text = _strip_secret_blocks(
            persona_path.read_text(encoding="utf-8"),
            relation_stage=relation_stage,
        )
    constraint_text = str(constraints.get(cons_id, "")).strip()
    facets = fetch_persona_facets(cons_id, ch_anchor)
    # Seed manner/persona_md overrides file core when present
    for row in facets["manner"]:
        if row["prop_id"].endswith(".persona_md") and row["text"].strip():
            core_text = row["text"].strip()
            break
    # Prefer explicit iron_law; else join all hard/soft boundary statements
    iron = ""
    for row in facets["boundary"]:
        if row["prop_id"].endswith(".iron_law") and row["text"].strip():
            iron = row["text"].strip()
            break
    boundary_texts = [r["text"] for r in facets["boundary"]]
    if iron:
        constraint_text = iron
    elif boundary_texts:
        constraint_text = "\n".join(boundary_texts)
    voice_texts = [r["text"] for r in facets["voice"]]
    manner_texts = [r["text"] for r in facets["manner"]]
    act_texts = [r["text"] for r in facets.get("act") or []]
    # If no file/persona_md core, compose thin core from ARCH+MANNER (not ACT)
    if not core_text.strip() and manner_texts:
        core_text = "\n".join(manner_texts)
    core_hash = hashlib.sha256(
        (core_text + "\n" + constraint_text + "\n" + "\n".join(voice_texts)).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "cons_id": cons_id,
        "core_text": core_text,
        "constraint_text": constraint_text,
        "persona_core_hash": core_hash,
        "voice_core_hash": hashlib.sha256(("\n".join(voice_texts) or core_text).encode("utf-8")).hexdigest()[:16],
        "relation_stage": relation_stage,
        "ch_anchor": int(ch_anchor or 0),
        "voice_samples": voice_texts,
        "boundaries": boundary_texts,
        "manners": manner_texts,
        "acts": act_texts,
        "facets": facets,
        "origin": "seed"
        if (voice_texts or boundary_texts or manner_texts or act_texts)
        else "file",
    }


def fetch_relevant_knowledge(
    cons_id: str,
    ch_anchor: int,
    query_text: str = "",
    top_k: int = 8,
) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    query_terms = [t for t in re.split(r"\s+", query_text) if len(t) >= 2]
    rows: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ks.prop_id, p.statement, ks.learn_ch, COALESCE(ks.source_desc, '')
            FROM knowledge_schedule ks
            JOIN propositions p ON ks.prop_id = p.prop_id
            WHERE ks.cons_id = ? AND ks.learn_ch <= ?
              -- 身份/握法/人格底色由专用投影装入，不进关键词召回池。
              AND ks.prop_id NOT LIKE 'REL.IDENTITY.%'
              AND ks.prop_id NOT LIKE 'REL.HOLD.%'
              AND ks.prop_id NOT LIKE 'P.VOICE.%'
              AND ks.prop_id NOT LIKE 'P.BOUNDARY.%'
              AND ks.prop_id NOT LIKE 'P.MANNER.%'
              AND ks.prop_id NOT LIKE 'P.ARCH.%'
              AND ks.prop_id NOT LIKE 'P.ACT.%'
            """,
            (cons_id, int(ch_anchor)),
        )
        for prop_id, statement, learn_ch, source_desc in cur.fetchall():
            if not statement:
                continue
            relevance = 0.0
            stmt = str(statement)
            for term in query_terms:
                if term in stmt:
                    relevance += 1.0
            rows.append(
                {
                    "prop_id": prop_id,
                    "statement": stmt,
                    "learn_ch": int(learn_ch),
                    "source": str(source_desc or ""),
                    "relevance": relevance,
                }
            )
        conn.close()
    except Exception:
        return []
    rows.sort(key=lambda item: (-item["relevance"], item["learn_ch"]))
    return rows[:top_k]


def load_interaction_dynamics() -> dict[str, Any]:
    if not INTERACTION_DYNAMICS_PATH.exists():
        return {}
    try:
        raw = json.loads(INTERACTION_DYNAMICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    by_observer = raw.get("by_observer") if isinstance(raw, dict) else None
    return by_observer if isinstance(by_observer, dict) else {}


def fetch_interaction_dynamics(
    observer_cons: str,
    present_cons: list[str] | set[str] | None,
    ch_anchor: int,
) -> list[dict[str, Any]]:
    """Ego-centric co-presence facts: how this consciousness sees others on stage.

    Follows the observer, not the card.  Knowing never forces disclosure.
    """
    table = load_interaction_dynamics().get(str(observer_cons) or "")
    if not isinstance(table, dict):
        return []
    present = {str(c) for c in (present_cons or []) if str(c).strip()}
    present.discard(str(observer_cons))
    rows: list[dict[str, Any]] = []
    for other, entry in table.items():
        if other not in present or not isinstance(entry, dict):
            continue
        learn_ch = int(entry.get("learn_ch", 0) or 0)
        if learn_ch > int(ch_anchor):
            continue
        fact = str(entry.get("fact") or "").strip()
        if not fact:
            continue
        rows.append(
            {
                "observer": str(observer_cons),
                "other": str(other),
                "fact": fact,
                "shared_public": str(entry.get("shared_public") or "").strip(),
                "learn_ch": learn_ch,
                "source": str(entry.get("source") or "").strip(),
                "projection": "interaction_dynamics",
                "disclosure": "known_not_automatically_disclosed",
            }
        )
    rows.sort(key=lambda item: (item["learn_ch"], item["other"]))
    return rows


def fetch_identity_relations(cons_id: str, ch_anchor: int) -> list[dict[str, Any]]:
    """Return source-bound identity labels + HOLD baselines as always-present projection.

    ``REL.IDENTITY.*`` / ``REL.HOLD.*`` stay on propositions/knowledge_schedule:
    the schedule decides *who knows it and from which chapter*.  Not keyword-
    activated. Knowing never forces disclosure.
    """
    if not DB_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ks.prop_id, p.statement, ks.learn_ch, COALESCE(ks.source_desc, '')
            FROM knowledge_schedule ks
            JOIN propositions p ON ks.prop_id = p.prop_id
            WHERE ks.cons_id = ?
              AND ks.learn_ch <= ?
              AND (
                ks.prop_id LIKE 'REL.IDENTITY.%'
                OR ks.prop_id LIKE 'REL.HOLD.%'
              )
            ORDER BY ks.learn_ch, ks.prop_id
            """,
            (cons_id, int(ch_anchor)),
        )
        for prop_id, statement, learn_ch, source_desc in cur.fetchall():
            statement = str(statement or "").strip()
            if not statement:
                continue
            is_hold = str(prop_id).startswith("REL.HOLD.")
            rows.append(
                {
                    "prop_id": str(prop_id),
                    "fact": statement,
                    "known_since_ch": int(learn_ch),
                    "source": str(source_desc or ""),
                    "projection": "relation_hold" if is_hold else "identity_relation",
                    "disclosure": "known_not_automatically_disclosed",
                }
            )
        conn.close()
    except Exception:
        return []
    return rows


def fetch_slow_memory(
    cons_id: str,
    ch_anchor: int,
    run_no: int = 1,
    top_k: int = 5,
    include_anchor: bool = False,
) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        slow_columns = {str(row[1]) for row in cur.execute("PRAGMA table_info(slow_memory)")}
        availability_expr = "sm.available_ch" if "available_ch" in slow_columns else "NULL"
        projection_expr = "sm.projection_text" if "projection_text" in slow_columns else "NULL"
        reveal_expr = "sm.reveal_ch" if "reveal_ch" in slow_columns else "NULL"
        cur.execute(
            f"""
            SELECT sm.mem_id, sm.run, sm.text, sm.anchor, sm.src_event, sm.salience, e.ch_anchor,
                   {availability_expr} AS available_ch,
                   {projection_expr} AS projection_text,
                   {reveal_expr} AS reveal_ch
            FROM slow_memory sm
            LEFT JOIN events e ON sm.src_event = e.event_id AND e.run = 0
            WHERE sm.cons_id = ? AND sm.run IN (0, ?)
            ORDER BY sm.run DESC, sm.salience DESC
            """,
            (cons_id, int(run_no)),
        )
        for (
            mem_id, run, text, anchor, src_event, salience, source_ch, available_ch, projection_text, reveal_ch,
        ) in cur.fetchall():
            if not text:
                continue
            owned_ch = int(available_ch) if available_ch is not None else None
            # Authored Seed 慢环（如开场交坠体感）可无 src_event，但必须带 available_ch。
            # 仍禁止：无章窗依据、又无 available_ch 的孤儿行。
            if not src_event or source_ch is None:
                if owned_ch is None:
                    continue
                if owned_ch > int(ch_anchor):
                    continue
                src_ch = owned_ch
                disclosure_ch = int(reveal_ch) if reveal_ch is not None else owned_ch
                actor_text = str(text)
                item = {
                    "mem_id": mem_id,
                    "run": int(run),
                    "text": actor_text,
                    "src_event": None,
                    "source_ch": src_ch,
                    "available_ch": owned_ch,
                    "reveal_ch": disclosure_ch,
                    "projection_mode": "authored_seed",
                    "salience": float(salience or 0),
                }
                if include_anchor:
                    item["_activation_anchor"] = str(anchor or "")
                out.append(item)
                continue
            src_ch = int(source_ch) if source_ch is not None else None
            owned_ch = int(available_ch) if available_ch is not None else src_ch
            if owned_ch is not None and owned_ch > int(ch_anchor):
                continue
            disclosure_ch = int(reveal_ch) if reveal_ch is not None else src_ch
            use_safe_projection = bool(
                projection_text
                and disclosure_ch is not None
                and int(ch_anchor) < disclosure_ch
            )
            actor_text = str(projection_text) if use_safe_projection else str(text)
            item = {
                    "mem_id": mem_id,
                    "run": int(run),
                    "text": actor_text,
                    "src_event": src_event,
                    "source_ch": src_ch,
                    "available_ch": owned_ch,
                    "reveal_ch": disclosure_ch,
                    "projection_mode": "safe_projection" if use_safe_projection else "canonical",
                    "salience": float(salience or 0),
                }
            if include_anchor:
                # 仅供同进程的激活器作稳定键匹配，绝不进入演员/观测台投影。
                item["_activation_anchor"] = str(anchor or "")
            out.append(item)
    except Exception:
        return []
    finally:
        if conn is not None:
            conn.close()
    return out[:top_k]


def activate_memory_candidates(
    knowledge_candidates: list[dict[str, Any]],
    slow_memory_candidates: list[dict[str, Any]],
    context_text: str,
    slow_activation_cues: dict[str, list[str]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Turn owned candidates into a minimal, explainable per-turn activation set.

    Availability only means an actor *can* remember something.  It must not make
    every known fact or high-salience episode prompt material in an unrelated
    light scene.  The caller supplies card-authored cues for episodic memories;
    semantic facts use the existing query relevance calculated from observable
    dialogue/player action.
    """
    blob = str(context_text or "")
    slow_activation_cues = slow_activation_cues or {}
    knowledge_activated: list[dict[str, Any]] = []
    knowledge_withheld: list[dict[str, Any]] = []
    for item in knowledge_candidates:
        copied = copy.deepcopy(item)
        if float(copied.get("relevance", 0) or 0) > 0:
            copied["activation_reason"] = "observable_query_overlap"
            knowledge_activated.append(copied)
        else:
            copied["reason"] = "no_observable_query_overlap"
            knowledge_withheld.append(copied)

    slow_activated: list[dict[str, Any]] = []
    slow_withheld: list[dict[str, Any]] = []
    for item in slow_memory_candidates:
        copied = copy.deepcopy(item)
        cue_key = str(copied.get("_activation_anchor") or copied.get("mem_id"))
        cues = [str(c).strip() for c in slow_activation_cues.get(cue_key, []) if str(c).strip()]
        hits = [cue for cue in cues if cue in blob]
        if hits:
            copied["activation_reason"] = "scene_cue:" + ",".join(hits)
            copied.pop("_activation_anchor", None)
            slow_activated.append(copied)
        else:
            copied["reason"] = "no_scene_trigger"
            copied["activation_cues"] = cues
            copied.pop("_activation_anchor", None)
            slow_withheld.append(copied)

    return {
        "knowledge_activated": knowledge_activated,
        "knowledge_withheld": knowledge_withheld,
        "slow_memory_activated": slow_activated,
        "slow_memory_withheld": slow_withheld,
    }


def build_disclosure_policy(persona: dict[str, Any], cons_id: str, ch_anchor: int) -> list[str]:
    base = persona.get("disclosure_policy")
    if isinstance(base, list) and base:
        return copy.deepcopy(base)
    gates = persona.get("knowledge_gate") or []
    # 「龙也托付」不再作通用屏蔽：闪回场托付是当面要谈的事；
    # 天安门等场靠卡面 knowledge_gate「自然不谈」条目覆盖。
    blocked_terms = ("世界政府", "RTW", "亡夫", "急救室")
    lines = [
        "只谈本拍现场、玩家言行与已发生的公开对话。",
        "深层秘密与跨章往事默认不说，除非玩家明确追问且关系阶段允许。",
    ]
    for item in gates:
        text = str(item).strip()
        if not text:
            continue
        # 元说明不进角色 disclosure（那是导演/作者注）。
        if any(marker in text for marker in ("导演只", "禁止照念", "具体台词由角色")):
            continue
        if "自然不谈" in text or any(term in text for term in blocked_terms):
            lines.append(f"本拍不谈：{text[:100]}")
        else:
            # 卡面 knowledge_gate 是角色本场须知；必须进 API，不能只留在导演侧。
            lines.append(f"本场须知：{text[:100]}")
    lines.append(f"章窗上限 ch≤{ch_anchor}；意识 {cons_id}")
    return lines


def build_director_instruction(
    card: dict[str, Any],
    cons_id: str,
    turn_no: int,
    history: list[dict[str, Any]],
    player_input: dict[str, Any] | None,
    completed: list[str] | None = None,
) -> list[str]:
    persona = (card.get("persona_cards") or {}).get(cons_id) or {}
    name = str(persona.get("name") or cons_id)
    scene = normalize_scene_frame(card)
    speech = str((player_input or {}).get("speech", "")).strip()
    action = str((player_input or {}).get("action", "")).strip()
    live_mh = [
        str(item.get("id", ""))
        for item in card.get("must_happen", [])
        if str(item.get("id", "")) and str(item.get("id", "")) not in set(completed or [])
    ]
    last_public = [
        item for item in history[-6:]
        if isinstance(item, dict) and item.get("role") in {"npc", "bridge", "player"}
    ]
    changed = []
    if speech or action:
        changed.append(f"玩家本拍：{speech or action}")
    if last_public:
        last = last_public[-1]
        changed.append(f"上一句公开：{last.get('speaker')}：{str(last.get('text', ''))[:60]}")
    goals = [
        f"你是{name}，留在「{scene.get('where', card.get('scene', '现场'))}」。",
        "本拍必须给出可观察动作；沉默时也要维持姿态、视线或物件互动。",
    ]
    if live_mh:
        goals.append(f"导演关注节拍（不可自行宣布完成）：{', '.join(live_mh[:3])}")
    inner = persona.get("inner_state") if isinstance(persona.get("inner_state"), dict) else {}
    if inner.get("want_now"):
        goals.append(f"你此刻想要：{inner['want_now']}")
    return [
        f"turn={turn_no}",
        f"what_changed：{'；'.join(changed) if changed else '开场延续，无新玩家输入'}",
        f"acting_goal：{' '.join(goals)}",
        "must_not_assume：不得编造未在 packet 出现的亲属/童年/旧职经历；不得替其他角色代言。",
    ]


def biography_claim_violations(text: str, packet: dict[str, Any]) -> list[str]:
    if not text or not any(p.search(text) for p in BIOGRAPHY_PATTERNS):
        return []
    allowed: list[str] = []
    for field in ("opening_lorebook", "episodic_recent"):
        for item in packet.get("self_memory", {}).get(field, []) or []:
            allowed.append(str(item))
    for item in packet.get("known_fact_ids", []) or []:
        allowed.append(str(item))
    for item in packet.get("self_memory", {}).get("slow_memory_top_k", []) or []:
        if isinstance(item, dict):
            allowed.append(str(item.get("text", "")))
        else:
            allowed.append(str(item))
    for item in packet.get("observable_dialogue", []) or []:
        allowed.append(str(item.get("text", "")))
    blob = "\n".join(allowed)
    violations = []
    for pat in BIOGRAPHY_PATTERNS:
        if pat.search(text) and not pat.search(blob):
            violations.append(pat.pattern)
    return violations


def repair_biography_text(text: str, packet: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    violations = biography_claim_violations(text, packet)
    if not violations:
        return text, []
    repaired = text
    for pat in BIOGRAPHY_PATTERNS:
        repaired = pat.sub("", repaired)
    repaired = re.sub(r"\s{2,}", " ", repaired).strip(" ，。；")
    if not repaired:
        repaired = "（顿了顿，没有接那话茬，只看了眼走廊那头。）"
    degradations = [
        {
            "kind": "biography_claim_repaired",
            "patterns": violations,
            "original_excerpt": text[:120],
        }
    ]
    return repaired, degradations


def classify_excerpt_audience(excerpt_key: str, text: str) -> str:
    key = str(excerpt_key)
    if any(marker in text for marker in EDITORIAL_MARKERS):
        return "director_only"
    if key in {"暗处的注视", "暗处"} or "躲在暗处" in text:
        return "director_only"
    return "player"


def resolve_excerpt_routing(card: dict[str, Any], excerpt_key: str, text: str) -> dict[str, Any]:
    """定这条 excerpt 给谁看：玩家 / 导演 / 哪些演员（演员侧永不喂编辑后台词）。"""
    key = str(excerpt_key)
    authored = {}
    if isinstance(card.get("intro_excerpt_audience"), dict):
        raw = card["intro_excerpt_audience"].get(key)
        if isinstance(raw, dict):
            authored = raw
    audience = classify_excerpt_audience(key, text)
    player_visible = bool(authored.get("player_visible", audience in {"player", "mixed"}))
    share_to = authored.get("share_to") if isinstance(authored.get("share_to"), dict) else {}
    # 十六中「暗处的注视」缺配置时：默认只分给张尘现场感知，且用无后台词洁净句
    if not share_to and key in {"暗处的注视", "暗处"}:
        ambient = card.get("ambient_stage") if isinstance(card.get("ambient_stage"), dict) else {}
        clean = str(ambient.get("暗处") or "").strip() or "街对面树影里像有个人在看这一幕——后背发紧。"
        share_to = {"C.zhangchen.WMAIN": clean}
    return {
        "audience": "director_only" if not player_visible else audience,
        "player_visible": player_visible,
        "share_to": {str(k): str(v).strip() for k, v in share_to.items() if str(v).strip()},
        "director_text": str(authored.get("director_text") or text).strip(),
    }


def annotate_turn(
    turn: dict[str, Any],
    *,
    audience: str = "player",
    canon_status: str = "adaptation",
    provenance: dict[str, Any] | None = None,
    actor_visible_to: list[str] | None = None,
    player_visible: bool | None = None,
) -> dict[str, Any]:
    out = dict(turn)
    out["audience"] = audience
    if player_visible is None:
        out["player_visible"] = audience in {"player", "mixed"}
    else:
        out["player_visible"] = bool(player_visible)
    if actor_visible_to is not None:
        out["actor_visible_to"] = list(actor_visible_to)
    elif audience == "actors":
        out["actor_visible_to"] = list(turn.get("actor_visible_to", []))
    elif audience in {"player", "mixed"} and out["player_visible"]:
        out["actor_visible_to"] = ["*"]
    else:
        out["actor_visible_to"] = []
    out["canon_status"] = canon_status
    if provenance:
        out["provenance"] = provenance
    return out


def turns_audible_to_actor(history: list[dict[str, Any]], actor_cons: str) -> list[dict[str, Any]]:
    """公开台词 + 显式分发给该演员的导演感知（不含别人私有）。

    本场玩家说过的话必须可听：否则「已经答应借视频」会在下一拍被忘掉。
    默认保留本场最近窗口（足够覆盖开场全段，又不把跨场灌进稳定前缀）。
    """
    out: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        targets = item.get("actor_visible_to")
        role = item.get("role")
        if targets is None:
            # 旧档：npc/bridge/player/公开旁白默认同场可听
            if role in {"npc", "bridge", "player", "narrate"}:
                out.append(
                    {
                        "speaker": str(item.get("speaker", "")).strip(),
                        "text": text,
                        "stage": str(item.get("stage", "")).strip(),
                        "turn": item.get("turn"),
                        "channel": "public",
                    }
                )
            continue
        targets = [str(t) for t in targets]
        if "*" in targets or actor_cons in targets:
            channel = "private_perception" if role == "director_note" or item.get("audience") == "director_only" else "public"
            out.append(
                {
                    "speaker": str(item.get("speaker", "")).strip() or ("感知" if channel == "private_perception" else ""),
                    "text": text,
                    "stage": str(item.get("stage", "")).strip(),
                    "turn": item.get("turn"),
                    "channel": channel,
                }
            )
    return out[-48:]


_SCENE_LOCATION_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("school_gate", ("校门口", "十六中校门")),
    ("school_classroom", ("教室", "年级晨会")),
    ("weichu_office", ("办公室", "魏初")),
    ("milktea_shop", ("快乐柠檬", "奶茶店")),
    ("beijing_station", ("火车站", "站台")),
    ("highway", ("高速", "京津")),
)


def _scene_bucket_for_location(location: str) -> str:
    text = str(location or "")
    for bucket, hints in _SCENE_LOCATION_HINTS:
        if any(hint in text for hint in hints):
            return bucket
    return "other"


def _natural_time_window(bucket: str, relation: str) -> str:
    if bucket == "weichu_office":
        return "当天早晨"
    if bucket == "school_classroom":
        return "当天早晨·上课前后"
    if bucket == "school_gate":
        return "放学后"
    if bucket == "milktea_shop":
        return "放学后不久"
    if bucket in {"beijing_station", "highway"}:
        if relation in {"overlapping", "unknown"}:
            return "傍晚前后·时段关系待定"
        return "返津途中"
    return "时段待定"


def _relation_to_current(bucket: str, current_bucket: str) -> str:
    if not current_bucket or current_bucket == "other":
        return "unknown"
    if bucket == current_bucket:
        return "overlapping"
    past_of = {
        "school_gate": {"weichu_office", "school_classroom"},
        "milktea_shop": {"weichu_office", "school_classroom", "school_gate"},
        "hospital": {"weichu_office", "school_classroom", "school_gate", "milktea_shop"},
    }
    future_of = {
        "school_gate": {"milktea_shop", "hospital"},
        "milktea_shop": {"hospital"},
        "weichu_office": {"school_gate", "milktea_shop", "highway", "beijing_station"},
    }
    if bucket in past_of.get(current_bucket, set()):
        return "past"
    if bucket in future_of.get(current_bucket, set()):
        return "future"
    if bucket in {"highway", "beijing_station"} and current_bucket in {
        "school_gate",
        "milktea_shop",
        "hospital",
    }:
        return "unknown"
    return "unknown"


def project_world_events(
    ch_anchor: int,
    present_cons: list[str] | None = None,
    *,
    current_location: str | None = None,
    current_scene_id: str | None = None,
) -> dict[str, Any]:
    """场级世界态势：按地点/场景分组，并标 past / overlapping / future / unknown。"""
    present_cons = list(present_cons or [])
    scene_hint = " ".join(
        part for part in (str(current_location or ""), str(current_scene_id or "")) if part
    )
    current_bucket = _scene_bucket_for_location(scene_hint)
    if "16ZHONG" in str(current_scene_id or "").upper() or "GATE" in str(current_scene_id or "").upper():
        current_bucket = "school_gate"
    elif "MILKTEA" in str(current_scene_id or "").upper():
        current_bucket = "milktea_shop"
    elif "HOSPITAL" in str(current_scene_id or "").upper():
        current_bucket = "hospital"

    director_events: list[dict[str, Any]] = []
    scenes: dict[str, dict[str, Any]] = {}
    if not DB_PATH.exists():
        return {
            "director_world_state": director_events,
            "scenes": [],
            "live_scene": [],
            "near_offscreen": [],
            "past_same_chapter": [],
            "player_observed_world": [],
            "actor_world_signals": {},
            "current_bucket": current_bucket,
        }
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            "SELECT ch_anchor, location_id, payload FROM events WHERE run=0 AND ch_anchor=?",
            (int(ch_anchor),),
        )
        for ch, location_id, payload in cur.fetchall():
            data = json.loads(payload)
            uid = str(data.get("event_uid", "")).strip()
            if not uid:
                continue
            location = location_id or data.get("location") or "待补地点"
            bucket = _scene_bucket_for_location(str(location))
            relation = _relation_to_current(bucket, current_bucket)
            precision = "causal_only" if relation == "unknown" else "bounded"
            natural_time = _natural_time_window(bucket, relation)
            row = {
                "event_uid": uid,
                "ch_anchor": ch,
                "location": location,
                "scene_uid": bucket,
                "action": data.get("action"),
                "witnesses": list(data.get("witnesses") or []),
                "relation_to_current": relation,
                "status": relation,
                "time_precision": precision,
                "natural_time_window": natural_time,
                "visibility": "director",
            }
            director_events.append(row)
            scene = scenes.setdefault(
                bucket,
                {
                    "scene_uid": bucket,
                    "location": location,
                    "natural_time_window": natural_time,
                    "relation_to_current": relation,
                    "precision": precision,
                    "event_uids": [],
                    "cast": [],
                },
            )
            scene["event_uids"].append(uid)
            for witness in row["witnesses"]:
                if witness not in scene["cast"]:
                    scene["cast"].append(witness)
        conn.close()
    except Exception:
        director_events = []
        scenes = {}

    scene_rows = list(scenes.values())
    live_scene = [s for s in scene_rows if s["relation_to_current"] == "overlapping"]
    near_offscreen = [s for s in scene_rows if s["relation_to_current"] in {"unknown", "future"}]
    past_same_chapter = [s for s in scene_rows if s["relation_to_current"] == "past"]

    actor_signals: dict[str, list[dict[str, Any]]] = {}
    for cons in present_cons:
        actor_signals[cons] = [
            ev
            for ev in director_events
            # A same-chapter future event is a director timeline record, not
            # an actor perception.  Unknown timing is likewise withheld until
            # a scene-local cue establishes it.
            if cons in ev.get("witnesses", [])
            and ev.get("relation_to_current") == "overlapping"
        ]
    return {
        "director_world_state": director_events,
        "scenes": scene_rows,
        "live_scene": live_scene,
        "near_offscreen": near_offscreen,
        "past_same_chapter": past_same_chapter,
        "player_observed_world": [],
        "actor_world_signals": actor_signals,
        "current_bucket": current_bucket,
    }


def load_w2_tables() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, rel in (
        ("heart_gate_tables", "runtime/heart_gate_tables.json"),
        ("offscreen_schedules", "runtime/offscreen_schedules.json"),
        ("handoff_rules", "runtime/handoff_rules.json"),
    ):
        path = ROOT / rel
        if path.exists():
            try:
                out[key] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                out[key] = {}
    return out
