#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2/S3 validators: player_packet_projection + persona_core_parity(ryuya)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"
CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
CONS = "C.ryuya.W1"


def check_player(conn: sqlite3.Connection) -> list[str]:
    fails: list[str] = []
    body = conn.execute("SELECT body_type FROM bodies WHERE body_id='B.player'").fetchone()
    if not body:
        fails.append("missing bodies.B.player")
    cons = conn.execute(
        "SELECT jump_capable FROM consciousnesses WHERE cons_id='C.player'"
    ).fetchone()
    if not cons:
        fails.append("missing consciousnesses.C.player")
    elif int(cons[0] or 0) != 0:
        fails.append(f"C.player jump_capable={cons[0]} want 0")
    occ = conn.execute(
        "SELECT 1 FROM occupancy WHERE body_id='B.player' AND cons_id='C.player'"
    ).fetchone()
    if not occ:
        fails.append("missing occupancy B.player×C.player")
    props = conn.execute(
        """
        SELECT COUNT(*) FROM knowledge_schedule ks
        JOIN propositions p ON p.prop_id=ks.prop_id
        WHERE ks.cons_id='C.player' AND ks.prop_id LIKE 'P.PLAYER.%' AND ks.learn_ch<=0
        """
    ).fetchone()[0]
    if props < 1:
        fails.append("no P.PLAYER.* scheduled to C.player at learn_ch<=0")
    else:
        print(f"[ok] player seed packet: body+cons+occ + {props} P.PLAYER.*")
    return fails


def fetch_persona_statements(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = conn.execute(
        """
        SELECT ks.prop_id, p.statement
        FROM knowledge_schedule ks
        JOIN propositions p ON p.prop_id=ks.prop_id
        WHERE ks.cons_id=? AND ks.learn_ch<=0
          AND (
            ks.prop_id LIKE 'P.VOICE.%'
            OR ks.prop_id LIKE 'P.BOUNDARY.%'
            OR ks.prop_id LIKE 'P.MANNER.%'
          )
        """,
        (CONS,),
    ).fetchall()
    out = {"voice": [], "boundary": [], "manner": [], "all": []}
    for prop_id, statement in rows:
        text = str(statement or "").strip()
        if not text:
            continue
        out["all"].append(text)
        if prop_id.startswith("P.VOICE."):
            out["voice"].append(text)
        elif prop_id.startswith("P.BOUNDARY."):
            out["boundary"].append(text)
        else:
            out["manner"].append(text)
    return out


def check_persona_parity(conn: sqlite3.Connection) -> list[str]:
    """Projected seed persona must cover card seed id lists / residual card fields."""
    fails: list[str] = []
    if not CARD.exists():
        return ["missing ryuya prologue card"]
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pc = card["persona_cards"][CONS]
    projected = fetch_persona_statements(conn)
    if len(projected["voice"]) < 1:
        fails.append("no P.VOICE.* for C.ryuya.W1")
    if len(projected["boundary"]) < 1:
        fails.append("no P.BOUNDARY.* for C.ryuya.W1")
    if len(projected["manner"]) < 1:
        fails.append("no P.MANNER.* for C.ryuya.W1")

    # Seed id lists on card must resolve in DB
    for key in ("voice_seed_prop_ids",):
        for pid in pc.get(key) or []:
            row = conn.execute(
                "SELECT statement FROM propositions WHERE prop_id=?", (pid,)
            ).fetchone()
            if not row or not str(row[0] or "").strip():
                fails.append(f"card {key} missing/empty prop {pid}")

    bounds = pc.get("boundaries") or {}
    for key in ("seed_hard_prop_ids", "seed_soft_prop_ids", "seed_manner_prop_ids"):
        for pid in bounds.get(key) or []:
            row = conn.execute(
                "SELECT statement FROM propositions WHERE prop_id=?", (pid,)
            ).fetchone()
            if not row or not str(row[0] or "").strip():
                fails.append(f"card boundaries.{key} missing/empty prop {pid}")

    # Nature text must not remain duplicated as full voice_samples on card
    if pc.get("voice_samples"):
        fails.append("card still has inline voice_samples; should be empty + seed ids")

    print(
        f"[ok] persona_core_parity ryuya: voice={len(projected['voice'])} "
        f"boundary={len(projected['boundary'])} manner={len(projected['manner'])}"
    )
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--check", choices=["player", "persona", "all"], default="all")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    fails: list[str] = []
    try:
        if args.check in {"player", "all"}:
            fails.extend(check_player(conn))
        if args.check in {"persona", "all"}:
            fails.extend(check_persona_parity(conn))
    finally:
        conn.close()
    if fails:
        print("[FAIL]")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("[PASS] player_packet_projection + persona_core_parity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
