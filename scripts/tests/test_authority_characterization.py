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


def test_p2c_completed_projection_has_one_business_writer():
    report = load_report()
    completed = production(report, "completed")
    completed_by_card = production(report, "completed_by_card")
    assert {row["symbol"] for row in completed} == {"FreeStageSession._sync_beat_projections"}
    assert {row["symbol"] for row in completed_by_card} == {"FreeStageSession._sync_beat_projections"}
    assert report["facts"]["completed"]["production_writer_count"] == 1
    assert report["facts"]["completed_by_card"]["production_writer_count"] == 1


def test_known_bug_legacy_mind_writer_is_visible_until_p3():
    report = load_report()
    rows = production(report, "private_inner_states")
    assert rows
    assert any(row["symbol"].endswith("_tick_private_inner_states") for row in rows)


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


def test_unknown_aliases_are_reported_not_hidden():
    report = load_report()
    assert report["summary"]["unknown_alias_count"] > 0
    assert "body_frames" in report["summary"]["facts_with_unknown_aliases"]


if __name__ == "__main__":
    test_p2c_completed_projection_has_one_business_writer()
    test_known_bug_legacy_mind_writer_is_visible_until_p3()
    test_p1b_lifecycle_projection_has_one_production_writer()
    test_p1b_sediment_is_append_only_but_run_meta_projection_update_remains()
    test_unknown_aliases_are_reported_not_hidden()
    print("PASS test_authority_characterization")
