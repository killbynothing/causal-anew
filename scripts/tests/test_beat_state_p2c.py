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

from runtime.beat_reducer import BeatState
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_beat_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_legacy_completed_migrates_with_explicit_legacy_source():
    state = BeatState.from_snapshot(
        None,
        scene_id="S1",
        legacy_completed=["B1", "B2", "B1"],
    )
    assert state.completed == ["B1", "B2"]
    assert state.receipts["B1"]["source_kind"] == "legacy_snapshot"
    assert state.receipts["B1"]["source_ref"] == "free_stage.session.v1:completed"


def test_first_completion_keeps_source_and_retry_is_idempotent():
    state = BeatState.empty("S1")
    assert state.complete("B1", source_kind="observed_progress", source_ref="turn:3", turn=3)
    before = state.to_dict()
    assert not state.complete("B1", source_kind="other", source_ref="turn:4", turn=4)
    assert state.to_dict() == before
    assert state.receipts["B1"]["turn"] == 3


def test_scene_replace_resets_only_current_scene_completion():
    state = BeatState.empty("S1")
    state.complete_many(["A", "B"], source_kind="canon_segment", source_ref="seg", turn=1)
    state.replace_scene("S2", ["C"], source_kind="flashback_return", source_ref="S1", turn=2)
    assert state.scene_id == "S2"
    assert state.completed == ["C"]
    assert set(state.receipts) == {"C"}
    assert state.receipts["C"]["source_kind"] == "flashback_return"


def test_free_stage_completed_is_projection_and_save_load_keeps_receipts():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-beat",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._beat_complete(
            "TEST_BEAT",
            source_kind="fixture",
            source_ref="case:1",
            turn_no=1,
        )
        view = session.completed
        view.append("MUTATED_COPY")
        assert session.completed == ["TEST_BEAT"]
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-beat",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["TEST_BEAT"]
        assert resumed.beat_state.receipts["TEST_BEAT"]["source_ref"] == "case:1"


def test_compat_completed_setter_stays_outside_production_paths():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-compat",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.completed = ["A", "B"]
        assert session.completed == ["A", "B"]
        assert session.beat_state.receipts["A"]["source_kind"] == "compat_assignment"


def test_no_direct_completed_mutation_remains_in_free_stage_production_source():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    direct = re.findall(
        r"self\.completed(?:\s*=|\.append\(|\.extend\(|\.remove\(|\.clear\()",
        source,
    )
    assert direct == []


def test_authority_map_reports_zero_completed_production_writers():
    report = _audit_report()
    fact = report["facts"]["completed"]
    assert fact["production_writer_count"] == 0
    assert not [
        row for row in fact["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
