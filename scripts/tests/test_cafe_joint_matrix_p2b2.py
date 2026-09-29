#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime.world_projection import PENDANT_PROP, RYUYA_BODY_ID


CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
PENDANT_ID = "I.PENDANT_ANCHOR"


class RecordingCaller:
    """Record the real caller payload, then delegate to the project test double."""

    def __init__(self) -> None:
        self.raw: list[str] = []
        self.json_payloads: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        content = str(kwargs.get("user_content") or "")
        self.raw.append(content)
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            self.json_payloads.append(copy.deepcopy(payload))
        return proto.fixed_selftest_actor(**kwargs)

    def actor_requests(self) -> list[dict[str, Any]]:
        return [
            row for row in self.json_payloads
            if isinstance(row.get("actor_context_packet"), dict)
        ]


def _session(tmp: str, sid: str, caller: RecordingCaller, *, autosave: bool = True):
    session = proto.FreeStageSession(
        session_id=sid,
        card_path=CARD,
        state_dir=Path(tmp) / "states",
        runtime_state_path=Path(tmp) / "runtime.db",
        autosave=autosave,
        load_existing=False,
        caller=caller,
    )
    # P2b-2 starts exactly after the explicit offer. We are characterizing
    # disposition/replay behavior, not re-testing RP1-RP3 generation here.
    session.completed = ["RP1", "RP2", "RP3"]
    session.branch_progress = ["prologue_pendant_offered"]
    assert session.body_frames[RYUYA_BODY_ID]["holding"] == PENDANT_ID
    return session


def _snapshot(session: proto.FreeStageSession) -> dict[str, Any]:
    tx = session._world_transaction("ryuya_pendant_disposition")
    action_rows = {
        key: copy.deepcopy(value)
        for key, value in session.player_action_receipts.items()
        if key.startswith("ryuya_pendant_response:")
    }
    pendant_obs = [
        copy.deepcopy(row)
        for row in session.run_observation_ledger
        if row.get("world_transaction_id") == "ryuya_pendant_disposition"
    ]
    debug = session.debug_history[-1] if session.debug_history else {}
    return {
        "rp4": "RP4" in session.completed,
        "world_outcome": tx.get("outcome") if isinstance(tx, dict) else None,
        "world_receipt_id": (
            ((tx.get("receipt") or {}).get("receipt_id"))
            if isinstance(tx, dict) else None
        ),
        "action_values": [
            ((row.get("action") or {}).get("value"))
            for _, row in sorted(action_rows.items())
        ],
        "action_receipt_ids": [
            ((row.get("receipt") or {}).get("receipt_id"))
            for _, row in sorted(action_rows.items())
        ],
        "player_has_pendant": PENDANT_PROP in (session.player_state.get("body_props") or []),
        "ryuya_holding": (session.body_frames.get(RYUYA_BODY_ID) or {}).get("holding"),
        "pendant_observations": pendant_obs,
        "ended": session.ended,
        "exit_reason": str(debug.get("exit_decision") or ""),
    }


def _assert_actor_payload(caller: RecordingCaller, expected_player_text: str) -> None:
    requests = caller.actor_requests()
    assert requests, "real FreeStageSession.step must reach an actor_context_packet caller"
    request = requests[-1]
    assert isinstance(request.get("output_contract"), dict)
    assert isinstance(request.get("instruction"), str)
    packet = request["actor_context_packet"]
    assert packet.get("actor_cons") == "C.ryuya.W1"
    assert isinstance(packet.get("conversation_contract"), dict)
    assert isinstance(packet.get("observable_player"), dict)
    serialized = json.dumps(packet.get("observable_player"), ensure_ascii=False)
    assert expected_player_text in serialized


def test_cafe_disposition_joint_matrix_current_compatibility():
    # deferred→RP4 is a characterization of current compatibility only.
    # It is NOT a canon decision; the ★★★ fact grain remains human-owned.
    cases = [
        {
            "name": "accepted_speech",
            "input": {"speech": "好，我收下", "action": "", "thought": ""},
            "visible": "好，我收下",
            "outcome": "accepted",
            "rp4_compat": True,
            "has_pendant": True,
            "holding": None,
        },
        {
            "name": "accepted_action",
            "input": {"speech": "", "action": "我接过挂坠，拿在手里", "thought": ""},
            "visible": "我接过挂坠，拿在手里",
            "outcome": "accepted",
            "rp4_compat": True,
            "has_pendant": True,
            "holding": None,
        },
        {
            "name": "declined",
            "input": {"speech": "你留着吧，我不收", "action": "", "thought": ""},
            "visible": "你留着吧，我不收",
            "outcome": "declined",
            "rp4_compat": True,
            "has_pendant": False,
            "holding": PENDANT_ID,
        },
        {
            "name": "deferred_pending_human_review",
            "input": {"speech": "先放着，我想想", "action": "", "thought": ""},
            "visible": "先放着，我想想",
            "outcome": "deferred",
            "rp4_compat": True,
            "has_pendant": False,
            "holding": PENDANT_ID,
            "pending_human_review": True,
        },
        {
            "name": "entrust_promise_only",
            "input": {"speech": "我答应，我会照看他们", "action": "", "thought": ""},
            "visible": "我答应，我会照看他们",
            "outcome": None,
            "rp4_compat": False,
            "has_pendant": False,
            "holding": PENDANT_ID,
        },
        {
            "name": "keep_chatting",
            "input": {"speech": "想再见见你总要有个借口吧", "action": "", "thought": ""},
            "visible": "想再见见你总要有个借口吧",
            "outcome": None,
            "rp4_compat": False,
            "has_pendant": False,
            "holding": PENDANT_ID,
        },
    ]

    for case in cases:
        with tempfile.TemporaryDirectory() as tmp:
            caller = RecordingCaller()
            session = _session(tmp, f"matrix-{case['name']}", caller)
            result = session.step(case["input"], debug=True)
            snap = _snapshot(session)

            assert snap["world_outcome"] == case["outcome"], case["name"]
            assert snap["rp4"] is case["rp4_compat"], case["name"]
            assert snap["player_has_pendant"] is case["has_pendant"], case["name"]
            assert snap["ryuya_holding"] == case["holding"], case["name"]
            assert snap["ended"] is False
            assert result["ended"] is False
            _assert_actor_payload(caller, case["visible"])

            if case["outcome"] is None:
                assert snap["action_values"] == []
                assert snap["pendant_observations"] == []
                assert "仍需完成场内契约" in snap["exit_reason"]
            else:
                assert snap["action_values"] == [case["outcome"]]
                assert len(snap["action_receipt_ids"]) == 1
                assert len(snap["pendant_observations"]) == 1
                obs = snap["pendant_observations"][0]
                assert obs["world_receipt_id"] == snap["world_receipt_id"]
                tx = session._world_transaction("ryuya_pendant_disposition")
                assert tx["receipt"]["source_refs"] == snap["action_receipt_ids"]
                assert "等待离场意图" in snap["exit_reason"]


def test_accepted_then_free_chat_stays_open_without_new_transaction():
    with tempfile.TemporaryDirectory() as tmp:
        caller = RecordingCaller()
        session = _session(tmp, "matrix-post-accept-chat", caller)
        session.step({"speech": "好，我收下", "action": "", "thought": ""})
        first_tx = copy.deepcopy(session._world_transaction("ryuya_pendant_disposition"))
        first_obs = copy.deepcopy(session.run_observation_ledger)
        first_actions = copy.deepcopy(session.player_action_receipts)

        out = session.step({"speech": "再聊会儿，急什么", "action": "", "thought": ""}, debug=True)
        assert out["ended"] is False
        assert session.ended is False
        assert session._world_transaction("ryuya_pendant_disposition") == first_tx
        assert session.run_observation_ledger == first_obs
        assert session.player_action_receipts == first_actions
        assert "RP4" in session.completed
        assert "等待离场意图" in session.debug_history[-1]["exit_decision"]


def test_accepted_then_explicit_goodbye_closes_without_rewriting_world_fact():
    with tempfile.TemporaryDirectory() as tmp:
        caller = RecordingCaller()
        session = _session(tmp, "matrix-goodbye", caller)
        session.step({"speech": "好，我收下", "action": "", "thought": ""})
        tx_before = copy.deepcopy(session._world_transaction("ryuya_pendant_disposition"))
        action_before = copy.deepcopy(session.player_action_receipts)

        out = session.step({"speech": "那我先走了，回头见", "action": "", "thought": ""}, debug=True)
        assert out["ended"] is True
        assert session.ended is True
        assert session._world_transaction("ryuya_pendant_disposition") == tx_before
        assert session.player_action_receipts == action_before
        assert session.lifecycle_state == "closed"
        assert "玩家已明确表达离场" in session.debug_history[-1]["exit_decision"]


def test_joint_state_survives_save_load_and_caller_payload_is_not_persisted_as_authority():
    with tempfile.TemporaryDirectory() as tmp:
        caller = RecordingCaller()
        session = _session(tmp, "matrix-save-load", caller, autosave=True)
        session.step({"speech": "好，我收下", "action": "", "thought": ""}, debug=True)
        before = _snapshot(session)
        assert caller.actor_requests()

        resumed_caller = RecordingCaller()
        resumed = proto.FreeStageSession(
            session_id="matrix-save-load",
            card_path=CARD,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=resumed_caller,
        )
        after = _snapshot(resumed)
        assert after["rp4"] == before["rp4"]
        assert after["world_outcome"] == before["world_outcome"]
        assert after["world_receipt_id"] == before["world_receipt_id"]
        assert after["action_values"] == before["action_values"]
        assert after["player_has_pendant"] == before["player_has_pendant"]
        assert after["ryuya_holding"] == before["ryuya_holding"]
        assert after["pendant_observations"] == before["pendant_observations"]
        assert resumed_caller.raw == [], "load must not call the model"
        assert resumed._world_transaction("ryuya_pendant_disposition")["receipt"]["producer"] == "WorldCommit"


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
