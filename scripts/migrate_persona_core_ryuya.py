#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3 batch C (ryuya vertical): persona core → P.VOICE/P.BOUNDARY/P.MANNER + schedule.

Source: free_stage_card_ryuya_prologue.json + runtime/personas/C.ryuya.W1.md
         + runtime/persona_constraints.json — no new plot invented.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "world_truth.db"
CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
PERSONA_MD = ROOT / "runtime" / "personas" / "C.ryuya.W1.md"
CONSTRAINTS = ROOT / "runtime" / "persona_constraints.json"
CONS = "C.ryuya.W1"


def build_rows() -> list[dict[str, str | int]]:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pc = card["persona_cards"][CONS]
    rows: list[dict[str, str | int]] = []

    for i, sample in enumerate(pc.get("voice_samples") or [], start=1):
        text = str(sample).strip()
        if not text:
            continue
        rows.append(
            {
                "prop_id": f"P.VOICE.ryuya.W1.{i:03d}",
                "statement": text,
                "learn_ch": 0,
                "source": f"runtime/free_stage_card_ryuya_prologue.json persona_cards.{CONS}.voice_samples[{i-1}]",
                "kind": "voice",
            }
        )

    boundaries = pc.get("boundaries") or {}
    for i, item in enumerate(boundaries.get("hard") or [], start=1):
        rows.append(
            {
                "prop_id": f"P.BOUNDARY.ryuya.W1.hard.{i:03d}",
                "statement": str(item).strip(),
                "learn_ch": 0,
                "source": f"runtime/free_stage_card_ryuya_prologue.json ...boundaries.hard[{i-1}]",
                "kind": "boundary_hard",
            }
        )
    for i, item in enumerate(boundaries.get("soft") or [], start=1):
        rows.append(
            {
                "prop_id": f"P.BOUNDARY.ryuya.W1.soft.{i:03d}",
                "statement": str(item).strip(),
                "learn_ch": 0,
                "source": f"runtime/free_stage_card_ryuya_prologue.json ...boundaries.soft[{i-1}]",
                "kind": "boundary_soft",
            }
        )
    style = str(boundaries.get("style") or "").strip()
    if style:
        rows.append(
            {
                "prop_id": "P.MANNER.ryuya.W1.style",
                "statement": style,
                "learn_ch": 0,
                "source": "runtime/free_stage_card_ryuya_prologue.json ...boundaries.style",
                "kind": "manner",
            }
        )

    # Nature-level constraints (not scene must_happen). Keep scene-only on card.
    nature_constraints = [
        "禁止用“愿意听就听、不愿意也没关系”“不急着说”一类试探/退路句式。",
        "朋友之间的沉默或一次拒绝不是谈话终点：可以接玩笑、换话题，但不纠缠。",
    ]
    for i, text in enumerate(nature_constraints, start=1):
        rows.append(
            {
                "prop_id": f"P.MANNER.ryuya.W1.constraint.{i:03d}",
                "statement": text,
                "learn_ch": 0,
                "source": f"runtime/free_stage_card_ryuya_prologue.json ...constraints (nature subset {i})",
                "kind": "manner",
            }
        )

    if CONSTRAINTS.exists():
        blob = json.loads(CONSTRAINTS.read_text(encoding="utf-8"))
        text = str(blob.get(CONS) or "").strip()
        if text:
            rows.append(
                {
                    "prop_id": "P.BOUNDARY.ryuya.W1.iron_law",
                    "statement": text,
                    "learn_ch": 0,
                    "source": "runtime/persona_constraints.json C.ryuya.W1",
                    "kind": "boundary_hard",
                }
            )

    if PERSONA_MD.exists():
        md = PERSONA_MD.read_text(encoding="utf-8").strip()
        if md:
            rows.append(
                {
                    "prop_id": "P.MANNER.ryuya.W1.persona_md",
                    "statement": md,
                    "learn_ch": 0,
                    "source": "runtime/personas/C.ryuya.W1.md",
                    "kind": "manner",
                }
            )
    return rows


def apply_db(db_path: Path, dry_run: bool = False) -> list[str]:
    rows = build_rows()
    diff: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        for row in rows:
            diff.append(f"+PROP {row['prop_id']} [{row['kind']}]: {str(row['statement'])[:60]}")
            if dry_run:
                continue
            conn.execute(
                """
                INSERT INTO propositions(prop_id, statement, spoiler_tier, canon_src)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(prop_id) DO UPDATE SET
                    statement=excluded.statement,
                    canon_src=excluded.canon_src
                """,
                (row["prop_id"], row["statement"], row["source"]),
            )
            conn.execute(
                """
                INSERT INTO knowledge_schedule(cons_id, prop_id, learn_ch, source_desc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cons_id, prop_id) DO UPDATE SET
                    learn_ch=excluded.learn_ch,
                    source_desc=excluded.source_desc
                """,
                (CONS, row["prop_id"], row["learn_ch"], row["source"]),
            )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return diff


def rewrite_card(dry_run: bool = False) -> list[str]:
    """Card keeps scene constraints; voice/boundaries become seed id lists."""
    changes: list[str] = []
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pc = card["persona_cards"][CONS]
    rows = build_rows()
    voice_ids = [r["prop_id"] for r in rows if r["kind"] == "voice"]
    hard_ids = [r["prop_id"] for r in rows if r["kind"] == "boundary_hard"]
    soft_ids = [r["prop_id"] for r in rows if r["kind"] == "boundary_soft"]
    manner_ids = [r["prop_id"] for r in rows if r["kind"] == "manner"]

    n_voice = len(pc.get("voice_samples") or [])
    pc["voice_samples"] = []
    pc["voice_seed_prop_ids"] = voice_ids
    pc["boundaries"] = {
        "hard": [],
        "soft": [],
        "style": "",
        "seed_hard_prop_ids": hard_ids,
        "seed_soft_prop_ids": soft_ids,
        "seed_manner_prop_ids": manner_ids,
    }
    # Keep scene-only constraints on card
    scene_only = [
        "托付点名用全名：折原修哉、张尘；说到修哉时自己清楚那是亲弟弟。",
        "托付说清后，下一拍起以交挂坠为眼前要推进的事，直到交到对方手里。",
    ]
    pc["constraints"] = scene_only
    changes.append(f"rewrite card voice_samples {n_voice}→0 (+{len(voice_ids)} seed ids)")
    changes.append(f"rewrite card boundaries → seed id lists; keep {len(scene_only)} scene constraints")
    if not dry_run:
        CARD.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db-only", action="store_true")
    ap.add_argument("--cards-only", action="store_true")
    args = ap.parse_args()
    if not args.cards_only:
        for line in apply_db(Path(args.db), dry_run=args.dry_run):
            print(line)
    if not args.db_only:
        for line in rewrite_card(dry_run=args.dry_run):
            print(line)
    print("DRY_RUN" if args.dry_run else "APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
