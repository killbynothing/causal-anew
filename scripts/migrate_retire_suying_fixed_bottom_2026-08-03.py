# -*- coding: utf-8 -*-
"""Retire CC.SUYING_DEATH as fixed-bottom (human cut 2026-08-03).

Player line is not about 苏颖; fixed-bottom self-ref chain must not root on her death.
P.GF_DEATH_TRUTH stays as novel knowledge for 张尘/龙也 arcs — only causal_constants role is removed.

Usage:
  python scripts/migrate_retire_suying_fixed_bottom_2026-08-03.py
  python scripts/migrate_retire_suying_fixed_bottom_2026-08-03.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

# Post-苏颖 self-ref spine (hanging pendant / entrust / rollback). No E_SUYING_DEATH.
NEW_CHAIN = json.dumps(
    [
        "E_RYUYA_GUILT",
        "E_ANCHOR_DELIVER",
        "E_PLAYER_ENTRUST",
        "E_ROLLBACK_TRIGGER",
    ],
    ensure_ascii=False,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    log: list[str] = []

    before = list(cur.execute("SELECT const_id, dependency_chain FROM causal_constants ORDER BY 1"))
    log.append(f"before: {before}")

    if args.apply:
        cur.execute("DELETE FROM causal_constants WHERE const_id=?", ("CC.SUYING_DEATH",))
        log.append("DELETE CC.SUYING_DEATH")
        for cid in ("CC.RYUYA_DEATH", "CC.PLAYER_ENTRUST"):
            cur.execute(
                "UPDATE causal_constants SET dependency_chain=? WHERE const_id=?",
                (NEW_CHAIN, cid),
            )
            log.append(f"UPDATE {cid} chain → no E_SUYING_DEATH")
        con.commit()
        log.append("COMMIT")
    else:
        log.append("DRY-RUN only")

    after = list(cur.execute("SELECT const_id, dependency_chain FROM causal_constants ORDER BY 1"))
    log.append(f"after: {after}")
    suying = cur.execute(
        "SELECT COUNT(*) FROM causal_constants WHERE const_id='CC.SUYING_DEATH' OR dependency_chain LIKE '%E_SUYING%'"
    ).fetchone()[0]
    log.append(f"suying_fixed_bottom_residue={suying}")
    con.close()
    for line in log:
        print(line)
    if args.apply and suying:
        raise SystemExit("[FAIL] 苏颖固定底残留")


if __name__ == "__main__":
    main()
