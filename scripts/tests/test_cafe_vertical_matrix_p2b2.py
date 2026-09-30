#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import exit_policy
from runtime import free_stage_prototype as proto
from runtime.world_projection import PENDANT_PROP, RYUYA_BODY_ID


CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


class CaptureCaller:
    def __init__(self) -> None:
        self.raw_payloads: list[str] = []

    def __call__(self, *, user_content: str = "", **_kwargs) -> str:
        self.raw_payloads.append(str(user_content or ""))
        # One permissive deterministic envelope serves all zero-LLM call sites.
        return json.dumps(
            {
                "pre_speech": {
                    "notice": "眼前事实",
                    "intention": "自然承接",
                    "social_move": "continuer",
                },
                "turns": [
                    {
                        "speaker": "折原龙也",
                        "text": "嗯。",
                        "stage": "",
                        "participation_mode": "speak",
                    }
                ],
                "mh_progress": [],
                "director_note": "",
                "facet_ids": [],
                "reason": "fixture",
                "ambient": [],
                "matched_opportunity_id": None,
                "confidence": 0.0,
            },
            ensure_ascii=False,
        )

    def actor_payloads(self) -> list[dict]:
        out: list[dict] = []
        for raw in self.raw_payloads:
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("actor_context_packet"), dict):
                out.append(parsed)
        return out


def _snapshot(session: proto.FreeStageSession) -> dict:
    return {
        "completed": list(session.completed),
        "branch_progress": list(session.branch_progress),
        "player_action_receipts": copy.deepcopy(session.player_action_receipts),
        "world_transactions": copy.deepcopy(session.world_transactions),
        "player_state": copy.deepcopy(session.player_state),
        "body_frames": copy.deepcopy(session.body_frames),
        "run_observation_ledger": copy.deepcopy(session.run_observation_ledger),
        "ended": bool(session.ended),
    }


def _run_case(
    *,
    name: str,
    player_input,
    disposition: str | None,
    compat_rp4: bool,
) -> None:
    caller = CaptureCaller()
    captured_decisions = []
    original_decide = exit_policy.decide_exit

    def capture_decision(request):
        decision = original_decide(request)
        captured_decisions.append(decision)
        return decision

    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        runtime_state = Path(tmp) / "runtime.db"
        session = proto.FreeStageSession(
            session_id=f"p2b2-{name}",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=runtime_state,
            autosave=True,
            load_existing=False,
            caller=caller,
        )
        session._satisfy_beats(
            ["RP1", "RP2", "RP3"],
            turn_no=0,
            source_kind="test_fixture",
            source_refs=(f"fixture:p2b2:{name}",),
        )
        session.branch_progress = ["prologue_pendant_offered"]
        assert session.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"
        session.save()

        with patch.object(exit_policy, "decide_exit", side_effect=capture_decision):
            result = session.step(player_input, debug=True)

        assert captured_decisions, f"{name}: ExitPolicy was not consulted"
        decision = captured_decisions[-1]
        assert decision.action == "continue", (name, decision.to_dict())
        assert result.get("transition") is None
        assert result["ended"] is False
        assert ("RP4" in session.completed) is compat_rp4

        actor_payloads = caller.actor_payloads()
        assert actor_payloads, f"{name}: no real actor caller payload captured"
        actor_packet = actor_payloads[-1]["actor_context_packet"]
        caller_holding = (actor_packet.get("body_frame_now") or {}).get("holding")

        tx = session._world_transaction("ryuya_pendant_disposition")
        action = session.player_action_receipts.get("ryuya_pendant_response:1")

        if disposition is None:
            assert tx is None, name
            assert action is None, name
            assert PENDANT_PROP not in session.player_state.get("body_props", [])
            assert session.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"
            assert caller_holding == "I.PENDANT_ANCHOR"
            assert not any(
                str(row.get("world_transaction_id") or "") == "ryuya_pendant_disposition"
                for row in session.run_observation_ledger
                if isinstance(row, dict)
            )
        else:
            assert action is not None, name
            assert action["action"]["value"] == disposition
            assert action["action"]["action_kind"] == "item_disposition_response"
            assert tx is not None and tx["outcome"] == disposition
            assert tx["receipt"]["producer"] == "WorldCommit"
            assert tx["receipt"]["source_refs"] == [action["receipt"]["receipt_id"]]

            observations = [
                row
                for row in session.run_observation_ledger
                if isinstance(row, dict)
                and row.get("world_transaction_id") == "ryuya_pendant_disposition"
            ]
            assert len(observations) == 1, (name, observations)
            assert observations[0]["world_receipt_id"] == tx["receipt"]["receipt_id"]

            if disposition == "accepted":
                assert PENDANT_PROP in session.player_state.get("body_props", [])
                assert session.body_frames[RYUYA_BODY_ID]["holding"] is None
                assert caller_holding is None
            else:
                assert PENDANT_PROP not in session.player_state.get("body_props", [])
                assert session.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"
                assert caller_holding == "I.PENDANT_ANCHOR"

        before_reload = _snapshot(session)
        resumed = proto.FreeStageSession(
            session_id=f"p2b2-{name}",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=runtime_state,
            autosave=True,
            load_existing=True,
            caller=CaptureCaller(),
        )
        assert _snapshot(resumed) == before_reload, f"{name}: save→load drift"


def test_fixed_cafe_matrix_end_to_end():
    # RP4 booleans here characterize the current compatibility projection only.
    # deferred=True is explicitly NOT a canon/★★★ decision.
    cases = [
        {
            "name": "accept_speech",
            "player_input": {"speech": "好，我收下", "action": "", "thought": ""},
            "disposition": "accepted",
            "compat_rp4": True,
        },
        {
            "name": "decline_speech",
            "player_input": {"speech": "你留着吧，我不收", "action": "", "thought": ""},
            "disposition": "declined",
            "compat_rp4": True,
        },
        {
            "name": "defer_speech",
            "player_input": {"speech": "先放着，我想想", "action": "", "thought": ""},
            "disposition": "deferred",
            "compat_rp4": True,
        },
        {
            "name": "entrust_promise_only",
            "player_input": {"speech": "我答应，我会照看他们", "action": "", "thought": ""},
            "disposition": None,
            "compat_rp4": False,
        },
        {
            "name": "continue_chat",
            "player_input": {"speech": "想再见见你总要有个借口吧", "action": "", "thought": ""},
            "disposition": None,
            "compat_rp4": False,
        },
    ]
    for case in cases:
        _run_case(**case)


def test_action_channel_acceptance_is_same_authority_chain():
    _run_case(
        name="accept_action",
        player_input={"speech": "", "action": "我接过挂坠，拿在手里", "thought": ""},
        disposition="accepted",
        compat_rp4=True,
    )


if __name__ == "__main__":
    test_fixed_cafe_matrix_end_to_end()
    print("PASS test_fixed_cafe_matrix_end_to_end")
    test_action_channel_acceptance_is_same_authority_chain()
    print("PASS test_action_channel_acceptance_is_same_authority_chain")
