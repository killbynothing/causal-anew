# -*- coding: utf-8 -*-
"""Remove XM-M17: mis-cited L5768 (Xiuzai cooking, not Maki range-hood care)."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "world_truth.db"
PREFIX = "[XM-M17]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT mem_id, anchor FROM slow_memory WHERE cons_id=? AND anchor LIKE ?",
        ("C.xiuzai.WMAIN", PREFIX + "%"),
    ).fetchall()
    print("MATCH", rows)
    if not args.apply:
        print("DRY-RUN")
        return 0
    n = conn.execute(
        "DELETE FROM slow_memory WHERE cons_id=? AND anchor LIKE ?",
        ("C.xiuzai.WMAIN", PREFIX + "%"),
    ).rowcount
    conn.commit()
    print("DELETED", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
