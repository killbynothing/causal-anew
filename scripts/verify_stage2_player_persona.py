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
CONS_WM = "C.ryuya.WMAIN"


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


def fetch_persona_statements(conn: sqlite3.Connection, cons: str) -> dict[str, list[str]]:
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
            OR ks.prop_id LIKE 'P.ARCH.%'
            OR ks.prop_id LIKE 'P.ACT.%'
          )
        """,
        (cons,),
    ).fetchall()
    out = {"voice": [], "boundary": [], "manner": [], "act": [], "all": []}
    for prop_id, statement in rows:
        text = str(statement or "").strip()
        if not text:
            continue
        out["all"].append(text)
        if prop_id.startswith("P.VOICE."):
            out["voice"].append(text)
        elif prop_id.startswith("P.BOUNDARY."):
            out["boundary"].append(text)
        elif prop_id.startswith("P.ACT."):
            out["act"].append(text)
        else:
            out["manner"].append(text)
    return out


def _prop_ok(conn: sqlite3.Connection, pid: str) -> bool:
    row = conn.execute(
        "SELECT statement FROM propositions WHERE prop_id=?", (pid,)
    ).fetchone()
    return bool(row and str(row[0] or "").strip())


def check_persona_parity(conn: sqlite3.Connection) -> list[str]:
    """Projected seed persona must cover card seed id lists / residual card fields."""
    fails: list[str] = []
    if not CARD.exists():
        return ["missing ryuya prologue card"]
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pc = card["persona_cards"][CONS]
    projected = fetch_persona_statements(conn, CONS)
    # Voice optional after thin retirement; boundary+manner required
    if len(projected["boundary"]) < 1:
        fails.append("no P.BOUNDARY.* for C.ryuya.W1")
    if len(projected["manner"]) < 1:
        fails.append("no P.MANNER/ARCH.* for C.ryuya.W1")
    # Old thin numeric VOICE (001–004) must stay retired; new named P.VOICE is required.
    thin_voice = conn.execute(
        "SELECT COUNT(*) FROM knowledge_schedule WHERE prop_id GLOB 'P.VOICE.ryuya.W1.[0-9]*'"
    ).fetchone()[0]
    if thin_voice:
        fails.append(f"thin P.VOICE.ryuya.W1.00x still scheduled ({thin_voice})")
    named_voice = conn.execute(
        "SELECT COUNT(*) FROM knowledge_schedule WHERE prop_id LIKE 'P.VOICE.ryuya.W1.%' "
        "AND prop_id NOT GLOB 'P.VOICE.ryuya.W1.[0-9]*'"
    ).fetchone()[0]
    if named_voice < 4:
        fails.append(f"named P.VOICE.ryuya.W1.* expected >=4, got {named_voice}")
    # ARCH must hit both consciousnesses
    for arch in ("P.ARCH.ryuya.mask", "P.ARCH.ryuya.brother_complex", "P.ARCH.ryuya.endure_dirt"):
        for cons in (CONS, CONS_WM):
            row = conn.execute(
                "SELECT 1 FROM knowledge_schedule WHERE cons_id=? AND prop_id=?",
                (cons, arch),
            ).fetchone()
            if not row:
                fails.append(f"missing schedule {cons} <- {arch}")
    # WMAIN must have manners
    wm = fetch_persona_statements(conn, CONS_WM)
    if len(wm["manner"]) < 1:
        fails.append("no P.MANNER/ARCH.* for C.ryuya.WMAIN")

    for key in ("voice_seed_prop_ids", "identity_seed_prop_ids"):
        for pid in pc.get(key) or []:
            if not _prop_ok(conn, pid):
                fails.append(f"card {key} missing/empty prop {pid}")

    bounds = pc.get("boundaries") or {}
    for key in ("seed_hard_prop_ids", "seed_soft_prop_ids", "seed_manner_prop_ids"):
        for pid in bounds.get(key) or []:
            if not _prop_ok(conn, pid):
                fails.append(f"card boundaries.{key} missing/empty prop {pid}")

    if pc.get("voice_samples"):
        fails.append("card still has inline voice_samples; should be empty + seed ids")

    print(
        f"[ok] persona_core_parity ryuya: voice={len(projected['voice'])} "
        f"boundary={len(projected['boundary'])} manner={len(projected['manner'])} "
        f"act={len(projected['act'])} wm_manner={len(wm['manner'])}"
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
