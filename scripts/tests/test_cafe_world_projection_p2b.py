#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime.causal_protocol import ReceiptConflict, RuntimeScope
from runtime.world_commit import commit_world_fact
from runtime.world_projection import PENDANT_PROP, RYUYA_BODY_ID, project_world_transaction


def _scope():
    return RuntimeScope(
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="p2b",
        scene_instance_id="OPENING_RYUYA_PROLOGUE_001:visit:1",
    )


def _transaction(outcome: str):
    ledger = {}
    result = commit_world_fact(
        ledger,
        scope=_scope(),
        request_id="req:pendant",
        turn_id="turn:3",
        transaction_id="ryuya_pendant_disposition",
        kind="item_disposition",
        outcome=outcome,
        owner="player",
        scene_id="OPENING_RYUYA_PROLOGUE_001",
        turn=3,
        public_effect=(
            "pendant_transferred_to_player"
            if outcome == "accepted"
            else "pendant_retained_by_ryuya"
        ),
        source_refs=["player:response:3"],
    )
    return result.record


def _frames():
    return {
        RYUYA_BODY_ID: {
            "holding": "I.PENDANT_ANCHOR",
            "hands": "holding:I.PENDANT_ANCHOR",
            "note": "",
            "last_action_type": "",
        }
    }


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_projection_is_copy_safe_and_accepted_is_consistent():
    state = {"body_props": ["钥匙"]}
    frames = _frames()
    observations = []
    before = (copy.deepcopy(state), copy.deepcopy(frames), copy.deepcopy(observations))
    out = project_world_transaction(
        _transaction("accepted"),
        player_state=state,
        body_frames=frames,
        observation_ledger=observations,
        session_id="p2b",
    )
    assert (state, frames, observations) == before
    assert PENDANT_PROP in out.player_state["body_props"]
    assert out.body_frames[RYUYA_BODY_ID]["holding"] is None
    assert out.body_frames[RYUYA_BODY_ID]["hands"] == "free"
    assert len(out.observation_ledger) == 1
    row = out.observation_ledger[0]
    assert row["fact_text"] == "挂坠accepted"
    assert row["world_transaction_id"] == "ryuya_pendant_disposition"
    assert str(row["world_receipt_id"]).startswith("world:")


def test_declined_and_deferred_do_not_claim_custody():
    for disposition in ("declined", "deferred"):
        out = project_world_transaction(
            _transaction(disposition),
            player_state={"body_props": []},
            body_frames=_frames(),
            observation_ledger=[],
            session_id="p2b",
        )
        assert PENDANT_PROP not in out.player_state.get("body_props", [])
        assert out.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"
        assert out.observation_ledger[0]["fact_text"] == f"挂坠{disposition}"


def test_projection_retry_is_idempotent():
    tx = _transaction("accepted")
    once = project_world_transaction(
        tx,
        player_state={"body_props": []},
        body_frames=_frames(),
        observation_ledger=[],
        session_id="p2b",
    )
    twice = project_world_transaction(
        tx,
        player_state=once.player_state,
        body_frames=once.body_frames,
        observation_ledger=once.observation_ledger,
        session_id="p2b",
    )
    assert twice.player_state["body_props"].count(PENDANT_PROP) == 1
    assert twice.body_frames == once.body_frames
    assert twice.observation_ledger == once.observation_ledger


def test_stage_only_pendant_motion_cannot_clear_holding():
    card = {
        "scene_id": "OPENING_RYUYA_PROLOGUE_001",
        "persona_cards": {"C.ryuya.W1": {"name": "折原龙也"}},
    }
    frames = _frames()
    turns = [{
        "speaker": "折原龙也",
        "cons": "C.ryuya.W1",
        "role": "npc",
        "text": "这个给你。",
        "stage": "他把挂坠递过去，停在你面前。",
    }]
    issues = proto.settle_body_frames_from_npc_turns(frames, card, turns)
    assert issues == []
    assert frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"
    assert frames[RYUYA_BODY_ID]["last_visible_stage"]


def test_non_pendant_body_frame_rules_still_work():
    card = {
        "scene_id": "OTHER",
        "persona_cards": {"C.akito.WMAIN": {"name": "川口秋人"}},
    }
    frames = {
        "B.akito.WMAIN": {
            "holding": "I.CAMERA_DSLR",
            "hands": "holding:I.CAMERA_DSLR",
            "last_visible_stage": "",
            "last_action_type": "",
        }
    }
    turns = [{
        "speaker": "川口秋人",
        "cons": "C.akito.WMAIN",
        "role": "npc",
        "text": "好了。",
        "stage": "他把单反放下。",
    }]
    assert proto.settle_body_frames_from_npc_turns(frames, card, turns) == []
    assert frames["B.akito.WMAIN"]["holding"] is None


def test_session_finalize_projects_only_after_world_commit_and_conflict_is_atomic():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2b-session",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        assert session.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"
        assert session._finalize_prologue_pendant("accepted", turn_no=3) is True
        tx = session._world_transaction("ryuya_pendant_disposition")
        assert tx["receipt"]["producer"] == "WorldCommit"
        assert PENDANT_PROP in session.player_state["body_props"]
        assert session.body_frames[RYUYA_BODY_ID]["holding"] is None
        assert session.run_observation_ledger[-1]["world_receipt_id"] == tx["receipt"]["receipt_id"]

        before = (
            copy.deepcopy(session.player_state),
            copy.deepcopy(session.body_frames),
            copy.deepcopy(session.run_observation_ledger),
        )
        try:
            session._finalize_prologue_pendant("declined", turn_no=4)
        except ReceiptConflict:
            pass
        else:
            raise AssertionError("terminal disposition conflict must fail")
        assert (
            session.player_state,
            session.body_frames,
            session.run_observation_ledger,
        ) == before


def test_explicit_player_response_sources_world_commit_without_smuggling_custody():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2b-source",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        assert session._commit_player_pendant_response("accepted", turn_no=7) is True
        action = session.player_action_receipts["ryuya_pendant_response:7"]
        action_payload = action["action"]
        assert action_payload["value"] == "accepted"
        action_blob = json.dumps(action_payload, ensure_ascii=False)
        assert "custody" not in action_blob
        assert "holding" not in action_blob
        tx = session._world_transaction("ryuya_pendant_disposition")
        assert tx["receipt"]["source_refs"] == [action["receipt"]["receipt_id"]]
        assert tx["request_id"] == "world-from:ryuya_pendant_response:7"


def test_step_does_not_complete_rp4_before_conflicting_world_commit():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2b-rp4-order",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.completed = ["RP1", "RP2", "RP3"]
        session.branch_progress = ["prologue_pendant_offered"]
        session._finalize_prologue_pendant("accepted", turn_no=1)
        # Existing terminal world fact conflicts with a later decline. The
        # player's decline remains a valid PlayerAction, but RP4 must not jump
        # ahead of a failed world settlement.
        try:
            session.step({"speech": "不收", "action": "", "thought": ""})
        except ReceiptConflict:
            pass
        else:
            raise AssertionError("conflicting terminal world fact must surface as a conflict")
        assert "RP4" not in session.completed
        assert "ryuya_pendant_response:1" in session.player_action_receipts
        action = session.player_action_receipts["ryuya_pendant_response:1"]
        assert action["action"]["value"] == "declined"
        assert session._world_transaction("ryuya_pendant_disposition")["outcome"] == "accepted"


def test_finalize_projection_survives_save_load():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2b-save",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._finalize_prologue_pendant("accepted", turn_no=2)
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2b-save",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        tx = resumed._world_transaction("ryuya_pendant_disposition")
        assert PENDANT_PROP in resumed.player_state["body_props"]
        assert resumed.body_frames[RYUYA_BODY_ID]["holding"] is None
        assert resumed.run_observation_ledger[-1]["world_receipt_id"] == tx["receipt"]["receipt_id"]


def test_opening_synopsis_seed_uses_world_projection_without_faking_player_action():
    card = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2b-opening",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
            opening_id="aline_tiananmen",
        )
        session._ensure_opening_synopsis_and_pendant()
        tx = session._world_transaction("ryuya_pendant_disposition")
        assert tx["outcome"] == "accepted"
        assert PENDANT_PROP in session.player_state["body_props"]
        assert session.player_action_receipts == {}


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
