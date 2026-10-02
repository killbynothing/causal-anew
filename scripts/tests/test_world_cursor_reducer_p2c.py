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

from runtime.world_cursor_reducer import WorldCursorReducer
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_cursor_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_reducer_normalizes_and_returns_copy():
    reducer = WorldCursorReducer(
        {"worldline": "", "run": 99, "ch_anchor": 1, "location": "A"},
        run_no=3,
    )
    assert reducer.snapshot()["run"] == 3
    assert reducer.snapshot()["worldline"] == "WMAIN"
    leaked = reducer.snapshot()
    leaked["location"] = "MUTATED"
    assert reducer.snapshot()["location"] == "A"


def test_session_cursor_alias_cannot_mutate_authority():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-cursor",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        before = session.world_cursor
        leaked = session.world_cursor
        leaked["run"] = 999
        leaked["worldline"] = "BAD"
        assert session.world_cursor == before


def test_session_cursor_save_load_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-cursor-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        updated = dict(session.world_cursor)
        updated["location"] = "测试地点"
        session.world_cursor = updated
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-cursor-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor["location"] == "测试地点"
        assert resumed.world_cursor["run"] == session.run_no


def test_calendar_advance_commits_candidate_through_reducer():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-cursor-advance",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        old = session.world_cursor
        target = dict(session.card)
        target["ch_anchor"] = int(old.get("ch_anchor", 0) or 0)
        target["clock"] = "23:59"
        degradations = session._advance_world_cursor_for_card(target)
        assert isinstance(degradations, list)
        assert session.world_cursor["run"] == session.run_no
        assert session.world_cursor["worldline"] == old.get("worldline", "WMAIN")
        assert session.world_cursor is not old


def test_authority_map_cursor_one_writer_zero_alias():
    report = _report()
    rows = [
        row for row in report["facts"]["world_cursor"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    assert {row["symbol"] for row in rows} == {
        "WorldCursorReducer._write_world_cursor"
    }, rows
    assert report["facts"]["world_cursor"]["production_writer_count"] == 1
    assert report["facts"]["world_cursor"]["unknown_alias_count"] == 0


def test_free_stage_has_no_direct_cursor_writers():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.world_cursor =" not in source
    assert 'self.world_cursor["run"]' not in source
    assert "self.world_cursor.setdefault" not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
