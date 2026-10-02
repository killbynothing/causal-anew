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

from runtime import free_stage_prototype as proto
from runtime.beat_ledger import FrameBeatState, beat_key


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_frame_beat_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_frame_state_append_only_idempotent_run_isolated_and_copy_safe():
    state = FrameBeatState.empty()
    assert state.mark_done(
        1, "F1", ["BE1", "BE2"],
        source_kind="fixture",
        source_ref="turn:1",
    )
    assert not state.mark_done(
        1, "F1", ["BE1"],
        source_kind="retry",
        source_ref="turn:2",
    )
    assert state.mark_done(
        2, "F1", ["BE1"],
        source_kind="other_run",
        source_ref="turn:3",
    )
    assert state.completed_beats(1, "F1") == {"BE1", "BE2"}
    assert state.completed_beats(2, "F1") == {"BE1"}
    view = state.ledger
    view["1"].clear()
    assert state.completed_beats(1, "F1") == {"BE1", "BE2"}
    assert state.revision == 2
    assert state.last_source == {"kind": "other_run", "ref": "turn:3"}


def test_snapshot_roundtrip_and_legacy_migration():
    legacy_raw = {"3": [beat_key("FRAME", "A"), beat_key("FRAME", "B")]}
    legacy = FrameBeatState.from_snapshot(
        None,
        legacy_completed_beats=legacy_raw,
    )
    assert legacy.completed_beats(3, "FRAME") == {"A", "B"}
    assert legacy.last_source == {"kind": "legacy_snapshot", "ref": "completed_beats"}
    restored = FrameBeatState.from_snapshot(
        legacy.to_dict(),
        legacy_completed_beats={},
    )
    assert restored.to_dict() == legacy.to_dict()


def test_session_frame_beat_save_load_and_projection():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-frame-beat",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session.frame_beat_state.mark_done(
            session.run_no,
            "FRAME",
            ["BE1"],
            source_kind="fixture",
            source_ref="case:1",
        )
        view = session.completed_beats
        view[str(session.run_no)].append("FAKE")
        assert "FAKE" not in session.completed_beats[str(session.run_no)]
        session.save()
        raw = json.loads((state_dir / "p2c-frame-beat.json").read_text(encoding="utf-8"))
        assert raw["frame_beat_state"]["schema_version"] == "free_stage.frame_beat_state.v1"
        resumed = proto.FreeStageSession(
            session_id="p2c-frame-beat",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed_beats == session.completed_beats
        assert resumed.frame_beat_state.last_source == {"kind": "fixture", "ref": "case:1"}


def test_session_progress_marks_frame_beats_through_owner():
    card = {
        "scene_id": "FRAME_SCENE",
        "scene_frame": {"frame_id": "FRAME_X"},
        "must_happen": [
            {"id": "M1", "frame_beat": ["BE1", "BE2"]},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-frame-progress",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.card = card
        session._mark_frame_beats_for_progress(card, ["M1"])
        assert session.frame_beat_state.completed_beats(session.run_no, "FRAME_X") == {"BE1", "BE2"}
        assert session.frame_beat_state.last_source["kind"] == "must_happen_progress"


def test_no_direct_completed_beats_mutation_remains():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.completed_beats =" not in source
    assert "self.completed_beats[" not in source
    assert "frame_beat_ledger.mark_done(self.completed_beats" not in source
    assert "self.frame_beat_state.mark_done(" in source


def test_authority_map_reports_zero_frame_beat_production_and_unknown_writers():
    report = _audit_report()
    meta = report["facts"]["completed_beats"]
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
