#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
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


def test_scene_contract_branch_progress_stays_separate_and_visible():
    report = load_report()
    world_branch = report["facts"]["branch_progress"]
    assert world_branch["production_writer_count"] == 0
    assert world_branch["unknown_alias_count"] == 0

    scene_branch = report["facts"]["scene_runtime_branch_progress"]
    assert scene_branch["target_owner"] == "SceneState"
    rows = [
        row for row in scene_branch["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    paths = {row["path"] for row in rows}
    assert "runtime/scene_contracts.py" in paths
    assert "web/scene_api.py" in paths


def print_p2c_authority_map() -> None:
    report = load_report()
    summary = {
        fact: {
            "production_writer_count": report["facts"][fact]["production_writer_count"],
            "unknown_alias_count": report["facts"][fact]["unknown_alias_count"],
            "target_owner": report["facts"][fact]["target_owner"],
        }
        for fact in P2C_FACTS
    }
    scene_meta = report["facts"]["scene_runtime_branch_progress"]
    summary["scene_runtime_branch_progress"] = {
        "production_writer_count": scene_meta["production_writer_count"],
        "unknown_alias_count": scene_meta["unknown_alias_count"],
        "target_owner": scene_meta["target_owner"],
        "semantic_exception": "scene_contract_routing_state",
    }
    print("P2C_FINAL_AUTHORITY_MAP=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    test_p2c_world_beat_field_writers_are_fully_closed()
    test_scene_contract_branch_progress_stays_separate_and_visible()
    print_p2c_authority_map()
    print("PASS test_p2c_authority_closeout")
