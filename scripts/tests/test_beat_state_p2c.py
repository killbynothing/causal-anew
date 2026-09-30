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


def test_legacy_migration_keeps_unknown_ids_unresolved_without_inventing_actions():
    state = beat_state.migrate_legacy(
        scene_id="S1",
        scene_instance_id="S1:visit:1",
        required_ids=["B1", "B2"],
        completed=["B1", "UNKNOWN"],
        completed_by_card={"OLD": ["O1"]},
    )
    assert beat_state.active_completed(state) == ["B1"]
    active = beat_state.active_scene(state)
    assert active["legacy_unresolved"] == ["UNKNOWN"]
    evidence = list(active["evidence"].values())
    assert evidence and evidence[0]["source_kind"] == "legacy_session_v1"
    assert all("player" not in ref for row in evidence for ref in row["source_refs"])
    assert beat_state.completed_by_scene(state)["OLD"] == ["O1"]


def test_satisfaction_is_evidence_scoped_idempotent_and_does_not_create_predecessors():
    state = beat_state.new_state(
        scene_id="S1",
        scene_instance_id="S1:visit:1",
        required_ids=["B1", "B2", "B3"],
    )
    eid = beat_state.evidence_id_for(
        scene_instance_id="S1:visit:1",
        source_kind="observed_progress",
        turn=3,
        beat_ids=["B3"],
        source_refs=["actor-output:turn:3"],
    )
    state, newly = beat_state.satisfy_beats(
        state,
        beat_ids=["B3"],
        evidence_id=eid,
        source_kind="observed_progress",
        source_refs=["actor-output:turn:3"],
        turn=3,
    )
    assert newly == ["B3"]
    assert beat_state.active_completed(state) == ["B3"]
    retry, newly_retry = beat_state.satisfy_beats(
        state,
        beat_ids=["B3"],
        evidence_id=eid,
        source_kind="observed_progress",
        source_refs=["actor-output:turn:3"],
        turn=3,
    )
    assert retry == state and newly_retry == []


def test_unknown_beat_and_evidence_conflict_are_hard_errors():
    state = beat_state.new_state(
        scene_id="S1",
        scene_instance_id="S1:visit:1",
        required_ids=["B1"],
    )
    try:
        beat_state.satisfy_beats(
            state,
            beat_ids=["MISSING"],
            evidence_id="e1",
            source_kind="observed_progress",
            source_refs=["actor-output:turn:1"],
            turn=1,
        )
    except beat_state.BeatStateError:
        pass
    else:
        raise AssertionError("undeclared beat must not become completed")

    state, _ = beat_state.satisfy_beats(
        state,
        beat_ids=["B1"],
        evidence_id="e1",
        source_kind="observed_progress",
        source_refs=["actor-output:turn:1"],
        turn=1,
    )
    try:
        beat_state.satisfy_beats(
            state,
            beat_ids=["B1"],
            evidence_id="e1",
            source_kind="canon_segment",
            source_refs=["canon:different"],
            turn=2,
        )
    except beat_state.BeatEvidenceConflict:
        pass
    else:
        raise AssertionError("same evidence id with different payload must conflict")


def test_revisit_uses_new_scene_instance_and_new_evidence_identity():
    state = beat_state.new_state(
        scene_id="S1", scene_instance_id="S1:visit:1", required_ids=["B1"],
    )
    eid1 = beat_state.evidence_id_for(
        scene_instance_id="S1:visit:1", source_kind="observed_progress",
        turn=1, beat_ids=["B1"], source_refs=["x"],
    )
    state, _ = beat_state.satisfy_beats(
        state, beat_ids=["B1"], evidence_id=eid1, source_kind="observed_progress",
        source_refs=["x"], turn=1,
    )
    state = beat_state.activate_scene(
        state,
        scene_id="S1",
        scene_instance_id="S1:visit:2",
        required_ids=["B1"],
    )
    eid2 = beat_state.evidence_id_for(
        scene_instance_id="S1:visit:2", source_kind="observed_progress",
        turn=1, beat_ids=["B1"], source_refs=["x"],
    )
    assert eid1 != eid2
    assert beat_state.active_completed(state) == []


def test_session_uses_beat_reducer_for_business_writes_and_save_load():
    source = inspect.getsource(proto.FreeStageSession)
    assert "self.completed.append(" not in source
    assert "self.completed.extend(" not in source
    assert "self.completed.remove(" not in source
    assert "beat_state.satisfy_beats" in source
    assert "beat_state.activate_scene" in source

    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-beat",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=lambda **_kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        newly = session._satisfy_beats(
            ["RP1"],
            turn_no=1,
            source_kind="scene_presence",
            source_refs=["history:player-turn:1"],
        )
        assert newly == ["RP1"]
        assert session.completed == ["RP1"]
        assert session.completed_by_card["OPENING_RYUYA_PROLOGUE_001"] == ["RP1"]
        session.save()
        payload = json.loads((state_dir / "p2c-beat.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == "free_stage.session.v2"
        assert payload["beat_state"]["schema_version"] == beat_state.BEAT_STATE_SCHEMA

        resumed = proto.FreeStageSession(
            session_id="p2c-beat",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=lambda **_kwargs: json.dumps({"turns": [], "mh_progress": []}),
        )
        assert resumed.completed == ["RP1"]
        assert resumed.beat_state == session.beat_state


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
