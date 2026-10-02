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

from runtime import beat_reducer
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_canon_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_canon_state_copy_safe_and_update_source():
    state = beat_reducer.CanonPerformanceState.empty()
    assert state.update_scene(
        "S1",
        add_completed=("SEG1",),
        add_hidden=("SEG1",),
        pending_stop="STOP1",
        player_position="counter",
        source_kind="canon_segment",
        source_ref="SEG1",
        turn=2,
    )
    view = state.scene("S1")
    view["completed_segments"].append("FAKE")
    view["pending_stop"] = "FAKE"
    assert state.scene("S1") == {
        "completed_segments": ["SEG1"],
        "not_visible_segments": ["SEG1"],
        "pending_stop": "STOP1",
        "player_position": "counter",
    }
    assert state.sources["S1"]["source_kind"] == "canon_segment"


def test_update_can_clear_stop_without_erasing_position():
    state = beat_reducer.CanonPerformanceState.empty()
    state.update_scene(
        "S1",
        pending_stop="STOP1",
        player_position="counter",
        source_kind="fixture",
    )
    state.update_scene(
        "S1",
        pending_stop="",
        source_kind="player_input",
        source_ref="turn:3",
        turn=3,
    )
    assert state.scene("S1")["pending_stop"] == ""
    assert state.scene("S1")["player_position"] == "counter"


def test_legacy_migration_and_snapshot_roundtrip():
    legacy_raw = {
        "S1": {
            "completed_segments": ["SEG1"],
            "not_visible_segments": [],
            "pending_stop": "P1",
            "player_position": "gate",
        }
    }
    legacy = beat_reducer.CanonPerformanceState.from_snapshot(
        None,
        legacy_state=legacy_raw,
    )
    assert legacy.scene("S1")["completed_segments"] == ["SEG1"]
    restored = beat_reducer.CanonPerformanceState.from_snapshot(
        legacy.to_dict(),
        legacy_state={},
    )
    assert restored.to_dict() == legacy.to_dict()


def test_session_canon_state_save_load_and_copy_safe():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-canon",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        scene_id = str(session.card.get("scene_id", session.card_path))
        session._canon_update(
            add_completed=("SEG1",),
            pending_stop="STOP1",
            player_position="gate",
            source_kind="fixture",
            source_ref="case:1",
            turn_no=1,
        )
        view = session.canon_performance_state
        view[scene_id]["completed_segments"].append("FAKE")
        assert session._canon_scene_state()["completed_segments"] == ["SEG1"]
        session.save()
        raw = json.loads((state_dir / "p2c-canon.json").read_text(encoding="utf-8"))
        assert raw["canon_performance"]["schema_version"] == "free_stage.canon_performance_state.v1"
        resumed = proto.FreeStageSession(
            session_id="p2c-canon",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.canon_performance_state == session.canon_performance_state


def test_no_mutable_canon_state_reference_or_direct_writer_remains():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.canon_performance_state =" not in source
    assert "self.canon_performance_state.setdefault(" not in source
    assert "completed_segments.append(" not in source
    assert "hidden_segments.append(" not in source
    assert 'canon_state["pending_stop"] =' not in source
    assert 'canon_state["player_position"] =' not in source
    assert "self.canon_performance.update_scene(" in source


def test_authority_map_reports_zero_canon_production_and_unknown_writers():
    report = _audit_report()
    meta = report["facts"]["canon_performance_state"]
    rows = [
        row for row in meta["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert meta["production_writer_count"] == 0, rows
    assert meta["unknown_alias_count"] == 0, rows
    assert rows == [], rows


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
