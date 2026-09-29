#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import actor_cog_loop as cogloop
from runtime import free_stage_prototype as proto
from runtime.world_projection import PENDANT_PROP, RYUYA_BODY_ID

CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


class MatrixCaller:
    def __init__(self, actor_rows):
        self.actor_rows = list(actor_rows)
        self.actor_requests = []
        self.director_requests = []

    def __call__(self, *, user_content="", **_kwargs):
        try:
            request = json.loads(user_content)
        except (TypeError, json.JSONDecodeError):
            return json.dumps({}, ensure_ascii=False)
        if isinstance(request, dict) and isinstance(request.get("actor_context_packet"), dict):
            self.actor_requests.append(request)
            packet = request["actor_context_packet"]
            contract = packet.get("conversation_contract") or {}
            mode = str(contract.get("participation_mode") or "speak")
            row = self.actor_rows.pop(0) if self.actor_rows else {"text": "嗯。", "stage": ""}
            return json.dumps(
                {
                    "pre_speech": {
                        "notice": "承接眼前可见事实",
                        "intention": "按当前 concern 自然回应",
                        "social_move": "primary",
                    },
                    "turns": [
                        {
                            "speaker": "折原龙也",
                            "text": str(row.get("text") or ""),
                            "stage": str(row.get("stage") or ""),
                            "participation_mode": mode,
                        }
                    ],
                    "mh_progress": [],
                    "director_note": "",
                    "participation_mode": mode,
                },
                ensure_ascii=False,
            )
        if isinstance(request, dict) and isinstance(request.get("director_harness"), dict):
            self.director_requests.append(request)
            return json.dumps(
                {"director_note": "", "mh_progress": []},
                ensure_ascii=False,
            )
        return json.dumps({}, ensure_ascii=False)


def _new_session(
    tmp: str,
    name: str,
    caller: MatrixCaller,
    *,
    completed=(),
    branch=(),
    old_inputs: int = 0,
    prior_reflect: str = "",
):
    state_dir = Path(tmp) / name
    session = proto.FreeStageSession(
        session_id=name,
        card_path=CARD,
        state_dir=state_dir,
        runtime_state_path=Path(tmp) / f"{name}.runtime.db",
        config={"actor_context_isolation": True},
        caller=caller,
        autosave=True,
        load_existing=False,
    )
    session.completed = [str(x) for x in completed]
    session.branch_progress = [str(x) for x in branch]
    if old_inputs:
        session.inputs = [f"old-{i}" for i in range(old_inputs)]
    if prior_reflect:
        session.prior_reflect_by_cons["C.ryuya.W1"] = {
            "turn_no": max(0, old_inputs),
            "thought": prior_reflect,
            "band": "pendant",
            "top_concern_id": "hand_pendant",
        }
    session.save()
    return session, state_dir


def _state(session):
    tx = session._world_transaction("ryuya_pendant_disposition")
    actions = {
        key: str(((row.get("action") or {}).get("value") or ""))
        for key, row in session.player_action_receipts.items()
        if key.startswith("ryuya_pendant_response:")
    }
    pendant_obs = [
        {
            "kind": str(row.get("kind") or ""),
            "fact": str(row.get("fact_text") or ""),
            "world_receipt_id": str(row.get("world_receipt_id") or ""),
        }
        for row in session.run_observation_ledger
        if str(row.get("kind") or "") in {"pendant", "pendant_offer"}
    ]
    return {
        "completed": tuple(session.completed),
        "prologue_markers": tuple(
            x for x in session.branch_progress if str(x).startswith("prologue_")
        ),
        "transaction": None if not tx else {
            "outcome": str(tx.get("outcome") or ""),
            "public_effect": str(tx.get("public_effect") or ""),
            "source_refs": tuple((tx.get("receipt") or {}).get("source_refs") or []),
        },
        "player_actions": tuple(sorted(actions.items())),
        "player_has_pendant": PENDANT_PROP in (session.player_state.get("body_props") or []),
        "ryuya_holding": (session.body_frames.get(RYUYA_BODY_ID) or {}).get("holding"),
        "pendant_observations": tuple(
            (row["kind"], row["fact"], row["world_receipt_id"]) for row in pendant_obs
        ),
        "lifecycle": str(session.lifecycle_state),
        "ended": bool(session.ended),
    }


def _run_step(session, player_input):
    decisions = []
    original = proto.exit_policy.decide_exit

    def wrapped(request):
        decision = original(request)
        decisions.append(decision.to_dict())
        return decision

    proto.exit_policy.decide_exit = wrapped
    try:
        result = session.step(player_input, debug=True)
    finally:
        proto.exit_policy.decide_exit = original
    return result, decisions


def _assert_actor_request(caller: MatrixCaller, player_input):
    assert caller.actor_requests, "production step did not reach isolated actor caller"
    request = caller.actor_requests[-1]
    packet = request["actor_context_packet"]
    assert packet.get("actor_cons") == "C.ryuya.W1"
    assert "constraint_card" not in packet
    assert isinstance(packet.get("conversation_contract"), dict)
    assert isinstance(packet.get("cog_loop"), dict)
    decide = (packet.get("cog_loop") or {}).get("decide") or {}
    assert decide.get("top_concern")
    observable = packet.get("observable_player") or {}
    if isinstance(player_input, dict):
        assert str(observable.get("speech") or "") == str(player_input.get("speech") or "")
        assert str(observable.get("action") or "") == str(player_input.get("action") or "")
        # Non-empty thought must not be exposed as public speech/action.
        thought = str(player_input.get("thought") or "")
        if thought:
            assert thought not in json.dumps(observable, ensure_ascii=False)
    return packet


def _assert_reload_equal(session, state_dir, caller, tmp):
    before = _state(session)
    session.save()
    resumed = proto.FreeStageSession(
        session_id=session.session_id,
        card_path=CARD,
        state_dir=state_dir,
        runtime_state_path=Path(tmp) / f"{session.session_id}.runtime.db",
        config={"actor_context_isolation": True},
        caller=caller,
        autosave=True,
        load_existing=True,
    )
    assert _state(resumed) == before
    return resumed


def test_cafe_fixed_input_joint_matrix():
    cases = [
        {
            "name": "pure_joke",
            "completed": (),
            "branch": (),
            "input": {"speech": "你今天咖啡喝得也太慢了", "action": "", "thought": ""},
            "actor": {"text": "雨还没停，你倒先管起我喝咖啡了。", "stage": ""},
        },
        {
            "name": "high_beats",
            "completed": ("RP1",),
            "branch": (),
            "old_inputs": 8,
            "input": {"speech": "哈哈，窗外还是这个鬼天气", "action": "", "thought": ""},
            "actor": {"text": "天气是挺烦，咖啡还行。", "stage": ""},
        },
        {
            "name": "serious_topic",
            "completed": ("RP1",),
            "branch": (),
            "input": {"speech": "你今天是不是有事", "action": "", "thought": ""},
            "actor": {"text": "我有件事想跟你说。", "stage": ""},
        },
        {
            "name": "stage_only_entrust",
            "completed": ("RP1", "RP2"),
            "branch": (),
            "input": {"speech": "你说", "action": "", "thought": ""},
            "actor": {
                "text": "嗯。",
                "stage": "他示意以后照顾张尘和折原修哉，也别说他的名字，会有危险，会死人。",
            },
        },
        {
            "name": "words_only_offer",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": (),
            "input": {"speech": "我听着", "action": "", "thought": ""},
            "actor": {"text": "这个挂坠给你，算临别礼物。收不收你自己决定。", "stage": ""},
        },
        {
            "name": "action_only_offer",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": (),
            "input": {"speech": "嗯", "action": "", "thought": ""},
            "actor": {"text": "嗯。", "stage": "他把古铜色挂坠推到你面前，手停在那里。"},
        },
        {
            "name": "complete_offer",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": (),
            "input": {"speech": "还有什么", "action": "", "thought": ""},
            "actor": {
                "text": "这个挂坠给你，算临别礼物。收不收你自己决定。",
                "stage": "他把古铜色挂坠推到你面前，手停在那里。",
            },
        },
        {
            "name": "ambiguous_response",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": ("prologue_pendant_offered",),
            "input": {"speech": "我答应照顾他们", "action": "", "thought": ""},
            "actor": {"text": "知道了。", "stage": ""},
        },
        {
            "name": "accept",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": ("prologue_pendant_offered",),
            "input": {"speech": "好，我收下", "action": "", "thought": ""},
            "actor": {"text": "嗯。", "stage": ""},
        },
        {
            "name": "decline",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": ("prologue_pendant_offered",),
            "input": {"speech": "你留着吧，我不收", "action": "", "thought": ""},
            "actor": {"text": "行。", "stage": ""},
        },
        {
            "name": "defer",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": ("prologue_pendant_offered",),
            "input": {"speech": "先放着，我想想", "action": "", "thought": ""},
            "actor": {"text": "好。", "stage": ""},
        },
        {
            "name": "ignore_and_chat",
            "completed": ("RP1", "RP2", "RP3"),
            "branch": ("prologue_pendant_offered",),
            "input": {"speech": "你还欠我一杯咖啡呢", "action": "", "thought": ""},
            "actor": {"text": "这都记着？", "stage": ""},
        },
    ]

    with tempfile.TemporaryDirectory() as tmp:
        snapshots = {}
        packets = {}
        exits = {}
        for case in cases:
            caller = MatrixCaller([case["actor"]])
            session, state_dir = _new_session(
                tmp,
                case["name"],
                caller,
                completed=case.get("completed", ()),
                branch=case.get("branch", ()),
                old_inputs=int(case.get("old_inputs", 0)),
                prior_reflect=(
                    "托付说清了；挂坠若要赠与，只能明确递出后等对方回应，不能替对方收下。"
                    if case["name"] in {"high_beats", "ambiguous_response"}
                    else ""
                ),
            )
            _result, decisions = _run_step(session, case["input"])
            packets[case["name"]] = _assert_actor_request(caller, case["input"])
            snapshots[case["name"]] = _state(session)
            exits[case["name"]] = decisions[-1] if decisions else None
            _assert_reload_equal(session, state_dir, caller, tmp)

        assert "RP2" not in snapshots["high_beats"]["completed"]
        assert "RP2" in snapshots["serious_topic"]["completed"]
        assert "RP3" not in snapshots["stage_only_entrust"]["completed"]
        assert "prologue_pendant_offered" not in snapshots["words_only_offer"]["prologue_markers"]
        assert "prologue_pendant_offered" not in snapshots["action_only_offer"]["prologue_markers"]
        assert "prologue_pendant_offered" in snapshots["complete_offer"]["prologue_markers"]
        assert snapshots["complete_offer"]["transaction"] is None
        assert "RP4" not in snapshots["complete_offer"]["completed"]

        ambiguous = snapshots["ambiguous_response"]
        assert ambiguous["transaction"] is None
        assert ambiguous["player_actions"] == ()
        assert "RP4" not in ambiguous["completed"]

        accepted = snapshots["accept"]
        assert accepted["transaction"]["outcome"] == "accepted"
        assert accepted["player_has_pendant"] is True
        assert accepted["ryuya_holding"] is None
        assert accepted["player_actions"] and accepted["player_actions"][0][1] == "accepted"
        assert accepted["pendant_observations"][-1][2].startswith("world:")
        assert exits["accept"]["action"] == "continue"

        for name, expected in (("decline", "declined"), ("defer", "deferred")):
            row = snapshots[name]
            assert row["transaction"]["outcome"] == expected
            assert row["transaction"]["public_effect"] == "pendant_not_in_player_custody"
            assert row["player_has_pendant"] is False
            assert row["player_actions"] and row["player_actions"][0][1] == expected
            assert row["pendant_observations"][-1][2].startswith("world:")
            assert exits[name]["action"] == "continue"
            # RP4 status is intentionally not asserted here: deferred/rejected
            # completion semantics remain a human canon decision.

        ignored = snapshots["ignore_and_chat"]
        assert ignored["transaction"] is None
        assert ignored["player_actions"] == ()
        assert "RP4" not in ignored["completed"]
        assert exits["ignore_and_chat"]["action"] == "continue"

        for name, packet in packets.items():
            assert (packet.get("cog_loop") or {}).get("decide", {}).get("top_concern")
            if name in {"high_beats", "ambiguous_response"}:
                prior = (packet.get("cog_loop") or {}).get("prior_reflect") or {}
                assert prior.get("thought")
                assert "不能替对方收下" in prior["thought"]


def test_reflect_uses_world_disposition_not_rp4_assumption():
    base = dict(
        cons_id="C.ryuya.W1",
        decide={"band": "pendant", "top_concern": "处理挂坠", "top_concern_id": "hand_pendant"},
        spoken_texts=["嗯。"],
        player_speech="",
        completed_after=["RP1", "RP2", "RP3", "RP4"],
    )
    accepted = cogloop.build_reflect_thought(**base, pendant_disposition="accepted")
    declined = cogloop.build_reflect_thought(**base, pendant_disposition="declined")
    deferred = cogloop.build_reflect_thought(**base, pendant_disposition="deferred")
    legacy = cogloop.build_reflect_thought(**base, pendant_disposition="")
    assert accepted and "明确收下" in accepted["thought"]
    assert declined and "明确不收" in declined["thought"]
    assert deferred and "暂时没有收下" in deferred["thought"]
    assert legacy and "没有可引用的世界收据" in legacy["thought"]
    for row in (declined, deferred, legacy):
        assert "已经交出去了" not in row["thought"]


def test_accept_continue_chat_then_explicit_exit():
    with tempfile.TemporaryDirectory() as tmp:
        caller = MatrixCaller([
            {"text": "嗯。", "stage": ""},
            {"text": "这都记着？", "stage": ""},
            {"text": "回头见。", "stage": ""},
        ])
        session, state_dir = _new_session(
            tmp,
            "accept-chat-exit",
            caller,
            completed=("RP1", "RP2", "RP3"),
            branch=("prologue_pendant_offered",),
        )

        _r1, d1 = _run_step(
            session, {"speech": "好，我收下", "action": "", "thought": ""}
        )
        assert session._world_transaction("ryuya_pendant_disposition")["outcome"] == "accepted"
        assert session.ended is False
        assert d1[-1]["action"] == "continue"
        first_tx = json.dumps(
            session._world_transaction("ryuya_pendant_disposition"),
            ensure_ascii=False,
            sort_keys=True,
        )
        session = _assert_reload_equal(session, state_dir, caller, tmp)

        _r2, d2 = _run_step(
            session, {"speech": "你还欠我一杯咖啡呢", "action": "", "thought": ""}
        )
        assert session.ended is False
        assert d2[-1]["action"] == "continue"
        assert json.dumps(
            session._world_transaction("ryuya_pendant_disposition"),
            ensure_ascii=False,
            sort_keys=True,
        ) == first_tx
        packet = _assert_actor_request(
            caller, {"speech": "你还欠我一杯咖啡呢", "action": "", "thought": ""}
        )
        prior = (packet.get("cog_loop") or {}).get("prior_reflect") or {}
        assert prior.get("thought")
        assert "明确收下" in prior["thought"]
        session = _assert_reload_equal(session, state_dir, caller, tmp)

        _r3, d3 = _run_step(
            session, {"speech": "那我先走了，回头见。", "action": "", "thought": ""}
        )
        assert d3[-1]["action"] == "end_run"
        assert session.ended is True
        assert session.lifecycle_state == "closed"
        _assert_reload_equal(session, state_dir, caller, tmp)


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
