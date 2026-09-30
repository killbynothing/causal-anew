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

from runtime import beat_state
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_beat_completion_is_idempotent_and_first_evidence_wins():
    ledger = {}
    instance = beat_state.scene_instance_id("S1", 1)
    first = beat_state.commit_completion(
        ledger, scene_id="S1", scene_instance_id=instance,
        beat_id="M1", turn=1, source_kind="visible", source_ref="r1",
    )
    retry = beat_state.commit_completion(
        ledger, scene_id="S1", scene_instance_id=instance,
        beat_id="M1", turn=9, source_kind="later", source_ref="r2",
    )
    assert first.committed is True
    assert retry.committed is False
    assert retry.record["turn"] == 1
    assert beat_state.project_completed(ledger, instance) == ["M1"]


def test_revisit_does_not_inherit_prior_scene_instance():
    ledger = {}
    first = beat_state.scene_instance_id("S1", 1)
    beat_state.commit_completion(
        ledger, scene_id="S1", scene_instance_id=first,
        beat_id="M1", turn=1, source_kind="visible",
    )
    second = beat_state.scene_instance_id("S1", 2)
    assert beat_state.project_completed(ledger, second) == []
    assert beat_state.project_completed_by_card(ledger, {"S1": 2}) == {}


def test_legacy_migration_marks_source_without_faking_player_receipt():
    ledger, visits, current = beat_state.migrate_legacy(
        current_scene_id="S2",
        card_history=["S1", "S2"],
        completed=["B2"],
        completed_by_card={"S1": ["A1"]},
    )
    assert visits == {"S1": 1, "S2": 1}
    assert beat_state.project_completed(ledger, current) == ["B2"]
    assert all(row["legacy"] for row in ledger.values())
    assert all(row["source_kind"] == "legacy_snapshot" for row in ledger.values())


def test_runtime_append_paths_delegate_to_beat_reducer():
    source = inspect.getsource(proto.FreeStageSession)
    assert "self.completed.append(" not in source
    assert "self.completed.extend(" not in source
    assert "self.completed_by_card[" not in source
    assignment_lines = [
        line.strip()
        for line in source.splitlines()
        if "self.completed =" in line
    ]
    assert assignment_lines == [
        "self.completed = beat_state.project_completed(",
    ]
    assert "beat_state.commit_completion" in inspect.getsource(proto.FreeStageSession._beat_complete)


def test_session_scene_revisit_gets_new_instance_and_flashback_contract_restores_old_one():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-visit",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        sid = str(session.card.get("scene_id", session.card_path))
        first = session.beat_scene_instance_id
        session._beat_complete("A1", turn_no=1, source_kind="fixture")
        session.card_history.append(sid)
        session._beat_enter_scene(sid)
        second = session.beat_scene_instance_id
        assert second != first
        assert session.completed == []
        session._beat_enter_scene(sid, restore_instance_id=first)
        assert session.completed == ["A1"]


def test_flashback_return_frame_persists_beat_instance():
    enter_source = inspect.getsource(proto.FreeStageSession._maybe_enter_ryuya_flashback)
    return_source = inspect.getsource(proto.FreeStageSession._maybe_transition)
    assert '"beat_scene_instance_id": self.beat_scene_instance_id' in enter_source
    assert 'return_frame.get("beat_scene_instance_id")' in return_source


def test_save_load_preserves_beat_event_ledger():
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
        session._beat_complete("X1", turn_no=1, source_kind="fixture", source_ref="x")
        instance = session.beat_scene_instance_id
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-beat",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.beat_scene_instance_id == instance
        assert resumed.completed == ["X1"]
        assert resumed.beat_events == session.beat_events


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
