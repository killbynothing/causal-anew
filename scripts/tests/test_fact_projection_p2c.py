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

from runtime.fact_projection import RuntimeFactProjection
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_fact_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_legacy_projection_migrates_without_inventing_source():
    state = RuntimeFactProjection.from_snapshot(
        None,
        legacy_branches=["A", "B", "A"],
        legacy_scene_receipts=[{
            "scene_id": "S1",
            "fact_id": "F1",
            "owner": "player",
            "turn": 2,
        }],
    )
    assert state.branch_progress == ["A", "B"]
    assert state.branch_sources["A"]["source_kind"] == "legacy_snapshot"
    assert state.scene_receipts[0]["source_kind"] == "legacy_snapshot"


def test_branch_projection_is_idempotent_and_removal_drops_source():
    state = RuntimeFactProjection.empty()
    assert state.add_branch(
        "A", source_kind="player_action", source_ref="player:r1", turn=1, scene_id="S1"
    )
    before = state.to_dict()
    assert not state.add_branch(
        "A", source_kind="other", source_ref="x", turn=2, scene_id="S1"
    )
    assert state.to_dict() == before
    assert state.remove_ids(["A"]) == ["A"]
    assert state.branch_progress == []
    assert "A" not in state.branch_sources


def test_scene_receipt_dedupes_by_scene_and_fact():
    state = RuntimeFactProjection.empty()
    assert state.record_scene_receipt(
        "F1", owner="player", turn=1, scene_id="S1", source_input="x"
    )
    assert not state.record_scene_receipt(
        "F1", owner="player", turn=2, scene_id="S1", source_input="y"
    )
    assert state.record_scene_receipt(
        "F1", owner="player", turn=2, scene_id="S2", source_input="y"
    )
    assert len(state.scene_receipts) == 2


def test_session_views_are_copy_safe_and_save_load_preserves_sources():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-facts",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._branch_add(
            "FACT_A",
            source_kind="fixture",
            source_ref="case:a",
            turn_no=1,
        )
        session._record_scene_receipt(
            "FACT_A",
            owner="player",
            turn_no=1,
            source_input="a",
            source_kind="fixture",
        )
        branches = session.branch_progress
        branches.append("MUTATED")
        receipts = session.scene_receipts
        receipts.append({"fact_id": "MUTATED"})
        assert session.branch_progress == ["FACT_A"]
        assert len(session.scene_receipts) == 1
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-facts",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.branch_progress == ["FACT_A"]
        assert resumed.fact_projection.branch_sources["FACT_A"]["source_ref"] == "case:a"
        assert resumed.scene_receipts[0]["source_kind"] == "fixture"


def test_compat_setters_exist_only_for_tests_and_tools():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-fact-compat",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.branch_progress = ["A"]
        session.scene_receipts = [{"scene_id": "S", "fact_id": "F", "owner": "x", "turn": 1}]
        assert session.branch_progress == ["A"]
        assert session.scene_receipts[0]["fact_id"] == "F"


def test_no_direct_projection_mutation_remains_in_free_stage_source():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    for field in ("branch_progress", "scene_receipts"):
        direct = re.findall(
            rf"self\.{field}(?:\s*=|\.append\(|\.extend\(|\.remove\(|\.clear\()",
            source,
        )
        assert direct == [], (field, direct)


def test_authority_map_reports_zero_projection_production_writers():
    report = _audit_report()
    for fact in ("branch_progress", "scene_receipts"):
        meta = report["facts"][fact]
        assert meta["production_writer_count"] == 0, fact
        assert not [
            row for row in meta["writers"]
            if row["classification"] in {"production", "production_tooling"}
        ]


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
