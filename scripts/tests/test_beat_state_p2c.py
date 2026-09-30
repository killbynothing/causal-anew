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
from runtime.causal_protocol import RuntimeScope


CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


def _scope(scene="S1:visit:1"):
    return RuntimeScope(
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="beat-p2c",
        scene_instance_id=scene,
    )


def _caller(**_kwargs):
    return json.dumps(
        {
            "pre_speech": {"notice": "x", "intention": "y", "social_move": "primary"},
            "turns": [{"speaker": "折原龙也", "text": "嗯。", "stage": "", "participation_mode": "speak"}],
            "mh_progress": [],
            "director_note": "",
        },
        ensure_ascii=False,
    )


def test_beat_state_idempotency_and_conflict():
    states = {}
    first = beat_state.commit_beat(
        states,
        scope=_scope(),
        scene_id="S1",
        beat_id="B1",
        turn=1,
        source_kind="observed_progress",
        evidence_refs=("scene:r1",),
        event_id="beat:event:1",
    )
    assert first.committed is True
    retry = beat_state.commit_beat(
        states,
        scope=_scope(),
        scene_id="S1",
        beat_id="B1",
        turn=1,
        source_kind="observed_progress",
        evidence_refs=("scene:r1",),
        event_id="beat:event:1",
    )
    assert retry.committed is False
    assert beat_state.completed_for_scope(states, _scope()) == ["B1"]

    try:
        beat_state.commit_beat(
            states,
            scope=_scope(),
            scene_id="S1",
            beat_id="B2",
            turn=1,
            source_kind="observed_progress",
            evidence_refs=("scene:r2",),
            event_id="beat:event:1",
        )
    except beat_state.BeatConflict:
        pass
    else:
        raise AssertionError("same beat event id with different payload must conflict")
    assert beat_state.completed_for_scope(states, _scope()) == ["B1"]


def test_beat_requires_evidence_and_legacy_migration_does_not_fake_player_action():
    states = {}
    try:
        beat_state.commit_beat(
            states,
            scope=_scope(),
            scene_id="S1",
            beat_id="B1",
            turn=1,
            source_kind="observed_progress",
            evidence_refs=(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("beat completion without evidence/source ref must fail")

    migrated = beat_state.migrate_legacy_completed(
        states,
        scope=_scope(),
        scene_id="S1",
        completed=["B1", "B2"],
        source_ref="legacy-session:s1",
    )
    assert migrated == ["B1", "B2"]
    events = states[_scope().scene_instance_id]["events"]
    assert all(row["source_kind"] == "legacy_snapshot" for row in events.values())
    assert not any(
        ref.startswith("player:")
        for row in events.values()
        for ref in row["evidence_refs"]
    )


def test_session_business_completion_uses_beat_commit_not_append_extend():
    source = inspect.getsource(proto.FreeStageSession)
    assert "self.completed.append(" not in source
    assert "self.completed.extend(" not in source

    skip_source = inspect.getsource(proto.FreeStageSession.skip_scene)
    assert "self.completed =" not in skip_source
    assert "self._commit_beat(" in skip_source

    canon_source = inspect.getsource(proto.FreeStageSession._emit_canon_segment)
    assert "self.completed.append(" not in canon_source
    assert "self._commit_beat(" in canon_source


def test_scene_receipt_has_stable_id_and_drives_beat_projection():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="beat-receipt",
            card_path=CARD,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
            intent_caller=None,
        )
        r1 = session._record_scene_receipt(
            "RP2", owner="actor", turn_no=2, source_input="说吧", source_kind="observed_progress"
        )
        r2 = session._record_scene_receipt(
            "RP2", owner="actor", turn_no=99, source_input="different", source_kind="observed_progress"
        )
        assert r1["receipt_id"] == r2["receipt_id"]
        session._commit_beat(
            "RP2",
            turn_no=2,
            source_kind="deterministic_evidence",
            evidence_refs=(r1["receipt_id"],),
        )
        assert session.completed == ["RP2"]
        assert session.beat_states


def test_rp4_completion_is_sourced_by_world_receipt_and_survives_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="beat-rp4",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
            intent_caller=None,
        )
        session.completed = ["RP1", "RP2", "RP3"]
        session.branch_progress = ["prologue_pendant_offered"]
        session.step({"speech": "好，我收下。", "action": "", "thought": ""})
        assert "RP4" in session.completed
        tx = session._world_transaction("ryuya_pendant_disposition")
        assert tx and tx["receipt"]["receipt_id"]
        state = session.beat_states[session._current_runtime_scope().scene_instance_id]
        rp4 = [
            row for row in state["events"].values()
            if row.get("beat_id") == "RP4"
        ]
        assert len(rp4) == 1
        assert tx["receipt"]["receipt_id"] in rp4[0]["evidence_refs"]
        session.save()

        resumed = proto.FreeStageSession(
            session_id="beat-rp4",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
            intent_caller=None,
        )
        assert resumed.completed == session.completed
        assert resumed.beat_states == session.beat_states


def test_adapter_debt_is_explicit_not_silently_claimed_done():
    assert set(beat_state.P2C_BEAT_ADAPTER_DEBT) == {
        "legacy_load",
        "reset",
        "scene_enter",
        "flashback_restore",
        "completed_by_card_projection",
    }


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
