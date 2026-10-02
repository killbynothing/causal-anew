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
from runtime.world_cursor_state import WorldCursorState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_cursor_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_cursor_state_copy_safe_sources_and_snapshot_roundtrip():
    state = WorldCursorState.empty(
        {"ch_anchor": 1, "world_clock": "10:00", "run": 2, "worldline": "WMAIN"},
        run_no=2,
        source_kind="fixture",
        source_ref="init",
    )
    view = state.cursor
    view["ch_anchor"] = 999
    assert state.cursor["ch_anchor"] == 1
    assert state.advance(
        ch_anchor=2,
        world_clock="11:30",
        run_no=2,
        source_kind="scene_transition",
        source_ref="S2",
    )
    assert state.cursor["ch_anchor"] == 2
    assert state.revision == 1
    assert state.last_source == {"kind": "scene_transition", "ref": "S2"}
    restored = WorldCursorState.from_snapshot(
        state.to_dict(),
        legacy_cursor={},
        run_no=2,
    )
    assert restored.cursor == state.cursor
    assert restored.revision == state.revision
    assert restored.last_source == state.last_source


def test_normal_advance_rejects_backward_without_mutating_state():
    state = WorldCursorState.empty(
        {"ch_anchor": 3, "world_clock": "12:00", "run": 1, "worldline": "WMAIN"},
        run_no=1,
    )
    before = state.to_dict()
    try:
        state.advance(
            ch_anchor=2,
            world_clock="11:00",
            run_no=1,
            source_kind="scene_transition",
            source_ref="BACKWARD",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("normal cursor advance must reject backward time")
    assert state.to_dict() == before


def test_explicit_flashback_replace_preserves_compat_behavior_with_source():
    state = WorldCursorState.empty(
        {"ch_anchor": 8, "world_clock": "22:00", "run": 1, "worldline": "WMAIN"},
        run_no=1,
    )
    assert state.replace(
        {"ch_anchor": 1, "world_clock": "19:00", "run": 1, "worldline": "WMAIN"},
        run_no=1,
        source_kind="flashback_scene_enter",
        source_ref="RYUYA_PROLOGUE",
    )
    assert state.cursor["ch_anchor"] == 1
    assert state.last_source["kind"] == "flashback_scene_enter"


def test_session_world_cursor_is_copy_safe_and_persists_envelope():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-cursor",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
            run_no=2,
        )
        view = session.world_cursor
        view["run"] = 999
        assert session.world_cursor["run"] == 2
        session._cursor_replace(
            {"ch_anchor": 4, "world_clock": "15:20", "run": 2, "worldline": "WMAIN"},
            source_kind="fixture",
            source_ref="cursor:test",
        )
        session.save()
        raw = json.loads((state_dir / "p2c-cursor.json").read_text(encoding="utf-8"))
        assert raw["world_cursor_state"]["schema_version"] == "free_stage.world_cursor_state.v1"
        assert raw["world_cursor"]["ch_anchor"] == 4
        resumed = proto.FreeStageSession(
            session_id="p2c-cursor",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor == session.world_cursor
        assert resumed.world_cursor_state.last_source == {"kind": "fixture", "ref": "cursor:test"}


def test_legacy_cursor_migrates_without_losing_run_worldline():
    state = WorldCursorState.from_snapshot(
        None,
        legacy_cursor={
            "ch_anchor": 6,
            "world_clock": "18:45",
            "run": 7,
            "worldline": "WALT",
        },
        run_no=7,
    )
    assert state.cursor == {
        "ch_anchor": 6,
        "world_clock": "18:45",
        "run": 7,
        "worldline": "WALT",
    }
    assert state.last_source == {"kind": "legacy_snapshot", "ref": "world_cursor"}


def test_no_direct_world_cursor_mutation_remains_in_free_stage_source():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    for token in (
        "self.world_cursor =",
        'self.world_cursor["',
        "self.world_cursor.update(",
        "self.world_cursor.setdefault(",
    ):
        assert token not in source, token
    assert "self.world_cursor_state.replace(" in source
    assert "self.world_cursor_state.advance(" in source


def test_authority_map_reports_zero_cursor_production_and_unknown_writers():
    report = _audit_report()
    meta = report["facts"]["world_cursor"]
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
