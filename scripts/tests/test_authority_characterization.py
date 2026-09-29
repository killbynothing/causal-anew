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


def test_known_bug_multiple_beat_writers_is_visible_until_p2():
    report = load_report()
    rows = production(report, "completed")
    symbols = {row["symbol"] for row in rows}
    assert any(symbol.endswith("FreeStageSession.step") for symbol in symbols)
    assert any(symbol.endswith("FreeStageSession.skip_scene") for symbol in symbols)
    assert report["facts"]["completed"]["production_writer_count"] > 1


def test_known_bug_legacy_mind_writer_is_visible_until_p3():
    report = load_report()
    rows = production(report, "private_inner_states")
    assert rows
    assert any(row["symbol"].endswith("_tick_private_inner_states") for row in rows)


def test_p1a_exit_bypass_removed_but_lifecycle_writers_remain_until_p1b():
    report = load_report()
    rows = production(report, "ended")
    symbols = {row["symbol"] for row in rows}
    assert "FreeStageSession._mark_ended" in symbols
    assert "run_session" not in symbols
    # reset / scene transition still write ended=False. P1b owns lifecycle
    # writer consolidation; P1a only removes competing end authorization.
    assert report["facts"]["ended"]["production_writer_count"] > 1


def test_known_bug_settlement_uses_mutating_sql_until_p1b():
    report = load_report()
    sediment = production(report, "sql:delta_sediment")
    run_meta = production(report, "sql:run_meta")

    assert any(row["write_kind"] == "delete_from" for row in sediment)
    assert any(row["write_kind"] == "update" for row in run_meta)


def test_unknown_aliases_are_reported_not_hidden():
    report = load_report()
    assert report["summary"]["unknown_alias_count"] > 0
    assert "body_frames" in report["summary"]["facts_with_unknown_aliases"]


if __name__ == "__main__":
    test_known_bug_multiple_beat_writers_is_visible_until_p2()
    test_known_bug_legacy_mind_writer_is_visible_until_p3()
    test_p1a_exit_bypass_removed_but_lifecycle_writers_remain_until_p1b()
    test_known_bug_settlement_uses_mutating_sql_until_p1b()
    test_unknown_aliases_are_reported_not_hidden()
    print("PASS test_authority_characterization")
