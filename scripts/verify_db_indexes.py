#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify world_truth.db hot-path secondary indexes are present and used."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

INDEXES = {
    "canon_locks": "idx_canon_locks_speaker_cons",
    "slow_memory": "idx_slow_memory_cons_id",
    "events": "idx_events_ch_anchor",
}

QUERY_PLANS = [
    ("canon_locks.speaker_cons", "SELECT * FROM canon_locks WHERE speaker_cons=?", ("C.kakashi.WMAIN",), "idx_canon_locks_speaker_cons"),
    ("slow_memory.cons_id", "SELECT * FROM slow_memory WHERE cons_id=?", ("C.kakashi.WMAIN",), "idx_slow_memory_cons_id"),
    ("events.ch_anchor", "SELECT * FROM events WHERE ch_anchor=?", (13,), "idx_events_ch_anchor"),
]


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}


def _query_plan(conn: sqlite3.Connection, sql: str, params: tuple) -> str:
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return "\n".join(str(row) for row in rows)


def main() -> int:
    if not DB.exists():
        print(f"[FAIL] missing db: {DB}")
        return 1
    conn = sqlite3.connect(DB)
    failures: list[str] = []
    for table, index_name in INDEXES.items():
        if index_name not in _index_names(conn, table):
            failures.append(f"{table} missing {index_name}")
    for label, sql, params, index_name in QUERY_PLANS:
        plan = _query_plan(conn, sql, params)
        if "USING INDEX" not in plan.upper() or index_name not in plan:
            failures.append(f"{label} does not use {index_name}: {plan}")
    conn.close()
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[PASS] world_truth.db hot-path indexes are present and used")
    return 0


if __name__ == "__main__":
    sys.exit(main())
