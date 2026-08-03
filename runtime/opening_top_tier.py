# -*- coding: utf-8 -*-
"""Opening two-scene top-tier wiring helpers (龙也序幕 × 天安门).

Forces isolated ActorPacket play path and fills FSM / RelState / KGE / cos+emo
gaps that assembly_projection previously listed as deferred.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from runtime.npc_fsm import NpcFSM

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "data" / "world_truth.db"

OPENING_TOP_TIER_SCENES = frozenset(
    {
        "OPENING_RYUYA_PROLOGUE_001",
        "OPENING_TIANANMEN_002",
    }
)

# Design-doc retrieve weights (npc_test_client)
_W1, _W2, _W3 = 0.6, 0.3, 0.1

_DEFAULT_FSM: dict[str, dict[str, Any]] = {
    "C.ryuya.W1": {"trust": 72, "intimacy": 58, "alert": 18, "state": "open", "violations": 0},
    "C.xiuzai.WMAIN": {"trust": 48, "intimacy": 22, "alert": 28, "state": "open", "violations": 0},
    "C.maki.WMAIN": {"trust": 50, "intimacy": 25, "alert": 22, "state": "open", "violations": 0},
    "C.kakashi.WMAIN": {"trust": 42, "intimacy": 18, "alert": 35, "state": "probing", "violations": 0},
    "C.akito.WMAIN": {"trust": 55, "intimacy": 28, "alert": 20, "state": "open", "violations": 0},
}

_DEFAULT_REL: dict[str, dict[str, Any]] = {
    "C.ryuya.W1": {
        "to_player": {
            "closeness": 0.72,
            "wariness": 0.12,
            "label": "两年朋友",
            "stage": "S2",
        }
    },
    "C.xiuzai.WMAIN": {
        "to_player": {"closeness": 0.15, "wariness": 0.35, "label": "初遇陌生人", "stage": "S0"}
    },
    "C.maki.WMAIN": {
        "to_player": {"closeness": 0.18, "wariness": 0.28, "label": "初遇陌生人", "stage": "S0"}
    },
    "C.kakashi.WMAIN": {
        "to_player": {"closeness": 0.12, "wariness": 0.40, "label": "戒备初遇", "stage": "S0"}
    },
    "C.akito.WMAIN": {
        "to_player": {"closeness": 0.20, "wariness": 0.25, "label": "初遇陌生人", "stage": "S0"}
    },
}


def is_opening_top_tier_scene(card: dict[str, Any] | None) -> bool:
    if not isinstance(card, dict):
        return False
    return str(card.get("scene_id") or "").strip() in OPENING_TOP_TIER_SCENES


def ensure_fsm_map(
    fsm_by_cons: dict[str, Any] | None,
    present: list[str],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    src = fsm_by_cons if isinstance(fsm_by_cons, dict) else {}
    for cons in present:
        cons = str(cons).strip()
        if not cons:
            continue
        raw = src.get(cons) if isinstance(src.get(cons), dict) else None
        seed = dict(_DEFAULT_FSM.get(cons) or {"trust": 50, "intimacy": 25, "alert": 25, "state": "open", "violations": 0})
        if raw:
            seed.update({k: raw[k] for k in ("trust", "intimacy", "alert", "state", "violations") if k in raw})
        out[cons] = seed
    return out


def ensure_rel_map(
    rel_by_cons: dict[str, Any] | None,
    present: list[str],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    src = rel_by_cons if isinstance(rel_by_cons, dict) else {}
    for cons in present:
        cons = str(cons).strip()
        if not cons:
            continue
        raw = src.get(cons) if isinstance(src.get(cons), dict) else None
        seed = dict(_DEFAULT_REL.get(cons) or {"to_player": {"closeness": 0.2, "wariness": 0.3, "label": "关系未标", "stage": "S0"}})
        if raw:
            seed = {**seed, **raw}
            if isinstance(raw.get("to_player"), dict):
                seed["to_player"] = {**(seed.get("to_player") or {}), **raw["to_player"]}
        out[cons] = seed
    return out


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s", "", s or "")
    if len(s) <= 1:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def cos_sim(a: str, b: str) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / ((len(A) ** 0.5) * (len(B) ** 0.5))


def score_slow_memory_cos_emo(
    candidates: list[dict[str, Any]],
    query: str,
    emo_tag: str = "",
    *,
    top_k: int = 2,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    smax = max(float(m.get("salience") or 0.5) for m in candidates) or 1.0
    target = str(emo_tag or "").strip()
    scored: list[tuple[float, dict[str, Any]]] = []
    for m in candidates:
        text = str(m.get("text") or "")
        anchor = str(m.get("anchor") or m.get("sensory_anchor") or "")
        sc = (
            _W1 * cos_sim(query, text + anchor)
            + _W2 * (1.0 if target and target == str(m.get("emo_tag") or "") else 0.0)
            + _W3 * (float(m.get("salience") or 0.5) / smax)
        )
        row = dict(m)
        row["_retrieve_score"] = round(sc, 4)
        scored.append((sc, row))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:top_k]]


def merge_slow_activations(
    cue_activated: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    *,
    max_n: int = 4,
) -> list[dict[str, Any]]:
    """Cue wins first (交坠/RP); cos+emo fills remaining slots."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _key(item: dict[str, Any]) -> str:
        return str(item.get("mem_id") or item.get("id") or item.get("text") or "")[:120]

    for item in cue_activated:
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        row = dict(item)
        row["_activation"] = row.get("_activation") or "cue"
        out.append(row)
        if len(out) >= max_n:
            return out
    for item in scored:
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        row = dict(item)
        row["_activation"] = "cos_emo"
        out.append(row)
        if len(out) >= max_n:
            break
    return out


def kge_slice(
    cons_id: str,
    chapter: int,
    *,
    db_path: str | Path | None = None,
    top_knows: int = 6,
) -> dict[str, Any]:
    """Assemble KnowledgeGateEngine knows + blocked keywords for disclosure."""
    path = str(db_path or DB_DEFAULT)
    try:
        from runtime.knowledge_gate_engine import KnowledgeGateEngine
    except Exception:
        from knowledge_gate_engine import KnowledgeGateEngine  # type: ignore

    eng = KnowledgeGateEngine(path)
    try:
        state = eng.query(cons_id, int(chapter))
        slice_obj = eng.assemble_context_slice(cons_id, int(chapter))
        slice_txt = ""
        if isinstance(slice_obj, dict):
            slice_txt = str(slice_obj.get("inject_text") or "")
        elif slice_obj:
            slice_txt = str(slice_obj)
        knows = list(state.get("knows") or [])[:top_knows]
        blocked = list(state.get("does_NOT_know") or [])
        policy = [
            f"门控封锁（勿提及）: {pid}"
            for pid in blocked[:12]
        ]
        if slice_txt:
            policy.insert(0, "知识门控切片已装配；只陈述你已解锁的事实。")
        return {
            "knows": knows,
            "blocked_prop_ids": blocked,
            "disclosure_lines": policy,
            "slice_text": slice_txt or "",
            "engine": "KnowledgeGateEngine",
        }
    finally:
        eng.close()


def validate_output_kge(
    cons_id: str,
    chapter: int,
    text: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    path = str(db_path or DB_DEFAULT)
    try:
        from runtime.knowledge_gate_engine import KnowledgeGateEngine
    except Exception:
        from knowledge_gate_engine import KnowledgeGateEngine  # type: ignore

    eng = KnowledgeGateEngine(path)
    try:
        return eng.validate_output(cons_id, int(chapter), text or "")
    finally:
        eng.close()


def validate_turns_kge(
    cons_id: str,
    chapter: int,
    turns: list[dict[str, Any]],
    *,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    blob = " ".join(
        f"{t.get('text') or ''} {t.get('stage') or ''}"
        for t in turns
        if isinstance(t, dict)
    )
    result = validate_output_kge(cons_id, chapter, blob, db_path=db_path)
    if result.get("result") == "PASS":
        return []
    return [
        {
            "kind": "kge_leak",
            "severity": result.get("result"),
            "cons": cons_id,
            "violations": result.get("violations") or [],
        }
    ]


def tick_fsm(
    fsm_row: dict[str, Any],
    *,
    player_speech: str = "",
    player_action: str = "",
    hostile_hint: bool = False,
) -> dict[str, Any]:
    fsm = NpcFSM(
        trust=int(fsm_row.get("trust", 50) or 50),
        intimacy=int(fsm_row.get("intimacy", 25) or 25),
        alert=int(fsm_row.get("alert", 25) or 25),
        state=str(fsm_row.get("state") or "open"),
    )
    fsm.violations = int(fsm_row.get("violations") or 0)
    text = f"{player_speech} {player_action}"
    d_trust = d_int = d_alert = 0
    violation = False
    if hostile_hint or any(tok in text for tok in ("滚开", "去死", "骗子", "报警", "骗子")):
        d_trust, d_alert, violation = -8, 12, True
    elif any(tok in text for tok in ("谢谢", "拜托", "相信", "朋友", "挂坠", "接过")):
        d_trust, d_int, d_alert = 3, 2, -2
    elif text.strip():
        d_trust, d_int = 1, 1
    fsm.apply(d_trust=d_trust, d_int=d_int, d_alert=d_alert, violation=violation)
    return {
        "trust": fsm.trust,
        "intimacy": fsm.intimacy,
        "alert": fsm.alert,
        "state": fsm.state,
        "violations": fsm.violations,
    }


def tick_rel(
    rel_row: dict[str, Any],
    *,
    player_speech: str = "",
    player_action: str = "",
) -> dict[str, Any]:
    out = dict(rel_row)
    tp = dict(out.get("to_player") or {})
    closeness = float(tp.get("closeness") or 0.2)
    wariness = float(tp.get("wariness") or 0.3)
    text = f"{player_speech} {player_action}"
    if any(tok in text for tok in ("谢谢", "帮忙", "一起", "朋友", "挂坠")):
        closeness = min(1.0, closeness + 0.03)
        wariness = max(0.0, wariness - 0.02)
    elif any(tok in text for tok in ("滚", "骗子", "别碰", "走开")):
        closeness = max(0.0, closeness - 0.05)
        wariness = min(1.0, wariness + 0.08)
    tp["closeness"] = round(closeness, 3)
    tp["wariness"] = round(wariness, 3)
    out["to_player"] = tp
    return out


# Scene → fronting_canon.scene keyword hints (B5 rows; do not invent new fc).
_SCENE_FRONTING_HINTS: dict[str, tuple[str, ...]] = {
    "OPENING_RYUYA_PROLOGUE_001": ("与玩家", "临终", "叮嘱", "交情", "日常温柔"),
}


def resolve_fronting_cons(body_id: str, *, db_path: str | Path | None = None) -> str | None:
    """Backward-compatible wrapper: scene-less single-cons pin only."""
    return select_fronting_cons(body_id, db_path=db_path)


def select_fronting_cons(
    body_id: str,
    *,
    scene_id: str | None = None,
    ch_ref: str | None = None,
    hint: str | None = None,
    prefer_cons: str | None = None,
    db_path: str | Path | None = None,
) -> str | None:
    """Pick fronting consciousness from fronting_canon for a multi-soul body.

    Scoring uses scene_id hints / free-text hint / ch_ref overlap against the
    B5-cut `scene` and `ch_ref` columns. Never invents fc rows.
    """
    path = Path(db_path or DB_DEFAULT)
    body = str(body_id or "").strip()
    if not body or not path.is_file():
        return None
    try:
        con = sqlite3.connect(str(path))
        rows = con.execute(
            "SELECT scene, ch_ref, fronting_cons FROM fronting_canon WHERE body_id=?",
            (body,),
        ).fetchall()
        occupants = [
            str(r[0])
            for r in con.execute(
                "SELECT cons_id FROM occupancy WHERE body_id=?",
                (body,),
            ).fetchall()
            if r and r[0]
        ]
        con.close()
    except sqlite3.Error:
        return None
    if not rows:
        if len(occupants) == 1:
            return occupants[0]
        return str(prefer_cons).strip() or None

    distinct = {str(r[2]).strip() for r in rows if r and r[2]}
    if len(distinct) == 1:
        return next(iter(distinct))

    hints = list(_SCENE_FRONTING_HINTS.get(str(scene_id or "").strip(), ()))
    if hint:
        hints.extend(tok for tok in re.split(r"[\s,，、]+", str(hint)) if tok)
    ch_needle = str(ch_ref or "").strip()
    scored: list[tuple[int, str]] = []
    for scene_txt, ch_txt, cons in rows:
        cons_s = str(cons or "").strip()
        if not cons_s:
            continue
        blob = f"{scene_txt or ''}\n{ch_txt or ''}"
        score = sum(1 for tok in hints if tok and tok in blob)
        if ch_needle and ch_needle in str(ch_txt or ""):
            score += 2
        if prefer_cons and cons_s == prefer_cons:
            score += 1
        scored.append((score, cons_s))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score = scored[0][0]
    if best_score <= 0 and prefer_cons:
        return str(prefer_cons).strip()
    if best_score <= 0 and str(scene_id or "") == "OPENING_RYUYA_PROLOGUE_001":
        for _score, cons_s in scored:
            if cons_s.endswith(".W1"):
                return cons_s
    return scored[0][1]


def body_id_for_cons(cons_id: str, *, db_path: str | Path | None = None) -> str | None:
    path = Path(db_path or DB_DEFAULT)
    cons = str(cons_id or "").strip()
    if not cons or not path.is_file():
        return None
    try:
        con = sqlite3.connect(str(path))
        row = con.execute(
            "SELECT body_id FROM occupancy WHERE cons_id=? ORDER BY occ_id LIMIT 1",
            (cons,),
        ).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    return str(row[0]) if row and row[0] else None


def apply_fronting_to_card(
    card: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Runtime fronting select for opening cards; keep card present as safety pin.

    For dual-consciousness bodies, replace present cons with the selected fronting
    when the card pin disagrees. Records `_fronting_select` for the observatory.
    """
    if not isinstance(card, dict) or not is_opening_top_tier_scene(card):
        return card
    out = dict(card)
    present = [str(c).strip() for c in (out.get("present") or []) if str(c).strip()]
    personas = dict(out.get("persona_cards") or {})
    receipts: list[dict[str, Any]] = []
    seen_bodies: set[str] = set()
    new_present: list[str] = []
    for cons in present:
        body = body_id_for_cons(cons, db_path=db_path)
        if not body or body in seen_bodies:
            new_present.append(cons)
            continue
        seen_bodies.add(body)
        selected = select_fronting_cons(
            body,
            scene_id=str(out.get("scene_id") or ""),
            prefer_cons=cons,
            db_path=db_path,
        )
        chosen = selected or cons
        receipts.append(
            {
                "body_id": body,
                "card_pin": cons,
                "selected": chosen,
                "matched_pin": chosen == cons,
                "source": "fronting_canon",
            }
        )
        if chosen != cons and chosen in personas:
            new_present.append(chosen)
        elif chosen != cons and cons in personas and chosen not in personas:
            # Pin wrong but persona only under pin: keep pin (safety), note mismatch.
            receipts[-1]["matched_pin"] = False
            receipts[-1]["kept_pin_reason"] = "persona_cards missing selected cons"
            new_present.append(cons)
        else:
            new_present.append(chosen if chosen else cons)
    # Dedupe preserve order
    deduped: list[str] = []
    for cons in new_present:
        if cons not in deduped:
            deduped.append(cons)
    out["present"] = deduped
    out["_fronting_select"] = receipts
    out["_fronting_runtime"] = True
    return out


def assembly_top_tier_status(
    *,
    present: list[str],
    body_frame_bodies: list[str],
    pendant_layer_c_emitted: bool,
    pendant_look_emitted: bool,
    pendant_accepted: bool,
    actor_isolation: bool,
    kge: bool,
    cos_emo: bool,
    fsm: bool,
    rel_state: bool,
    fronting: bool = False,
    generate_cards: bool = False,
    beta_threshold: bool = False,
) -> dict[str, Any]:
    wired = [
        "Seed.ARCH/MANNER/BOUNDARY",
        "Seed.REL.IDENTITY+HOLD",
        "Seed.P.ACT",
        "session.BodyFrame",
        "want/inner(card→session)",
        "slow_memory.cue",
        "pendant_layer_c",
        "tiananmen_secret_leak_gate",
    ]
    if actor_isolation:
        wired.append("actor_context_isolation→call_actor_packet")
    if kge:
        wired.append("KnowledgeGateEngine unify")
    if cos_emo:
        wired.append("slow_memory cos+emo Top-K")
    if fsm:
        wired.append("FSM/session affect")
    if rel_state:
        wired.append("RelState(session)")
    if fronting:
        wired.append("fronting_canon runtime select")
    if generate_cards:
        wired.append("Storylet generate_cards overlay")
    if beta_threshold:
        wired.append("β soft→director threshold")
    deferred: list[str] = []
    top = (
        actor_isolation
        and kge
        and cos_emo
        and fsm
        and rel_state
        and fronting
        and generate_cards
        and beta_threshold
    )
    return {
        "scope": "opening_two_scenes",
        "top_tier": top,
        "wired_now": wired,
        "deferred_not_top_tier": deferred,
        "present_cons": present,
        "body_frame_bodies": body_frame_bodies,
        "pendant_layer_c_emitted": pendant_layer_c_emitted,
        "pendant_look_emitted": pendant_look_emitted,
        "pendant_accepted": pendant_accepted,
    }
