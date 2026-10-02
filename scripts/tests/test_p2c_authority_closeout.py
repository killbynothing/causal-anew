#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

P2C_FACTS = (
    "completed",
    "completed_by_card",
    "completed_beats",
    "canon_performance_state",
    "branch_progress",
    "scene_receipts",
    "world_transactions",
    "causal_receipts",
    "run_observation_ledger",
    "player_state",
    "body_frames",
    "world_cursor",
)


def load_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_closeout_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_p2c_world_beat_field_writers_are_fully_closed():
    report = load_report()
    problems = {}
    for fact in P2C_FACTS:
        meta = report["facts"][fact]
        rows = [
            row for row in meta["writers"]
            if row["classification"] in {
                "production", "production_tooling", "unknown_alias"
            }
        ]
        if meta["production_writer_count"] or meta["unknown_alias_count"] or rows:
            problems[fact] = {
                "production": meta["production_writer_count"],
                "unknown": meta["unknown_alias_count"],
                "rows": rows,
            }
    assert problems == {}, problems


if __name__ == "__main__":
    test_p2c_world_beat_field_writers_are_fully_closed()
    print("PASS test_p2c_authority_closeout")
