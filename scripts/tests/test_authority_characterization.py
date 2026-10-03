#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0a characterization of known authority debt.

These assertions deliberately freeze the audited baseline as KNOWN_BUG evidence.
When the owning phase removes a debt, update this characterization together with
the new required invariant test; do not silently delete the case.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "audit_runtime_authority.py"


@lru_cache(maxsize=1)
def load_report():
    spec = importlib.util.spec_from_file_location("runtime_authority_audit_characterization", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def production(report, fact):
    return [
        row for row in report["facts"][fact]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]


def test_p2c_completed_has_no_direct_production_writer():
    report = load_report()
    rows = production(report, "completed")
    assert rows == []
    assert report["facts"]["completed"]["production_writer_count"] == 0


def test_p2c_fact_projections_have_no_direct_production_writer():
    report = load_report()
    for fact in ("branch_progress", "scene_receipts"):
        rows = production(report, fact)
        assert rows == []
        assert report["facts"][fact]["production_writer_count"] == 0


def test_p2c_observation_ledger_has_no_direct_production_writer():
    report = load_report()
    rows = production(report, "run_observation_ledger")
    assert rows == []
    assert report["facts"]["run_observation_ledger"]["production_writer_count"] == 0


def test_p2c_world_ledgers_have_no_direct_production_writer():
    report = load_report()
    for fact in ("world_transactions", "causal_receipts"):
        rows = production(report, fact)
        assert rows == [], rows
        assert report["facts"][fact]["production_writer_count"] == 0


def test_p2c_physical_projections_have_no_direct_or_unknown_writer():
    report = load_report()
    for fact in ("player_state", "body_frames"):
        rows = production(report, fact)
        meta = report["facts"][fact]
        assert rows == [], rows
        assert meta["production_writer_count"] == 0
        assert meta["unknown_alias_count"] == 0, meta["writers"]


def test_p3_working_context_is_not_a_persistent_mind_writer():
    report = load_report()
    meta = report["facts"]["private_inner_states"]
    assert meta["target_owner"] == "TurnWorkingContext"
    assert production(report, "private_inner_states") == []
    assert meta["production_writer_count"] == 0
    assert meta["unknown_alias_count"] == 0


def test_p1b_lifecycle_projection_has_one_production_writer():
    report = load_report()
    ended = production(report, "ended")
    lifecycle = production(report, "lifecycle_state")
    assert {row["symbol"] for row in ended} == {"FreeStageSession._set_lifecycle_state"}
    assert {row["symbol"] for row in lifecycle} == {"FreeStageSession._set_lifecycle_state"}
    assert report["facts"]["ended"]["production_writer_count"] == 1
    assert report["facts"]["lifecycle_state"]["production_writer_count"] == 1


def test_p1b_sediment_is_append_only_but_run_meta_projection_update_remains():
    report = load_report()
    sediment = production(report, "sql:delta_sediment")
    run_meta = production(report, "sql:run_meta")

    assert sediment
    assert not any(row["write_kind"] == "delete_from" for row in sediment)
    assert any(row["write_kind"].startswith("insert") for row in sediment)
    # P1b deliberately leaves run_meta.closed_at/final_delta_summary as the
    # current lifecycle projection debt; no schema exception is invented here.
    assert any(row["write_kind"] == "update" for row in run_meta)


def test_unknown_alias_inventory_is_explicit_even_when_zero():
    report = load_report()
    total = sum(
        int(meta.get("unknown_alias_count") or 0)
        for meta in report["facts"].values()
    )
    assert report["summary"]["unknown_alias_count"] == total
    assert sorted(report["summary"]["facts_with_unknown_aliases"]) == sorted(
        fact
        for fact, meta in report["facts"].items()
        if int(meta.get("unknown_alias_count") or 0) > 0
    )
    assert "body_frames" not in report["summary"]["facts_with_unknown_aliases"]


if __name__ == "__main__":
    test_p2c_completed_has_no_direct_production_writer()
    test_p2c_fact_projections_have_no_direct_production_writer()
    test_p2c_observation_ledger_has_no_direct_production_writer()
    test_p2c_world_ledgers_have_no_direct_production_writer()
    test_p2c_physical_projections_have_no_direct_or_unknown_writer()
    test_p3_working_context_is_not_a_persistent_mind_writer()
    test_p1b_lifecycle_projection_has_one_production_writer()
    test_p1b_sediment_is_append_only_but_run_meta_projection_update_remains()
    test_unknown_alias_inventory_is_explicit_even_when_zero()
    print("PASS test_authority_characterization")
