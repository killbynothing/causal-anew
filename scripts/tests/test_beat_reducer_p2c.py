#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.beat_state import BeatReducer
from runtime.causal_protocol import RuntimeScope
from runtime import free_stage_prototype as proto


def scope(instance: str, scene="S1"):
    return RuntimeScope(
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="beat-p2c",
        scene_instance_id=instance,
    )


def test_reducer_completion_is_idempotent_and_receipted():
    beats = BeatReducer.new("S1")
    first = beats.complete(
        scope=scope(beats.active_scene_instance_id),
        beat_ids=["M1", "M2", "M1"],
        turn=2,
        source_kind="observed_progress",
        request_id="req:2",
        source_refs=["visible-turn:2"],
    )
    assert first.newly_completed == ("M1", "M2")
    assert beats.completed == ["M1", "M2"]
    retry = beats.complete(
        scope=scope(beats.active_scene_instance_id),
        beat_ids=["M1", "M2"],
        turn=3,
        source_kind="observed_progress",
        request_id="req:3",
    )
    assert retry.newly_completed == ()
    raw = beats.to_dict()
    assert len(raw["receipts"]) == 2
    assert all(row["receipt"]["producer"] == "BeatReducer" for row in raw["receipts"])


def test_same_scene_revisit_gets_new_instance_and_no_old_completion():
    beats = BeatReducer.new("S1")
    first_instance = beats.active_scene_instance_id
    beats.complete(
        scope=scope(first_instance),
        beat_ids=["M1"],
        turn=1,
        source_kind="fixture",
        request_id="first",
    )
    beats.enter_scene("S2")
    second_s1 = beats.enter_scene("S1")
    assert second_s1 != first_instance
    assert beats.completed == []
    beats.complete(
        scope=scope(second_s1),
        beat_ids=["M2"],
        turn=4,
        source_kind="fixture",
        request_id="second",
    )
    assert beats.completed == ["M2"]
    beats.resume_scene("S1", first_instance)
    assert beats.completed == ["M1"]


def test_legacy_snapshot_migration_marks_source_without_player_receipt():
    payload = {
        "schema_version": "free_stage.session.v1",
        "completed": ["M2"],
        "completed_by_card": {"S0": ["A1"], "S1": ["M1"]},
    }
    beats = BeatReducer.from_session_payload(
        payload,
        current_scene_id="S1",
        card_history=["S0", "S1"],
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="legacy",
    )
    assert beats.completed == ["M1", "M2"]
    raw = beats.to_dict()
    assert raw["migration"]["mode"] == "legacy_snapshot_no_player_receipt"
    assert raw["receipts"]
    assert all(row["source_kind"] == "legacy_snapshot" for row in raw["receipts"])
    assert all(row["receipt"]["producer"] == "BeatReducer" for row in raw["receipts"])
    assert all(
        not any(str(ref).startswith("player:") for ref in row["receipt"]["source_refs"])
        for row in raw["receipts"]
    )


def test_session_completed_is_read_only_projection_and_scope_matches_beat_instance():
    prop = inspect.getattr_static(proto.FreeStageSession, "completed")
    by_card = inspect.getattr_static(proto.FreeStageSession, "completed_by_card")
    assert isinstance(prop, property) and prop.fset is None
    assert isinstance(by_card, property) and by_card.fset is None

    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="beat-session",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=lambda **kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        assert session.completed == []
        newly = session._complete_beats(
            ["X1"],
            turn_no=1,
            source_kind="fixture",
            source_refs=("fixture:1",),
        )
        assert newly == ["X1"]
        assert session.completed == ["X1"]
        assert session._current_runtime_scope().scene_instance_id == session.beats.active_scene_instance_id
        try:
            session.completed = ["BAD"]
        except AttributeError:
            pass
        else:
            raise AssertionError("completed must have no production setter")


def test_save_load_preserves_receipts_and_projection():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="beat-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=lambda **kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        session._complete_beats(["X1", "X2"], turn_no=1, source_kind="fixture")
        original_instance = session.beats.active_scene_instance_id
        session.save()

        resumed = proto.FreeStageSession(
            session_id="beat-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=lambda **kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        assert resumed.completed == ["X1", "X2"]
        assert resumed.beats.active_scene_instance_id == original_instance
        assert resumed.beats.to_dict()["receipts"] == session.beats.to_dict()["receipts"]


def test_production_source_has_no_completed_business_writes():
    source = inspect.getsource(proto.FreeStageSession)
    forbidden = (
        "self.completed =",
        "self.completed.append(",
        "self.completed.extend(",
        "self.completed.remove(",
        "self.completed.clear(",
        "self.completed_by_card[",
    )
    for token in forbidden:
        assert token not in source, token
    assert "self.beats.complete(" in source
    assert "self.beats.enter_scene(" in source
    assert "self.beats.resume_scene(" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
