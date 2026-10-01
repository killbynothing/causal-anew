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

from runtime.beat_state import BeatState, scene_instance_id
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_beat_state_requires_evidence_and_does_not_invent_predecessors():
    state = BeatState.new("S1")
    try:
        state.complete("B2", source_kind="", source_ref="", turn=1)
    except ValueError:
        pass
    else:
        raise AssertionError("beat completion without evidence must fail")
    assert state.complete("B2", source_kind="observed_progress", source_ref="turn:1", turn=1)
    assert state.completed() == ["B2"]
    assert not state.complete("B2", source_kind="other", source_ref="turn:2", turn=2)
    assert state.completed() == ["B2"]


def test_revisit_same_scene_gets_new_receipt_scope():
    state = BeatState.new("S1")
    state.complete("B1", source_kind="observed_progress", source_ref="turn:1", turn=1)
    first = state.receipts()[0]
    state.enter_scene(
        scene_id="S2",
        scene_instance_id=scene_instance_id("S2", 1),
        source_kind="scene_enter",
        source_ref="S1->S2",
        turn=2,
    )
    state.enter_scene(
        scene_id="S1",
        scene_instance_id=scene_instance_id("S1", 2),
        restored_beats=("B1",),
        source_kind="flashback_restore",
        source_ref="S2->S1",
        turn=3,
    )
    second = state.receipts()[0]
    assert first["scene_instance_id"] == "S1:visit:1"
    assert second["scene_instance_id"] == "S1:visit:2"
    assert first["receipt_id"] != second["receipt_id"]


def test_legacy_completed_migrates_without_player_action_fabrication():
    state = BeatState.from_legacy(
        current_scene_id="S2",
        current_completed=["C2"],
        completed_by_card={"S1": ["C1"]},
        card_history=["S1", "S2"],
    )
    assert state.completed() == ["C2"]
    assert state.completed_by_card() == {"S1": ["C1"], "S2": ["C2"]}
    blob = json.dumps(state.to_dict(), ensure_ascii=False)
    assert "legacy_snapshot" in blob
    assert "PlayerAction" not in blob
    assert "player_action" not in blob


def test_free_stage_completed_is_projection_and_production_has_no_raw_writer():
    source = inspect.getsource(proto.FreeStageSession)
    assert "self.completed.append(" not in source
    assert "self.completed.extend(" not in source
    assert "self.completed =" not in source
    assert "self.completed_by_card[" not in source
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-beat",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        assert session.completed == []
        session._complete_beat("RP1", source_kind="observed_progress", source_ref="turn:1", turn_no=1)
        assert session.completed == ["RP1"]
        assert session.completed_by_card["OPENING_RYUYA_PROLOGUE_001"] == ["RP1"]


def test_beat_state_survives_save_load_with_same_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
        session = proto.FreeStageSession(
            session_id="p2c-beat-save",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._complete_beat("RP1", source_kind="observed_progress", source_ref="turn:1", turn_no=1)
        before = session.beat_state.receipts()[0]
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-beat-save",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["RP1"]
        assert resumed.beat_state.receipts()[0] == before


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
