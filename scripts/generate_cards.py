# -*- coding: utf-8 -*-
"""Storylet / free_stage card compiler.

Two modes:
1. `generate_draft` — DB-projected draft skeleton (`status=draft_needs_human`).
   Must-happen / exits / locks stay ★★★ until human cut; engine refuses to load.
2. `compile_opening_overlay` — for the two human-approved opening cards: keep
   authored MH/exits/locks/scene, refresh knowledge_gate + compiler stamp from DB.
   Playable surface remains the authored card; pipeline is observable.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
OPENING_AUTHORED: dict[str, Path] = {
    "OPENING_RYUYA_PROLOGUE_001": ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
    "OPENING_TIANANMEN_002": ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
}

SPOILER_SURFACE_TERMS = ("世界政府", "RTW", "LT", "时空机器", "狙击手", "枪击")
BOOKMARK_RE = re.compile(r"(Chapter|第\s*\d+\s*章|原著|L\d+)", re.I)


def normalize_character(name: str) -> str:
    name = name.strip()
    if name.startswith("C."):
        return name
    mapping = {
        "kakashi": "C.kakashi.WMAIN",
        "akito": "C.akito.WMAIN",
        "xiuzai": "C.xiuzai.WMAIN",
        "maki": "C.maki.WMAIN",
        "ryuya": "C.ryuya.W1",
        "坂本晴明": "C.kakashi.WMAIN",
        "卡卡西": "C.kakashi.WMAIN",
        "川口秋人": "C.akito.WMAIN",
        "秋人": "C.akito.WMAIN",
        "折原修哉": "C.xiuzai.WMAIN",
        "修哉": "C.xiuzai.WMAIN",
        "折原真纪": "C.maki.WMAIN",
        "真纪": "C.maki.WMAIN",
        "折原龙也": "C.ryuya.W1",
        "龙也": "C.ryuya.W1",
    }
    return mapping.get(name.lower(), mapping.get(name, f"C.{name}.WMAIN"))


def get_display_name(cons_id: str) -> str:
    mapping = {
        "C.kakashi.WMAIN": "坂本晴明",
        "C.akito.WMAIN": "川口秋人",
        "C.xiuzai.WMAIN": "折原修哉",
        "C.maki.WMAIN": "折原真纪",
        "C.ryuya.W1": "折原龙也",
        "C.ryuya.WMAIN": "折原龙也",
    }
    if cons_id in mapping:
        return mapping[cons_id]
    parts = cons_id.split(".")
    return parts[1] if len(parts) >= 2 else cons_id


def _compact_excerpt_text(text: str) -> str:
    text = text.replace("\f", "\n")
    return re.sub(r"\s+", " ", text).strip()


def build_scene_source_excerpt(ch_anchor: int, source_path: str | Path = "source/chapters.json") -> dict[str, str]:
    path = Path(source_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return {"氛围片段": "★★★ 未找到 source/chapters.json；请人工补入本场原著氛围段。"}
    try:
        chapters = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"氛围片段": f"★★★ 读取 source/chapters.json 失败：{exc}"}
    raw = str(chapters.get(str(ch_anchor)) or "")
    if not raw.strip():
        return {"氛围片段": f"★★★ 未找到 ch_anchor={ch_anchor} 的原著章节文本；请人工补入。"}
    candidates: list[str] = []
    for para in re.split(r"\n\s*\n", raw):
        text = _compact_excerpt_text(para)
        if not text or BOOKMARK_RE.search(text):
            continue
        if "“" in text or "”" in text:
            continue
        if 36 <= len(text) <= 180:
            candidates.append(text)
    if not candidates:
        fallback = _compact_excerpt_text(raw)[:180]
        candidates = [BOOKMARK_RE.sub("", fallback).strip()]
    return {"氛围片段": candidates[0]}


def project_knowledge_gate(
    characters: list[str],
    ch_anchor: int,
    db_path: str | Path,
) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT prop_id, statement, spoiler_tier FROM propositions")
    props = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    known_props: set[str] = set()
    for char in characters:
        cur.execute(
            "SELECT prop_id, learn_ch FROM knowledge_schedule WHERE cons_id = ?",
            (char,),
        )
        for prop_id, learn_ch in cur.fetchall():
            if prop_id in props and int(learn_ch or 0) <= int(ch_anchor):
                known_props.add(props[prop_id][0])
    conn.close()
    known_list = sorted(known_props)
    prompt_safe = [
        item for item in known_list if not any(term in item for term in SPOILER_SURFACE_TERMS)
    ]
    return [
        f"【此刻知道】角色只可自然谈论 ch<={ch_anchor} 已解锁知识。",
        f"【此刻知道·可自然谈】{', '.join(prompt_safe) if prompt_safe else '（本章无额外库投影条目）'}。",
        "【自然不谈】未亲历、未被告知、未到 learn_ch 的事不会主动提起；未来剧透词由引擎侧 spoiler_gate 拦截。",
    ]


def generate_draft(
    scene_id: str,
    ch_anchor: int,
    characters: list[str],
    events: list[str],
    db_path: str = "data/world_truth.db",
) -> dict[str, Any]:
    db = Path(db_path)
    if not db.is_absolute():
        db = ROOT / db
    normalized_chars = [normalize_character(c) for c in characters if c.strip()]
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()

    must_happen_list: list[dict[str, Any]] = []
    for ev_id in events:
        ev_id = ev_id.strip()
        if not ev_id:
            continue
        found = False
        for eid, payload_str in cur.execute("SELECT event_id, payload FROM events"):
            try:
                payload = json.loads(payload_str)
            except Exception:
                payload = {}
            if str(eid) == ev_id or payload.get("event_uid") == ev_id:
                found = True
                must_happen_list.append(
                    {
                        "id": f"★★★ {payload.get('event_uid', str(eid))}",
                        "desc": f"★★★ {payload.get('action', '未知事件行动')}",
                        "evidence": f"★★★ {payload.get('canon_src', '未知出处')}",
                        "after": [],
                    }
                )
                break
        if not found:
            must_happen_list.append(
                {
                    "id": f"★★★ {ev_id}",
                    "desc": "★★★ 无法从数据库中检索到该事件 action 描述，请手动补充",
                    "evidence": "★★★ 无法从数据库中检索到该事件 evidence 出处，请手动补充",
                    "after": [],
                }
            )

    locks_list = [
        "无戏外概念：不提系统、剧本、玩家、AI、模型、prompt、must_happen、canon、分支、节点。"
    ]
    for char in normalized_chars:
        try:
            cur.execute(
                "SELECT lock_id, locked_text, context, ch_ref FROM canon_locks "
                "WHERE speaker_cons = ? AND ch_ref <= ?",
                (char, ch_anchor),
            )
            for _lock_id, locked_text, context, ch_ref in cur.fetchall():
                locks_list.append(
                    f"【正典锁化】{get_display_name(char)} 在 Ch.{ch_ref} 下的锁定台词："
                    f"'{locked_text}' (语境: {context})"
                )
        except sqlite3.Error:
            pass
    conn.close()

    persona_cards_dict: dict[str, Any] = {}
    for char in normalized_chars:
        persona_cards_dict[char] = {
            "name": get_display_name(char),
            "boundaries": {},
            "constraints": [
                "★★★ 本库无 persona_core 文件时，边界与决策规约待人裁或 Seed 投影补入。"
            ],
            "voice_samples": [],
            "voice_gap": ["★★★ 本库无 voice_bank；声纹抽样跳过。"],
            "inner_state": {
                "want_now": "★★★ 待按原著补入此刻目标",
                "knot": "★★★ 待按原著补入心结",
                "unsaid": "",
                "stance_to_player": "中性",
            },
        }

    return {
        "status": "draft_needs_human",
        "scene_id": scene_id,
        "scene": "★★★ 待人裁场景名称",
        "pacing": "standard",
        "ch_anchor": ch_anchor,
        "scene_frame": {
            "location": "★★★ 待人裁地点描述",
            "scene_label": "★★★ 待人裁场景标签",
            "time_of_day": "★★★ 待人裁时间",
            "blurb": "★★★ 待人裁开场旁白",
            "init_stage": "★★★ 待人裁初始舞台指示",
            "cons_present": normalized_chars,
            "background_context": ["★★★ 待填入当前场景的上下文背景"],
        },
        "scene_source_excerpt": build_scene_source_excerpt(ch_anchor),
        "exits": [
            {
                "target_card": "★★★ 待人裁目标卡路径",
                "trigger": "★★★ 待人裁转场触发条件描述",
                "bridge_hint": "★★★ 待人裁转场旁白提示",
            }
        ],
        "memory_layers": {
            "context_memory": ["★★★ 待填入当前场景的上下文背景"],
            "relationship_memory": ["★★★ 待填入当前人际关系演变背景"],
            "knowledge_gate": project_knowledge_gate(normalized_chars, ch_anchor, db),
        },
        "must_happen": must_happen_list,
        "locks": locks_list,
        "persona_cards": persona_cards_dict,
        "compiler": {"mode": "draft", "version": "2026-08-03"},
    }


def compile_opening_overlay(
    scene_id: str,
    *,
    db_path: str | Path | None = None,
    authored_path: Path | None = None,
) -> dict[str, Any]:
    """Refresh DB-projected layers onto a human-approved opening card.

    Does not invent must_happen / exits / locks. Marks compiler.mode=authored_overlay.
    """
    sid = str(scene_id).strip()
    path = Path(authored_path) if authored_path else OPENING_AUTHORED.get(sid)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"no authored opening card for {sid}")
    card = json.loads(path.read_text(encoding="utf-8"))
    if card.get("status") == "draft_needs_human":
        raise ValueError("authored opening card must not be draft_needs_human")
    db = Path(db_path or (ROOT / "data" / "world_truth.db"))
    chars = [str(c) for c in (card.get("present") or []) if str(c).strip()]
    if not chars:
        chars = [str(k) for k in (card.get("persona_cards") or {}) if str(k).strip()]
    ch_anchor = int(card.get("ch_anchor", 0) or 0)
    layers = dict(card.get("memory_layers") or {})
    # Keep authored knowledge_gate text if present; append compiler receipt line.
    authored_gate = list(layers.get("knowledge_gate") or [])
    projected = project_knowledge_gate(chars, ch_anchor, db)
    layers["knowledge_gate"] = authored_gate or projected
    layers["knowledge_gate_projected"] = projected
    card["memory_layers"] = layers
    card["compiler"] = {
        "mode": "authored_overlay",
        "version": "2026-08-03",
        "scene_id": sid,
        "source_path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "mh_ids": [
            str(item.get("id"))
            for item in (card.get("must_happen") or [])
            if isinstance(item, dict) and item.get("id")
        ],
        "projected_chars": chars,
    }
    card["_compiler"] = dict(card["compiler"])
    return card


def stamp_opening_card_in_memory(card: dict[str, Any], *, db_path: str | Path | None = None) -> dict[str, Any]:
    """Session-load stamp: same overlay without rewriting the on-disk JSON."""
    if not isinstance(card, dict):
        return card
    sid = str(card.get("scene_id") or "").strip()
    if sid not in OPENING_AUTHORED:
        return card
    if (card.get("compiler") or {}).get("mode") == "authored_overlay":
        return card
    try:
        overlaid = compile_opening_overlay(sid, db_path=db_path)
    except Exception:
        out = dict(card)
        out["compiler"] = {"mode": "authored_overlay", "version": "2026-08-03", "degraded": True}
        out["_compiler"] = dict(out["compiler"])
        return out
    # Preserve any runtime mutations already on the live card (fronting, etc.).
    merged = dict(overlaid)
    for key in ("present", "_fronting_select", "_fronting_runtime", "persona_cards"):
        if key in card:
            merged[key] = card[key]
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="free_stage card compiler")
    sub = parser.add_subparsers(dest="cmd", required=True)

    draft = sub.add_parser("draft", help="Generate draft_needs_human skeleton")
    draft.add_argument("--scene-id", required=True)
    draft.add_argument("--ch-anchor", type=int, required=True)
    draft.add_argument("--characters", required=True)
    draft.add_argument("--events", required=True)
    draft.add_argument("--db-path", default=str(ROOT / "data" / "world_truth.db"))
    draft.add_argument("--output")

    opening = sub.add_parser("opening", help="Compile authored opening overlay")
    opening.add_argument("--scene-id", required=True, choices=sorted(OPENING_AUTHORED))
    opening.add_argument("--db-path", default=str(ROOT / "data" / "world_truth.db"))
    opening.add_argument("--output")

    args = parser.parse_args()
    if args.cmd == "draft":
        chars = [c.strip() for c in args.characters.split(",") if c.strip()]
        evs = [e.strip() for e in args.events.split(",") if e.strip()]
        payload = generate_draft(args.scene_id, args.ch_anchor, chars, evs, args.db_path)
        out = Path(args.output) if args.output else ROOT / "runtime" / "card_drafts" / f"{args.scene_id.lower()}_draft.json"
    else:
        payload = compile_opening_overlay(args.scene_id, db_path=args.db_path)
        out = Path(args.output) if args.output else ROOT / "runtime" / "card_drafts" / f"{args.scene_id.lower()}_overlay.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
