#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0a required gate: authority scanner must find representative writers."""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "audit_runtime_authority.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("runtime_authority_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def get_report():
    return load_audit().build_report(False)


def writers(report, fact, *classes):
    rows = report["facts"][fact]["writers"]
    if not classes:
        return rows
    return [row for row in rows if row["classification"] in set(classes)]


def test_scanner_finds_representative_five_domain_writers():
    report = get_report()
    assert report["parse_errors"] == []

    completed = writers(report, "completed", "production")
    # P2c: completed is now a read-only BeatReducer projection.
    assert completed == []

    world_tx = writers(report, "world_transactions", "production")
    # P2a moves business append authority out of FreeStageSession. Reset remains
    # an explicit compatibility writer until P2c, but the commit helper itself
    # must no longer assign into the ledger.
    assert any(row["symbol"].endswith("FreeStageSession.reset") for row in world_tx)
    assert not any(row["symbol"].endswith("_commit_world_transaction") for row in world_tx)
    commit_source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    helper_start = commit_source.index("    def _commit_world_transaction(")
    helper_end = commit_source.index("\n    def _world_transaction(", helper_start)
    helper_source = commit_source[helper_start:helper_end]
    assert "world_commit.commit_world_fact" in helper_source
    assert "self.world_transactions[" not in helper_source

    mind = writers(report, "private_inner_states", "production")
    assert any(row["symbol"].endswith("_tick_private_inner_states") for row in mind)

    ended = writers(report, "ended", "production")
    assert {row["symbol"] for row in ended} == {"FreeStageSession._set_lifecycle_state"}
    lifecycle = writers(report, "lifecycle_state", "production")
    assert {row["symbol"] for row in lifecycle} == {"FreeStageSession._set_lifecycle_state"}
    # P1a removed run_session authorization; P1b removes direct bool writers.
    assert not any(row["symbol"].endswith("run_session") for row in ended)


def test_scanner_separates_initialization_and_reports_callers():
    report = get_report()
    completed = report["facts"]["completed"]["writers"]
    assert not any(row["classification"] == "production" for row in completed)

    ended = report["facts"]["ended"]["writers"]
    lifecycle_writer = next(
        row for row in ended
        if row["symbol"].endswith("_set_lifecycle_state")
        and row["classification"] == "production"
    )
    caller_symbols = {row["caller"] for row in lifecycle_writer["callers"]}
    assert "FreeStageSession._mark_ended" in caller_symbols
    assert "FreeStageSession.reset" in caller_symbols
    assert "FreeStageSession._maybe_transition" in caller_symbols


def test_verify_inventory_is_complete_and_new_p0_gates_are_registered():
    report = get_report()
    quick = [row for row in report["verify_inventory"] if row["tier"] == "quick"]
    ids = [row["id"] for row in quick]

    assert len(ids) == len(set(ids))
    assert len(ids) >= 203
    assert "runtime_authority_map" in ids
    assert "authority_characterization" in ids

    by_id = {row["id"]: row for row in quick}
    assert by_id["runtime_authority_map"]["need_file_exists"] is True
    assert by_id["authority_characterization"]["need_file_exists"] is True


if __name__ == "__main__":
    test_scanner_finds_representative_five_domain_writers()
    test_scanner_separates_initialization_and_reports_callers()
    test_verify_inventory_is_complete_and_new_p0_gates_are_registered()
    print("PASS test_runtime_authority_map")
