#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.world_fact_reducer import WorldFactReducer
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_world_fact_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_reducer_copy_safe_branch_and_receipts():
    reducer = WorldFactReducer(["A"], [{"scene_id": "S", "fact_id": "F"}])
    branches = reducer.branch_snapshot()
    branches.append("B")
    receipts = reducer.receipt_snapshot()
    receipts[0]["fact_id"] = "MUTATED"
    assert reducer.branch_snapshot() == ["A"]
    assert reducer.receipt_snapshot()[0]["fact_id"] == "F"

    assert reducer.add_branch("A") is False
    assert reducer.add_branch("B") is True
    reducer.filter_branch(lambda item: item != "A")
    assert reducer.branch_snapshot() == ["B"]

    assert reducer.append_scene_receipt(
        scene_id="S", fact_id="F", owner="player", turn=1
    ) is False
    assert reducer.append_scene_receipt(
        scene_id="S", fact_id="G", owner="player", turn=2
    ) is True
    assert [row["fact_id"] for row in reducer.receipt_snapshot()] == ["F", "G"]


def test_session_projection_aliases_cannot_mutate_authority():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-world-facts",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.branch_progress = ["A"]
        session.scene_receipts = [{"scene_id": "S", "fact_id": "F"}]
        leaked_branch = session.branch_progress
        leaked_receipts = session.scene_receipts
        leaked_branch.append("B")
        leaked_receipts[0]["fact_id"] = "MUTATED"
        assert session.branch_progress == ["A"]
        assert session.scene_receipts[0]["fact_id"] == "F"


def test_scene_receipt_and_branch_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-world-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session.branch_progress = ["route_a"]
        assert session._record_scene_receipt(
            "route_a", owner="player", turn_no=1, source_input="走这边"
        ) is True
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-world-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.branch_progress == ["route_a"]
        assert resumed._scene_fact_ids() == {"route_a"}
        assert resumed._record_scene_receipt(
            "route_a", owner="player", turn_no=2, source_input="重复"
        ) is False


def test_authority_map_session_world_fact_bypasses_removed():
    report = _report()
    branch_rows = [
        row for row in report["facts"]["branch_progress"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    branch_symbols = {row["symbol"] for row in branch_rows}
    assert "WorldFactReducer._write_branch_progress" in branch_symbols
    assert not any(symbol.startswith("FreeStageSession.") for symbol in branch_symbols)

    receipt_rows = [
        row for row in report["facts"]["scene_receipts"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    assert {row["symbol"] for row in receipt_rows} == {
        "WorldFactReducer._write_scene_receipts"
    }


def test_free_stage_has_no_direct_branch_or_scene_receipt_writers():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    for forbidden in (
        "self.branch_progress.append",
        "self.branch_progress =",
        "self.scene_receipts.append",
        "self.scene_receipts =",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
