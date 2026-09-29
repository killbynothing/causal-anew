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
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT, WorldCursorState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_cursor_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_cursor_state_is_copy_only_and_run_scoped():
    state = WorldCursorState(
        {"ch_anchor": 1, "world_clock": "10:00", "run": 1, "worldline": "WMAIN"},
        run_no=1,
    )
    view = state.view()
    view["run"] = 99
    view["ch_anchor"] = 99
    assert state.view()["run"] == 1
    assert state.view()["ch_anchor"] == 1
    try:
        WorldCursorState({"ch_anchor": 1, "world_clock": "10:00"}, run_no=0)
    except ValueError:
        pass
    else:
        raise AssertionError("run=0 must not become writable cursor state")


def test_cursor_advance_is_monotonic_and_failure_does_not_mutate():
    state = WorldCursorState(
        {"ch_anchor": 1, "world_clock": "10:00", "run": 2, "worldline": "WMAIN"},
        run_no=2,
    )
    advanced = state.advance(ch_anchor=2, world_clock="11:00")
    assert advanced["ch_anchor"] == 2
    assert advanced["world_clock"] == "11:00"
    before = state.view()
    try:
        state.advance(ch_anchor=1, world_clock="09:00")
    except ValueError:
        pass
    else:
        raise AssertionError("cursor regression must fail")
    assert state.view() == before


def test_session_cursor_roundtrip_and_view_cannot_mutate_owner():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-cursor",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        original = session.world_cursor
        leaked = session.world_cursor
        leaked["run"] = 999
        leaked["worldline"] = "EVIL"
        assert session.world_cursor == original

        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-cursor",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor == original
        assert resumed.world_cursor["run"] == resumed.run_no


def test_session_advance_rejects_backward_target_without_cursor_write():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-cursor-back",
            state_dir=Path(tmp) / "states",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._world_cursor_state.replace(
            {"ch_anchor": 10, "world_clock": "20:00", "run": session.run_no, "worldline": "WMAIN"},
            run_no=session.run_no,
        )
        before = session.world_cursor
        degradations = session._advance_world_cursor_for_card(
            {"ch_anchor": 9, "clock": "19:00"}
        )
        assert degradations
        assert session.world_cursor == before


def test_authority_map_zeroes_world_cursor_direct_writers():
    report = _audit()
    rows = [
        row for row in report["facts"]["world_cursor"]["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert rows == [], rows
    debt = set(P2A_WORLD_MIGRATION_DEBT)
    assert "world_cursor" not in debt
    assert debt == {"branch_progress"}
    assert "player_state" not in debt


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
