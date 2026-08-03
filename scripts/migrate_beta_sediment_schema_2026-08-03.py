# -*- coding: utf-8 -*-
"""Create run_meta + delta_sediment (β v0.2 §4.1).

Human-cut 2026-08-03: schema + draft weights approved.
Does not touch run=0 canon rows. Idempotent CREATE IF NOT EXISTS.

Usage:
  python scripts/migrate_beta_sediment_schema_2026-08-03.py
  python scripts/migrate_beta_sediment_schema_2026-08-03.py --apply
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

DDL_RUN_META = """
CREATE TABLE IF NOT EXISTS run_meta (
  run INTEGER PRIMARY KEY,
  parent_run INTEGER NOT NULL,
  kind TEXT NOT NULL,
  fork_event TEXT,
  inherit_level INTEGER NOT NULL,
  player_line TEXT NOT NULL DEFAULT 'a_qi',
  opening_id TEXT,
  player_profile_hash TEXT,
  opened_at TEXT,
  closed_at TEXT,
  final_delta_summary TEXT,
  CHECK (run >= 1),
  CHECK (kind IN ('fresh', 'beta', 'fork')),
  CHECK (inherit_level IN (0, 1, 2))
);
"""

DDL_DELTA_SEDIMENT = """
CREATE TABLE IF NOT EXISTS delta_sediment (
  sid INTEGER PRIMARY KEY,
  node_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  cons_id TEXT,
  weight REAL NOT NULL,
  src_run INTEGER NOT NULL,
  src_delta TEXT NOT NULL,
  revoked INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  CHECK (kind IN ('precedent', 'scar', 'unlock', 'witness')),
  CHECK (src_run >= 1),
  CHECK (revoked IN (0, 1))
);
"""

IDX = [
    "CREATE INDEX IF NOT EXISTS idx_delta_sediment_node ON delta_sediment(node_id);",
    "CREATE INDEX IF NOT EXISTS idx_delta_sediment_src_run ON delta_sediment(src_run);",
    "CREATE INDEX IF NOT EXISTS idx_delta_sediment_kind ON delta_sediment(kind);",
    "CREATE INDEX IF NOT EXISTS idx_run_meta_parent ON run_meta(parent_run);",
]


def required_cols(table: str) -> set[str]:
    if table == "run_meta":
        return {
            "run",
            "parent_run",
            "kind",
            "fork_event",
            "inherit_level",
            "player_line",
            "opening_id",
            "player_profile_hash",
            "opened_at",
            "closed_at",
            "final_delta_summary",
        }
    return {
        "sid",
        "node_id",
        "kind",
        "payload",
        "cons_id",
        "weight",
        "src_run",
        "src_delta",
        "revoked",
        "created_at",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    log: list[str] = []

    if args.apply:
        cur.executescript(DDL_RUN_META)
        cur.executescript(DDL_DELTA_SEDIMENT)
        for stmt in IDX:
            cur.execute(stmt)
        con.commit()
        log.append("COMMIT: run_meta + delta_sediment")
    else:
        log.append("DRY-RUN only (pass --apply to create)")

    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name in ("run_meta", "delta_sediment"):
        present = name in tables
        log.append(f"table {name}: {'present' if present else 'MISSING'}")
        if present:
            cols = {r[1] for r in cur.execute(f"PRAGMA table_info({name})")}
            missing = required_cols(name) - cols
            if missing:
                log.append(f"  MISSING COLS: {sorted(missing)}")
            else:
                log.append(f"  cols_ok n={len(cols)}")

    con.close()
    for line in log:
        print(line)
    if args.apply and ("run_meta" not in tables or "delta_sediment" not in tables):
        # re-open after apply path — tables set was pre-commit; recheck
        con = sqlite3.connect(args.db)
        tables2 = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        if "run_meta" not in tables2 or "delta_sediment" not in tables2:
            raise SystemExit("[FAIL] tables not created")


if __name__ == "__main__":
    main()
