#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import beat_state
from runtime.causal_protocol import RuntimeScope


def scope(scene="S1", visit=1):
    return RuntimeScope(
        worldline="WMAIN", run=1, ch_anchor=1, session_id="beat-fixture",
        scene_instance_id=f"{scene}:visit:{visit}",
    )


def card(scene="S1"):
    return {
        "scene_id": scene,
        "must_happen": [
            {"id": "B1"},
            {"id": "B2", "after": ["B1"]},
            {"id": "B3", "after": ["B2"]},
        ],
    }


def test_legacy_migration_does_not_fabricate_player_receipt():
    state = beat_state.from_snapshot(
        None,
        current_scene_id="S2",
        current_instance_id="S2:visit:2",
        legacy_completed=["X2"],
        legacy_completed_by_card={"S1": ["X1"], "S2": ["X2"]},
    )
    assert beat_state.current_completed(state) == ["X2"]
    assert beat_state.completed_by_scene(state) == {"S1": ["X1"], "S2": ["X2"]}
    assert state["instances"]["S2:visit:2"]["legacy_source"] == "completed/completed_by_card"
    assert state["instances"]["S2:visit:2"]["receipts"] == []


def test_prerequisites_and_scoped_receipts():
    state = beat_state.new_state("S1", "S1:visit:1")
    try:
        beat_state.commit_beats(
            state, scope=scope(), card=card(), beat_ids=["B2"],
            source_kind="observed_progress", turn=1,
        )
    except beat_state.BeatStateError:
        pass
    else:
        raise AssertionError("B2 cannot complete before B1")

    result = beat_state.commit_beats(
        state, scope=scope(), card=card(), beat_ids=["B1", "B2"],
        source_kind="observed_progress", turn=2,
        source_refs=["actor-output:2"], event_id="progress:2",
    )
    assert result.newly_completed == ("B1", "B2")
    assert beat_state.current_completed(result.state) == ["B1", "B2"]
    assert all(row["receipt"]["producer"] == "BeatState" for row in result.receipts)
    assert {row["receipt"]["scope"]["scene_instance_id"] for row in result.receipts} == {"S1:visit:1"}


def test_revisit_isolated_and_restore_original_instance():
    state = beat_state.new_state("S1", "S1:visit:1")
    state = beat_state.commit_beats(
        state, scope=scope(), card=card(), beat_ids=["B1"],
        source_kind="observed_progress", turn=1,
    ).state
    second_id = beat_state.next_instance_id(state, "S1")
    state = beat_state.begin_scene(state, "S1", second_id)
    assert second_id == "S1:visit:2"
    assert beat_state.current_completed(state) == []
    state = beat_state.restore_instance(state, "S1:visit:1")
    assert beat_state.current_completed(state) == ["B1"]


def test_same_beat_retry_is_idempotent():
    state = beat_state.new_state("S1", "S1:visit:1")
    once = beat_state.commit_beats(
        state, scope=scope(), card=card(), beat_ids=["B1"],
        source_kind="observed_progress", turn=1, event_id="e1",
    )
    twice = beat_state.commit_beats(
        once.state, scope=scope(), card=card(), beat_ids=["B1"],
        source_kind="observed_progress", turn=1, event_id="e1",
    )
    assert twice.newly_completed == ()
    assert len(beat_state.receipts_for_current(twice.state)) == 1


def test_session_completed_is_read_only_projection_and_roundtrips():
    import json
    import tempfile
    from runtime import free_stage_prototype as proto

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        card_path = root / "card.json"
        card_path.write_text(json.dumps(card(), ensure_ascii=False), encoding="utf-8")
        session = proto.FreeStageSession(
            session_id="beat-session",
            card_path=card_path,
            state_dir=root / "states",
            runtime_state_path=root / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=lambda **kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        session._commit_beats(
            ["B1"],
            source_kind="test",
            turn_no=1,
            event_id="test:1",
        )
        assert session.completed == ["B1"]
        leaked = session.completed
        leaked.append("FAKE")
        assert session.completed == ["B1"]
        session.save()

        resumed = proto.FreeStageSession(
            session_id="beat-session",
            card_path=card_path,
            state_dir=root / "states",
            runtime_state_path=root / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=lambda **kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        assert resumed.completed == ["B1"]
        assert resumed._state_payload()["beat_state"]["schema_version"] == beat_state.BEAT_STATE_SCHEMA


def test_free_stage_has_no_direct_completed_writer():
    import inspect
    from runtime import free_stage_prototype as proto

    source = inspect.getsource(proto.FreeStageSession)
    for token in (
        "self.completed =",
        "self.completed.append(",
        "self.completed.extend(",
        "self.completed_by_card =",
        "self.completed_by_card[",
    ):
        assert token not in source, token
    assert "beat_state_store.commit_beats" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
