#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 validators: seed identity projection + items have no run-domain facts."""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

OPENING_CONS = [
    "C.ryuya.W1",
    "C.xiuzai.WMAIN",
    "C.maki.WMAIN",
    "C.kakashi.WMAIN",
    "C.akito.WMAIN",
]

RUN_DOMAIN_RE = re.compile(
    r"(玩家持有|玩家已|本局|这一局|run\s*=|已交到玩家|玩家手里)",
    re.I,
)


def check_identity(conn: sqlite3.Connection) -> list[str]:
    fails: list[str] = []
    for cons in OPENING_CONS:
        rows = conn.execute(
            """
            SELECT ks.prop_id, ks.learn_ch, p.statement
            FROM knowledge_schedule ks
            JOIN propositions p ON p.prop_id = ks.prop_id
            WHERE ks.cons_id=? AND ks.prop_id LIKE 'REL.IDENTITY.%' AND ks.learn_ch <= 0
            """,
            (cons,),
        ).fetchall()
        if not rows:
            fails.append(f"{cons}: no REL.IDENTITY scheduled at learn_ch<=0")
        else:
            print(f"[ok] {cons}: {len(rows)} REL.IDENTITY @ learn_ch<=0")
    return fails


def check_items(conn: sqlite3.Connection) -> list[str]:
    fails: list[str] = []
    for item_id, note in conn.execute("SELECT item_id, note FROM items"):
        text = note or ""
        if RUN_DOMAIN_RE.search(text):
            fails.append(f"{item_id}: run-domain wording in note: {text[:80]}")
        else:
            print(f"[ok] {item_id}: note clean")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--check", choices=["identity", "items", "all"], default="all")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    fails: list[str] = []
    try:
        if args.check in {"identity", "all"}:
            fails.extend(check_identity(conn))
        if args.check in {"items", "all"}:
            fails.extend(check_items(conn))
    finally:
        conn.close()
    if fails:
        print("[FAIL] seed checks:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("[PASS] seed_identity_projection + seed_no_run_facts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
