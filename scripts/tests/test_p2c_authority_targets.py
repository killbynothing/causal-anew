#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_FIELDS = (
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

EXPECTED_OWNERS = {
    "completed": "BeatReducer",
    "completed_by_card": "BeatReducer",
    "completed_beats": "BeatReducer",
    "canon_performance_state": "BeatReducer",
    "branch_progress": "WorldCommit",
    "scene_receipts": "WorldCommit",
    "world_transactions": "WorldCommit",
    "causal_receipts": "WorldCommit",
    "run_observation_ledger": "WorldCommit",
    "player_state": "WorldCommit",
    "body_frames": "WorldCommit",
    "world_cursor": "WorldCommit",
}


def _load_audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_runtime_authority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _production(meta):
    return [
        row for row in meta.get("writers", [])
        if row.get("classification") in {"production", "production_tooling"}
    ]


def test_p2c_target_inventory_is_complete_and_machine_visible():
    audit = _load_audit()
    report = audit.build_report(False)
    facts = report.get("facts") or {}
    missing = [field for field in TARGET_FIELDS if field not in facts]
    assert not missing, f"P2c target facts missing from authority map: {missing}"

    compact = {}
    for field in TARGET_FIELDS:
        meta = facts[field]
        assert meta.get("target_owner") == EXPECTED_OWNERS[field], (field, meta.get("target_owner"))
        rows = _production(meta)
        compact[field] = {
            "production_writer_count": len(rows),
            "symbols": sorted({str(row.get("symbol") or "") for row in rows}),
            "unknown_alias_count": int(meta.get("unknown_alias_count") or 0),
        }

    # Characterization start: at P2c entry there must still be real migration
    # work. Later loops replace this with shrinking/zero-writer invariants.
    assert any(row["production_writer_count"] > 0 for row in compact.values())
    print("P2C_AUTHORITY_TARGETS=" + json.dumps(compact, ensure_ascii=False, sort_keys=True))


def test_p2c_target_set_matches_audit_domains():
    audit = _load_audit()
    report = audit.build_report(False)
    facts = report.get("facts") or {}
    current = {
        field
        for field, meta in facts.items()
        if meta.get("target_owner") in {"BeatReducer", "WorldCommit"}
        and meta.get("domain") in {"beat", "world", "player_world"}
    }
    declared = set(TARGET_FIELDS)
    assert current <= declared, f"new P2c authority fact family must be declared: {sorted(current - declared)}"


if __name__ == "__main__":
    test_p2c_target_inventory_is_complete_and_machine_visible()
    test_p2c_target_set_matches_audit_domains()
    print("PASS test_p2c_authority_targets")
