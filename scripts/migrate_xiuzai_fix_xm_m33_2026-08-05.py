# -*- coding: utf-8 -*-
"""Remove mis-bucketed XM-M33 (Wu Xiaxuan album / 'followed to China').

Human cut 2026-08-05: Wu is already in China; album scene is post-opening
(Kakashi visits office). No 'secret dossier' in novel.
Idempotent: deletes by anchor prefix [XM-M33].
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"
PREFIX = "[XM-M33]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT mem_id, anchor, substr(text,1,80) FROM slow_memory "
        "WHERE cons_id=? AND anchor LIKE ?",
        ("C.xiuzai.WMAIN", PREFIX + "%"),
    ).fetchall()
    print(f"MATCH {len(rows)}")
    for r in rows:
        print(r)
    if not args.apply:
        print("DRY-RUN; pass --apply to delete")
        return 0
    cur = conn.execute(
        "DELETE FROM slow_memory WHERE cons_id=? AND anchor LIKE ?",
        ("C.xiuzai.WMAIN", PREFIX + "%"),
    )
    conn.commit()
    print(f"DELETED {cur.rowcount}")
    left = conn.execute(
        "SELECT COUNT(*) FROM slow_memory WHERE cons_id=? AND anchor LIKE ?",
        ("C.xiuzai.WMAIN", PREFIX + "%"),
    ).fetchone()[0]
    assert left == 0, left
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
