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
from runtime import run_lifecycle
from runtime.run_observation_ledger import append_observation
from runtime.world_projection import PENDANT_PROP, RYUYA_BODY_ID



def _seed_completed(session, beat_ids):
    return session._complete_beats(
        list(beat_ids),
        turn_no=0,
        source_kind="test_fixture",
        source_refs=("test-fixture",),
        request_id=f"test-fixture:{session.session_id}:{','.join(beat_ids)}",
    )


CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


class RecordingCaller:
    def __init__(self, *, text: str = "嗯，先说这个。", stage: str = "") -> None:
        self.text = text
        self.stage = stage
        self.calls: list[str] = []
        self.actor_requests: list[dict[str, Any]] = []

    def __call__(self, *, user_content: str = "", **_kwargs: Any) -> str:
        self.calls.append(str(user_content or ""))
        try:
            request = json.loads(user_content)
        except (TypeError, json.JSONDecodeError):
            return "{}"

        if isinstance(request, dict) and isinstance(request.get("actor_context_packet"), dict):
            self.actor_requests.append(copy.deepcopy(request))
            packet = request["actor_context_packet"]
            contract = packet.get("conversation_contract") if isinstance(packet.get("conversation_contract"), dict) else {}
            mode = str(contract.get("participation_mode") or "speak")
            slot = str(contract.get("response_slot") or "")
            stage_only = slot == "stage_only"
            turns = []
            if mode != "pass":
                turns = [
                    {
                        "speaker": "折原龙也",
                        "text": "" if stage_only else self.text,
                        "stage": self.stage if self.stage else ("他抬了抬眼。" if stage_only else ""),
                        "participation_mode": mode,
                    }
                ]
            return json.dumps(
                {
                    "pre_speech": {
                        "notice": "当前玩家输入与桌面物态",
                        "intention": "只接这一拍，不替玩家做决定",
                        "social_move": "primary",
                    },
                    "turns": turns,
                    "mh_progress": [],
                    "director_note": "",
                    "participation_mode": mode,
                },
                ensure_ascii=False,
            )

        # Director/semantic helper calls are allowed to return an empty,
        # deterministic answer. Their code paths already own fallback rules.
        if isinstance(request, dict) and "catalog" in request:
            return json.dumps({"facet_ids": [], "reason": "matrix_fixture"})
        return "{}"

    def last_actor_packet(self) -> dict[str, Any]:
        if not self.actor_requests:
            raise AssertionError("expected a real actor_context_packet caller payload")
        packet = self.actor_requests[-1].get("actor_context_packet")
        assert isinstance(packet, dict)
        return packet


def _offer_ledger(session_id: str) -> list[dict[str, Any]]:
    return append_observation(
        [],
        turn=0,
        scene_id="OPENING_RYUYA_PROLOGUE_001",
        session_id=session_id,
        run_id=1,
        fact_text="龙也明确口头说明挂坠是给玩家的，并把挂坠递到玩家这边；等待玩家回应",
        kind="pendant_offer",
    )


def _offered_session(
    tmp: str,
    *,
    session_id: str,
    caller: RecordingCaller,
    autosave: bool = True,
) -> proto.FreeStageSession:
    session = proto.FreeStageSession(
        session_id=session_id,
        card_path=CARD,
        state_dir=Path(tmp) / "states",
        runtime_state_path=Path(tmp) / "runtime.db",
        autosave=autosave,
        load_existing=False,
        caller=caller,
        intent_caller=None,
        truth_db=None,
    )
    _seed_completed(session, ["RP1", "RP2", "RP3"])
    session.branch_progress = ["prologue_pendant_offered"]
    session.run_observation_ledger = _offer_ledger(session_id)
    session.prior_reflect_by_cons["C.ryuya.W1"] = {
        "thought": "托付已说清；挂坠停在对方面前，等对方自己回应。",
        "band": "pendant",
        "top_concern_id": "await_pendant_response",
        "turn_no": 0,
    }
    session.save()
    return session


def _pendant_observations(session: proto.FreeStageSession) -> list[dict[str, Any]]:
    return [
        row for row in session.run_observation_ledger
        if isinstance(row, dict)
        and str(row.get("world_transaction_id") or "") == "ryuya_pendant_disposition"
    ]


def _assert_reload_equivalent(session: proto.FreeStageSession, *, tmp: str, caller: RecordingCaller) -> None:
    session.save()
    resumed = proto.FreeStageSession(
        session_id=session.session_id,
        card_path=CARD,
        state_dir=Path(tmp) / "states",
        runtime_state_path=Path(tmp) / "runtime.db",
        autosave=True,
        load_existing=True,
        caller=caller,
        intent_caller=None,
        truth_db=None,
    )
    assert resumed.world_transactions == session.world_transactions
    assert resumed.player_action_receipts == session.player_action_receipts
    assert resumed.player_state == session.player_state
    assert resumed.body_frames == session.body_frames
    assert resumed.run_observation_ledger == session.run_observation_ledger
    assert resumed.completed == session.completed
    assert resumed.lifecycle_state == session.lifecycle_state
    assert resumed.ended == session.ended


def test_offer_evidence_matrix_words_action_full():
    words_only = [
        {
            "role": "npc",
            "speaker": "折原龙也",
            "cons": "C.ryuya.W1",
            "text": "这个挂坠给你，收着。",
            "stage": "",
        }
    ]
    action_only = [
        {
            "role": "npc",
            "speaker": "折原龙也",
            "cons": "C.ryuya.W1",
            "text": "",
            "stage": "他把挂坠递过去，停在你面前。",
        }
    ]
    full_offer = [
        {
            "role": "npc",
            "speaker": "折原龙也",
            "cons": "C.ryuya.W1",
            "text": "这个挂坠给你，收着。",
            "stage": "他把挂坠递过去，停在你面前。",
        }
    ]
    assert proto.turns_cover_ryuya_pendant_gift(words_only) is False
    assert proto.turns_cover_ryuya_pendant_gift(action_only) is False
    assert proto.turns_cover_ryuya_pendant_gift(full_offer) is True

    # Stage-only entrust cannot substitute for audible names + warning.
    stage_only_entrust = [
        {
            "role": "npc",
            "speaker": "折原龙也",
            "cons": "C.ryuya.W1",
            "text": "……",
            "stage": "他在纸上写下折原修哉、张尘，又在自己的名字上划了一道。",
        }
    ]
    assert proto.turns_cover_ryuya_entrust(stage_only_entrust) is False


def test_pre_offer_high_beat_joke_and_stage_only_do_not_fake_progress():
    with tempfile.TemporaryDirectory() as tmp:
        joke_caller = RecordingCaller(text="你这借口还挺现成。")
        joke = proto.FreeStageSession(
            session_id="p2b-high-beat-joke",
            card_path=CARD,
            state_dir=Path(tmp) / "joke",
            runtime_state_path=Path(tmp) / "joke.db",
            autosave=False,
            load_existing=False,
            caller=joke_caller,
            intent_caller=None,
            truth_db=None,
        )
        _seed_completed(joke, ["RP1"])
        joke.inputs = [{"speech": "闲聊", "action": "", "thought": ""}] * 20
        joke.step({"speech": "想再见见你总要有个借口吧", "action": "", "thought": ""})
        assert "RP2" not in joke.completed
        assert "RP3" not in joke.completed
        packet = joke_caller.last_actor_packet()
        decide = ((packet.get("cog_loop") or {}).get("decide") or {})
        assert decide.get("top_concern_id") != "entrust"

        serious_caller = RecordingCaller(text="我有点事想跟你说。")
        serious = proto.FreeStageSession(
            session_id="p2b-serious",
            card_path=CARD,
            state_dir=Path(tmp) / "serious",
            runtime_state_path=Path(tmp) / "serious.db",
            autosave=False,
            load_existing=False,
            caller=serious_caller,
            intent_caller=None,
            truth_db=None,
        )
        _seed_completed(serious, ["RP1"])
        serious.step({"speech": "你今天怎么了，有事就说。", "action": "", "thought": ""})
        assert "RP2" in serious.completed
        assert "RP3" not in serious.completed
        serious_packet = serious_caller.last_actor_packet()
        assert ((serious_packet.get("cog_loop") or {}).get("decide") or {}).get("top_concern_id")

        stage_caller = RecordingCaller(
            text="……",
            stage="他在纸上写下折原修哉和张尘，又指了指不要说名字。",
        )
        stage = proto.FreeStageSession(
            session_id="p2b-stage-only-entrust",
            card_path=CARD,
            state_dir=Path(tmp) / "stage",
            runtime_state_path=Path(tmp) / "stage.db",
            autosave=False,
            load_existing=False,
            caller=stage_caller,
            intent_caller=None,
            truth_db=None,
        )
        _seed_completed(stage, ["RP1", "RP2"])
        stage.step({"speech": "你说。", "action": "", "thought": ""})
        assert "RP3" not in stage.completed


def test_post_offer_joint_matrix_and_save_load():
    cases = [
        (
            "ambiguous",
            {"speech": "这东西到底什么意思？", "action": "", "thought": ""},
            None,
        ),
        (
            "entrust_promise",
            {"speech": "我答应，我会照看他们。", "action": "", "thought": ""},
            None,
        ),
        (
            "accepted",
            {"speech": "好，我收下。", "action": "", "thought": ""},
            "accepted",
        ),
        (
            "declined",
            {"speech": "你留着吧，我不收。", "action": "", "thought": ""},
            "declined",
        ),
        (
            "deferred",
            {"speech": "先放着，我想想。", "action": "", "thought": ""},
            "deferred",
        ),
        (
            "ignore_and_chat",
            {"speech": "先别说这个，你咖啡都凉了。", "action": "", "thought": ""},
            None,
        ),
    ]

    for name, player_input, expected_world in cases:
        with tempfile.TemporaryDirectory() as tmp:
            caller = RecordingCaller(text="行，按你的意思。")
            session = _offered_session(
                tmp,
                session_id=f"p2b-matrix-{name}",
                caller=caller,
            )
            result = session.step(player_input)
            assert result["ended"] is False
            tx = session._world_transaction("ryuya_pendant_disposition")
            packet = caller.last_actor_packet()
            decide = ((packet.get("cog_loop") or {}).get("decide") or {})
            assert decide.get("top_concern_id")
            prior = (packet.get("cog_loop") or {}).get("prior_reflect") or {}
            assert "等对方自己回应" in str(prior.get("thought") or "")

            if expected_world is None:
                assert tx is None, name
                assert not any(
                    key.startswith("ryuya_pendant_response:")
                    for key in session.player_action_receipts
                ), name
                assert "RP4" not in session.completed, name
                assert PENDANT_PROP not in session.player_state.get("body_props", []), name
                assert session.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR", name
                assert _pendant_observations(session) == [], name
                assert decide.get("top_concern_id") in {
                    "await_pendant_response",
                    "no_reannounce",
                    "offer_pendant",
                }, (name, decide)
            else:
                assert tx is not None and tx["outcome"] == expected_world, name
                action_keys = [
                    key for key in session.player_action_receipts
                    if key.startswith("ryuya_pendant_response:")
                ]
                assert len(action_keys) == 1, (name, action_keys)
                action = session.player_action_receipts[action_keys[0]]
                assert action["action"]["value"] == expected_world
                assert tx["receipt"]["source_refs"] == [action["receipt"]["receipt_id"]]
                observations = _pendant_observations(session)
                assert len(observations) == 1
                assert observations[0]["world_receipt_id"] == tx["receipt"]["receipt_id"]

                # P2b-2 deliberately does not define whether deferred (or any
                # future disposition policy) is canonical RP4 completion.
                # It only requires the current Beat projection to survive reload
                # and never outrun a missing/failed world transaction.
                if "RP4" in session.completed:
                    assert tx is not None
                if expected_world == "accepted":
                    assert PENDANT_PROP in session.player_state.get("body_props", [])
                    assert session.body_frames[RYUYA_BODY_ID]["holding"] is None
                else:
                    assert PENDANT_PROP not in session.player_state.get("body_props", [])
                    assert session.body_frames[RYUYA_BODY_ID]["holding"] == "I.PENDANT_ANCHOR"

                prompt_frame = ((packet.get("self_state") or {}).get("body_frame_now") or {})
                if expected_world == "accepted":
                    assert prompt_frame.get("holding") is None
                else:
                    assert prompt_frame.get("holding") == "I.PENDANT_ANCHOR"

            _assert_reload_equivalent(session, tmp=tmp, caller=caller)


def test_accept_then_continue_chat_stays_open_and_goodbye_closes():
    with tempfile.TemporaryDirectory() as tmp:
        caller = RecordingCaller(text="随你，反正别弄丢。")
        session = _offered_session(
            tmp,
            session_id="p2b-continue-exit",
            caller=caller,
        )
        session.step({"speech": "好，我收下。", "action": "", "thought": ""})
        assert session._world_transaction("ryuya_pendant_disposition")["outcome"] == "accepted"
        assert session.ended is False

        session.step({"speech": "再聊会儿，雨还没停。", "action": "", "thought": ""})
        assert session.ended is False
        assert session._world_transaction("ryuya_pendant_disposition")["outcome"] == "accepted"

        before_tx = copy.deepcopy(session.world_transactions)
        leave = session.step({"speech": "那我先走了，回头见。", "action": "", "thought": ""})
        assert leave["ended"] is True
        assert session.lifecycle_state == run_lifecycle.CLOSED
        assert session.world_transactions == before_tx
        assert any(proto.END_MARKER in str(row.get("text") or "") for row in session.history)
        _assert_reload_equivalent(session, tmp=tmp, caller=caller)


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
