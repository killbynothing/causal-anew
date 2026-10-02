#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime.world_fact_ledger import WORLD_FACT_LEDGER_SCHEMA, WorldFactLedger


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_retract_changes_current_branch_but_keeps_historical_receipt():
    ledger = WorldFactLedger()
    assert ledger.assert_fact(
        event_id="e1", fact_id="left", scene_id="S1", owner="player",
        turn=1, source_kind="player_branch", source_input="左边",
        project_branch=True, observable_receipt=True,
    ) is True
    assert ledger.active_branch() == ["left"]
    assert [row["fact_id"] for row in ledger.scene_receipts()] == ["left"]
    assert ledger.retract_fact(
        event_id="e2", fact_id="left", scene_id="S1", turn=2,
        source_kind="exclusive_replace",
    ) is True
    assert ledger.active_branch() == []
    assert [row["fact_id"] for row in ledger.scene_receipts()] == ["left"]


def test_legacy_load_does_not_fabricate_events():
    ledger = WorldFactLedger.from_saved(
        None,
        legacy_branch=["legacy"],
        legacy_receipts=[{
            "scene_id": "OLD", "fact_id": "seen", "owner": "player",
            "turn": 1, "source_input": "", "source_kind": "legacy",
        }],
    )
    raw = ledger.to_dict()
    assert raw["schema_version"] == WORLD_FACT_LEDGER_SCHEMA
    assert raw["events"] == []
    assert ledger.active_branch() == ["legacy"]
    assert ledger.scene_receipts()[0]["fact_id"] == "seen"


def test_session_projections_are_copy_only_and_persist():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="fact-save", state_dir=state_dir, autosave=True,
            load_existing=False, caller=_caller,
        )
        assert session._assert_branch_fact(
            "f1", owner="world", turn_no=1, source_kind="fixture",
            observable_receipt=True,
        ) is True
        branch = session.branch_progress
        branch.append("FAKE")
        receipts = session.scene_receipts
        receipts.append({"fact_id": "FAKE"})
        assert session.branch_progress == ["f1"]
        assert [row["fact_id"] for row in session.scene_receipts] == ["f1"]
        session.save()
        disk = json.loads((state_dir / "fact-save.json").read_text(encoding="utf-8"))
        assert disk["world_fact_ledger"]["schema_version"] == WORLD_FACT_LEDGER_SCHEMA
        resumed = proto.FreeStageSession(
            session_id="fact-save", state_dir=state_dir, autosave=True,
            load_existing=True, caller=_caller,
        )
        assert resumed.branch_progress == ["f1"]
        assert [row["fact_id"] for row in resumed.scene_receipts] == ["f1"]


def test_player_branch_event_ids_do_not_reuse_across_visits():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="fact-visit", state_dir=Path(tmp) / "states",
            autosave=False, load_existing=False, caller=_caller,
        )
        session._record_player_branch_fact("route", turn_no=1, player_input="左")
        session.card_history.append(session._beat_scene_id())
        session._retract_branch_facts(
            {"route"}, turn_no=2, source_kind="fixture_revisit",
        )
        session._record_player_branch_fact("route", turn_no=3, player_input="又选左")
        ids = [row["event_id"] for row in session._world_fact_state.events()]
        assert len(ids) == len(set(ids))
        actions = [key for key in session.player_action_receipts if key.endswith(":route")]
        assert len(actions) == 2


def test_free_stage_branch_projection_is_closed_but_external_debt_remains_visible():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert not re.search(r"self\.branch_progress\s*=", source)
    assert not re.search(r"self\.branch_progress\.append\(", source)
    assert not re.search(r"self\.scene_receipts\s*=", source)
    assert not re.search(r"self\.scene_receipts\.append\(", source)

    audit_path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("world_fact_authority_audit", audit_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.build_report(False)
    branch_rows = [
        row for row in report["facts"]["branch_progress"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    symbols = {row["symbol"] for row in branch_rows}
    assert "FreeStageSession.reset" not in symbols
    assert any(symbol.endswith("register_branch_progress") for symbol in symbols)
    assert any(symbol.endswith("SceneState.load") for symbol in symbols)
    assert report["facts"]["scene_receipts"]["production_writer_count"] == 0


def test_production_has_no_direct_branch_or_scene_receipt_mutators():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = [
        r"self\.branch_progress\s*=",
        r"self\.branch_progress\.append\(",
        r"self\.scene_receipts\s*=",
        r"self\.scene_receipts\.append\(",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, source), pattern
    assert "self._world_fact_state.assert_fact(" in source
    assert "self._world_fact_state.retract_fact(" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
