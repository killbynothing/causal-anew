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
from runtime.world_cursor_state import WorldCursorOwner
from runtime.world_commit import P2A_WORLD_MIGRATED_FACTS, P2A_WORLD_MIGRATION_DEBT


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c7_authority_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_owner_view_is_copy_safe_and_preserves_orthogonal_axes():
    owner = WorldCursorOwner(
        {"ch_anchor": 3, "world_clock": "10:00", "run": 2, "worldline": "WALT"}
    )
    leaked = owner.view()
    leaked["ch_anchor"] = 999
    leaked["worldline"] = "EVIL"
    assert owner.view() == {
        "ch_anchor": 3,
        "world_clock": "10:00",
        "run": 2,
        "worldline": "WALT",
    }

    advanced = owner.advance(ch_anchor=4, world_clock="09:00")
    assert advanced["ch_anchor"] == 4
    assert advanced["world_clock"] == "09:00"
    assert advanced["run"] == 2
    assert advanced["worldline"] == "WALT"


def test_owner_rejected_advance_is_atomic_and_explicit_replace_can_flashback():
    owner = WorldCursorOwner(
        {"ch_anchor": 4, "world_clock": "12:00", "run": 3, "worldline": "WMAIN"}
    )
    before = owner.view()
    try:
        owner.advance(ch_anchor=3, world_clock="23:00")
    except ValueError:
        pass
    else:
        raise AssertionError("backward normal transition must be rejected")
    assert owner.view() == before

    replaced = owner.replace(
        {"ch_anchor": 0, "world_clock": "20:10", "run": 3, "worldline": "WMAIN"}
    )
    assert replaced["ch_anchor"] == 0
    assert replaced["run"] == 3


def test_session_cursor_is_copy_only_and_save_load_owned():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c7-roundtrip",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        original = session.world_cursor
        leaked = session.world_cursor
        leaked["ch_anchor"] = 999
        leaked["run"] = 99
        assert session.world_cursor == original

        session._replace_world_cursor(
            {
                "ch_anchor": int(original["ch_anchor"]) + 1,
                "world_clock": original["world_clock"],
                "run": session.run_no,
                "worldline": original["worldline"],
            }
        )
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c7-roundtrip",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor == session.world_cursor


def test_domain_envelope_cursor_wins_only_through_owner_on_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c7-domain",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session.save()
        path = state_dir / "p2c7-domain.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["world_cursor"]["ch_anchor"] = 99
        raw["domain_state"]["world_cursor"]["ch_anchor"] = 7
        raw["domain_state"]["world_cursor"]["world_clock"] = "21:05"
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        resumed = proto.FreeStageSession(
            session_id="p2c7-domain",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_cursor["ch_anchor"] == 7
        assert resumed.world_cursor["world_clock"] == "21:05"
        assert resumed.world_cursor["run"] == resumed.run_no


def test_session_advance_rejection_keeps_cursor_and_returns_degradation():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c7-advance",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        current = session.world_cursor
        session._replace_world_cursor(
            {
                "ch_anchor": 10,
                "world_clock": "20:00",
                "run": session.run_no,
                "worldline": current["worldline"],
            }
        )
        before = session.world_cursor
        degradations = session._advance_world_cursor_for_card(
            {"scene_id": "PAST", "ch_anchor": 9, "world_clock": "23:00"}
        )
        assert degradations
        assert session.world_cursor == before


def test_authority_map_zeroes_world_cursor_writers_and_p2a_debt():
    report = _audit()
    meta = report["facts"]["world_cursor"]
    assert meta["target_owner"] == "WorldCursorOwner"
    rows = [
        row for row in meta["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert rows == [], rows
    assert meta["production_writer_count"] == 0
    assert meta["unknown_alias_count"] == 0
    assert set(P2A_WORLD_MIGRATION_DEBT) == set()
    assert "world_cursor" in set(P2A_WORLD_MIGRATED_FACTS)


def test_free_stage_has_no_direct_world_cursor_mutation():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    for token in (
        "self.world_cursor =",
        "self.world_cursor[",
        "self.world_cursor.update(",
        "self.world_cursor.setdefault(",
    ):
        assert token not in source, token
    assert "def _replace_world_cursor(" in source
    assert "self._world_cursor_owner.advance(" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
