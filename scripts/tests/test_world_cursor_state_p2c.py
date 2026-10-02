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
from runtime.world_cursor_state import WORLD_CURSOR_STATE_SCHEMA, WorldCursorState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_cursor_state_is_copy_only_and_advance_is_monotonic():
    state = WorldCursorState.from_cursor(
        {"ch_anchor": 16, "world_clock": "18:00", "worldline": "WMAIN"},
        run=2,
    )
    visible = state.cursor()
    visible["ch_anchor"] = 999
    assert state.cursor()["ch_anchor"] == 16

    advanced = state.advance(
        run=2,
        ch_anchor=17,
        world_clock="19:30",
        source_kind="test_transition",
    )
    assert advanced["ch_anchor"] == 17
    assert advanced["run"] == 2
    assert advanced["worldline"] == "WMAIN"
    try:
        state.advance(
            run=2,
            ch_anchor=16,
            world_clock="18:00",
            source_kind="bad_backtrack",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("world cursor must reject backward transition")
    assert state.cursor()["ch_anchor"] == 17


def test_saved_state_and_legacy_cursor_roundtrip():
    state = WorldCursorState.from_cursor(
        {"ch_anchor": 16, "world_clock": "18:00", "worldline": "WMAIN", "location": "北京"},
        run=3,
    )
    raw = state.to_dict()
    assert raw["schema_version"] == WORLD_CURSOR_STATE_SCHEMA
    loaded = WorldCursorState.from_saved(raw, legacy_cursor={}, run=3)
    assert loaded.cursor() == state.cursor()

    legacy = WorldCursorState.from_saved(
        None,
        legacy_cursor={"ch_anchor": 15, "world_clock": "12:00", "worldline": "WALT"},
        run=4,
    )
    assert legacy.cursor()["run"] == 4
    assert legacy.cursor()["worldline"] == "WALT"


def test_session_world_cursor_projection_is_read_only_and_persists():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="cursor",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        original = session.world_cursor
        visible = session.world_cursor
        visible["worldline"] = "FAKE"
        assert session.world_cursor == original

        session._world_cursor_state.replace(
            {**original, "location": "fixture"},
            run=session.run_no,
            source_kind="test",
        )
        session.save()
        disk = json.loads((state_dir / "cursor.json").read_text(encoding="utf-8"))
        assert disk["world_cursor"]["location"] == "fixture"
        assert disk["world_cursor_state"]["cursor"]["location"] == "fixture"

        resumed = proto.FreeStageSession(
            session_id="cursor",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor["location"] == "fixture"


def test_domain_envelope_can_supply_legacy_cursor_without_becoming_writer():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        state_dir.mkdir(parents=True, exist_ok=True)
        seed = proto.FreeStageSession(
            session_id="cursor-domain",
            state_dir=state_dir,
            autosave=False,
            load_existing=False,
            caller=_caller,
        )._state_payload()
        seed.pop("world_cursor_state", None)
        seed["world_cursor"]["location"] = "wrong-legacy"
        seed["domain_state"]["world_cursor"]["location"] = "domain-source"
        (state_dir / "cursor-domain.json").write_text(
            json.dumps(seed, ensure_ascii=False),
            encoding="utf-8",
        )
        resumed = proto.FreeStageSession(
            session_id="cursor-domain",
            state_dir=state_dir,
            autosave=False,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor["location"] == "domain-source"


def test_production_has_no_direct_world_cursor_mutator():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = [
        r"self\.world_cursor\s*=",
        r"self\.world_cursor\[",
        r"self\.world_cursor\.setdefault\(",
        r"self\.world_cursor\.update\(",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, source), pattern
    assert "self._world_cursor_state.advance(" in source
    assert "self._world_cursor_state.replace(" in source


def test_authority_map_has_zero_world_cursor_production_writers():
    audit_path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("cursor_authority_audit", audit_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.build_report(False)
    assert report["facts"]["world_cursor"]["production_writer_count"] == 0


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
