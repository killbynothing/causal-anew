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

from runtime.beat_state import BEAT_STATE_SCHEMA, BeatState
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_beat_state_idempotent_completion_and_snapshot():
    state = BeatState()
    assert state.complete("B1", scene_id="S1", source_kind="observed", turn=1) is True
    assert state.complete("B1", scene_id="S1", source_kind="observed", turn=1) is False
    assert state.complete_many(
        ["B1", "B2", "B2"],
        scene_id="S1",
        source_kind="observed",
        turn=2,
    ) == ["B2"]
    assert state.completed() == ["B1", "B2"]
    assert len(state.events()) == 2
    state.snapshot_card("S1")
    projected = state.completed_by_card()
    projected["S1"].append("FAKE")
    assert state.completed_by_card()["S1"] == ["B1", "B2"]


def test_legacy_load_marks_unresolved_without_fabricating_events():
    state = BeatState.from_saved(
        None,
        legacy_completed=["B1", "B2"],
        legacy_completed_by_card={"S0": ["A1"]},
    )
    raw = state.to_dict()
    assert raw["schema_version"] == BEAT_STATE_SCHEMA
    assert raw["completed"] == ["B1", "B2"]
    assert raw["completed_by_card"] == {"S0": ["A1"]}
    assert raw["events"] == []
    assert raw["legacy_unresolved"] == ["B1", "B2"]


def test_beat_state_owns_frame_beats_and_canon_performance():
    state = BeatState()
    assert state.mark_frame_beats(1, "FRAME", ["BE1", "BE1", "BE2"]) == ["BE1", "BE2"]
    assert state.mark_frame_beats(1, "FRAME", ["BE2"]) == []
    assert state.completed_frame_beats(1, "FRAME") == {"BE1", "BE2"}
    assert state.completed_frame_beats(2, "FRAME") == set()

    visible = state.frame_beats()
    visible["1"].append("FRAME::FAKE")
    assert state.completed_frame_beats(1, "FRAME") == {"BE1", "BE2"}

    assert state.record_canon_segment(
        "S1", "SEG1", pending_stop="STOP1", player_position="gate"
    ) is True
    assert state.record_canon_segment(
        "S1", "SEG1", hidden=True, pending_stop="", player_position="counter"
    ) is False
    canon = state.canon_scene_state("S1")
    assert canon["completed_segments"] == ["SEG1"]
    assert canon["not_visible_segments"] == ["SEG1"]
    assert canon["pending_stop"] == ""
    assert canon["player_position"] == "counter"
    canon["completed_segments"].append("FAKE")
    assert state.canon_scene_state("S1")["completed_segments"] == ["SEG1"]


def test_tail_legacy_fields_migrate_into_existing_beat_state_v1():
    state = BeatState.from_saved(
        {
            "schema_version": BEAT_STATE_SCHEMA,
            "completed": ["B1"],
            "completed_by_card": {},
            "events": [],
            "legacy_unresolved": [],
        },
        legacy_completed_beats={"1": ["FRAME::BE1"]},
        legacy_canon_performance_state={
            "S1": {
                "completed_segments": ["SEG1"],
                "not_visible_segments": [],
                "pending_stop": "STOP",
                "player_position": "gate",
            }
        },
    )
    assert state.completed_frame_beats(1, "FRAME") == {"BE1"}
    assert state.canon_scene_state("S1")["completed_segments"] == ["SEG1"]
    raw = state.to_dict()
    assert raw["frame_beats"]["1"] == ["FRAME::BE1"]
    assert raw["canon_performance_state"]["S1"]["pending_stop"] == "STOP"


def test_session_completed_properties_are_copy_only():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="beat-copy",
            state_dir=Path(tmp) / "states",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._complete_beat("B1", source_kind="test", turn_no=1)
        visible = session.completed
        visible.append("FAKE")
        assert session.completed == ["B1"]
        session._snapshot_completed("S1")
        by_card = session.completed_by_card
        by_card["S1"].append("FAKE")
        assert session.completed_by_card["S1"] == ["B1"]


def test_session_save_load_prefers_beat_state_and_keeps_legacy_projection():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="beat-save",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._complete_beats(
            ["B1", "B2"],
            source_kind="test",
            turn_no=1,
            source_refs=["fixture"],
        )
        session._snapshot_completed("S1")
        session.save()
        disk = json.loads((state_dir / "beat-save.json").read_text(encoding="utf-8"))
        assert disk["completed"] == ["B1", "B2"]
        assert disk["completed_by_card"]["S1"] == ["B1", "B2"]
        assert disk["beat_state"]["schema_version"] == BEAT_STATE_SCHEMA
        assert len(disk["beat_state"]["events"]) == 2

        resumed = proto.FreeStageSession(
            session_id="beat-save",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["B1", "B2"]
        assert resumed.completed_by_card["S1"] == ["B1", "B2"]
        assert len(resumed._beat_state.events()) == 2

        resumed._beat_state.mark_frame_beats(1, "FRAME", ["BE1"])
        resumed._beat_state.record_canon_segment(
            "S1", "SEG1", pending_stop="STOP", player_position="gate"
        )
        resumed.save()
        disk2 = json.loads((state_dir / "beat-save.json").read_text(encoding="utf-8"))
        assert disk2["completed_beats"]["1"] == ["FRAME::BE1"]
        assert disk2["canon_performance_state"]["S1"]["completed_segments"] == ["SEG1"]


def test_old_session_snapshot_migrates_without_player_receipts():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        state_dir.mkdir(parents=True, exist_ok=True)
        seed = proto.FreeStageSession(
            session_id="legacy-beat",
            state_dir=state_dir,
            autosave=False,
            load_existing=False,
            caller=_caller,
        )._state_payload()
        seed.pop("beat_state", None)
        seed["completed"] = ["LEGACY1"]
        seed["completed_by_card"] = {"OLD": ["LEGACY0"]}
        (state_dir / "legacy-beat.json").write_text(
            json.dumps(seed, ensure_ascii=False),
            encoding="utf-8",
        )
        resumed = proto.FreeStageSession(
            session_id="legacy-beat",
            state_dir=state_dir,
            autosave=False,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["LEGACY1"]
        raw = resumed._beat_state.to_dict()
        assert raw["events"] == []
        assert raw["legacy_unresolved"] == ["LEGACY1"]
        assert resumed.player_action_receipts == {}


def test_production_has_no_direct_completed_mutators():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = [
        r"self\.completed\s*=",
        r"self\.completed\.append\(",
        r"self\.completed\.extend\(",
        r"self\.completed\.remove\(",
        r"self\.completed_by_card\s*=",
        r"self\.completed_by_card\[",
        r"self\.completed_beats\s*=",
        r"frame_beat_ledger\.mark_done\(self\.completed_beats",
        r"self\.canon_performance_state\s*=",
        r"self\.canon_performance_state\.setdefault",
        r'canon_state\[\s*"(?:pending_stop|player_position)"\s*\]\s*=',
    ]
    for pattern in forbidden:
        assert not re.search(pattern, source), pattern
    assert "self._beat_state.complete(" in source
    assert "self._beat_state.complete_many(" in source
    assert "self._beat_state.snapshot_card(" in source
    assert "self._beat_state.mark_frame_beats(" in source
    assert "self._beat_state.record_canon_segment(" in source
    assert "self._beat_state.update_canon_scene(" in source


def test_authority_map_has_zero_tail_beat_writers():
    audit_path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("beat_tail_authority_audit", audit_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.build_report(False)
    assert report["facts"]["completed_beats"]["production_writer_count"] == 0
    assert report["facts"]["canon_performance_state"]["production_writer_count"] == 0


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
