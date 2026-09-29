#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.causal_protocol import ReceiptConflict, RuntimeScope
from runtime.player_action import assert_same_player_action, player_action_for_fact
from runtime.world_commit import WorldCommitConflict, WorldTransactionProposal, commit_transaction
from runtime import free_stage_prototype as proto


def proposal(outcome="accepted", *, turn=1, scene="S1"):
    return WorldTransactionProposal(
        transaction_id="tx:pendant",
        kind="item_disposition",
        outcome=outcome,
        owner="player",
        scene_id=scene,
        turn=turn,
        worldline="WMAIN",
        run=2,
        public_effect=("pendant_transferred_to_player" if outcome == "accepted" else "pendant_retained_by_ryuya"),
    )


def test_world_transaction_same_fact_is_idempotent_without_moving_origin():
    state, first = commit_transaction({}, proposal(turn=3, scene="S1"))
    assert first.status == "committed"
    state2, retry = commit_transaction(state, proposal(turn=9, scene="FLASHBACK"))
    assert retry.status == "idempotent"
    assert state2 == state
    assert state2["tx:pendant"]["turn"] == 3
    assert state2["tx:pendant"]["scene_id"] == "S1"


def test_world_transaction_conflict_has_zero_partial_effect():
    state, _ = commit_transaction({}, proposal("accepted"))
    before = {key: dict(value) for key, value in state.items()}
    try:
        commit_transaction(state, proposal("declined"))
    except WorldCommitConflict:
        pass
    else:
        raise AssertionError("same transaction id/different outcome must conflict")
    assert state == before
    assert state["tx:pendant"]["outcome"] == "accepted"


def test_player_action_receipt_has_no_private_thought_or_world_custody():
    scope = RuntimeScope(worldline="WMAIN", run=2, ch_anchor=1, session_id="s", scene_instance_id="S1:visit:1")
    receipt = player_action_for_fact(
        scope=scope, request_id="turn:4", turn=4,
        player_input={"speech": "好，我收下", "action": "伸手接住", "thought": "其实我有点犹豫"},
        fact_id="pendant_acceptance_expression",
    )
    data = receipt.to_dict()
    assert data["speech"] == "好，我收下"
    assert data["action"] == "伸手接住"
    assert "thought" not in data
    assert "custody" not in data
    assert "world_effect" not in data
    same = player_action_for_fact(
        scope=scope, request_id="turn:4", turn=4,
        player_input={"speech": "好，我收下", "action": "伸手接住"},
        fact_id="pendant_acceptance_expression",
    )
    assert assert_same_player_action(receipt, same) is receipt
    different = player_action_for_fact(
        scope=scope, request_id="turn:4", turn=4,
        player_input={"speech": "我不要", "action": ""},
        fact_id="pendant_acceptance_expression",
    )
    try:
        assert_same_player_action(receipt, different)
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same player action id/different payload must conflict")


def test_free_stage_transaction_conflict_cannot_rewrite_downstream_state():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2a-conflict",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime_state.db",
            load_existing=False, autosave=False, run_no=2,
            caller=lambda **_: '{"turns":[],"mh_progress":[],"director_note":""}',
        )
        assert session._commit_world_transaction(
            "tx:test", kind="item_disposition", outcome="accepted", owner="player",
            turn_no=1, public_effect="accepted",
        )
        before = {key: dict(value) for key, value in session.world_transactions.items()}
        try:
            session._commit_world_transaction(
                "tx:test", kind="item_disposition", outcome="declined", owner="player",
                turn_no=2, public_effect="declined",
            )
        except WorldCommitConflict:
            pass
        else:
            raise AssertionError("session adapter must surface world conflict")
        assert session.world_transactions == before
        assert session.world_transactions["tx:test"]["outcome"] == "accepted"
        assert len(session.world_commit_receipts) == 1


if __name__ == "__main__":
    test_world_transaction_same_fact_is_idempotent_without_moving_origin()
    test_world_transaction_conflict_has_zero_partial_effect()
    test_player_action_receipt_has_no_private_thought_or_world_custody()
    test_free_stage_transaction_conflict_cannot_rewrite_downstream_state()
    print("PASS test_world_commit_p2a")
