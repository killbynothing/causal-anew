#!/usr/bin/env python3
from __future__ import annotations

import copy
import inspect
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import actor_orchestrator
from runtime import participation as p4
from runtime.actor_mind import build_actor_mind
from runtime.free_stage_prototype import (
    apply_stall_escalation_to_speaker_plan,
    apply_visible_group_output_budget,
    build_floor_plan,
    build_participation_deliberation,
    build_speaker_plan,
    ensure_solo_or_prologue_speakers,
    FreeStageSession,
)
from runtime.intent_runtime import ensure_decision_target_in_speaker_plan


def _card() -> dict:
    return {
        "scene_id": "P4_FIXTURE",
        "present": ["C.akito.WMAIN", "C.kakashi.WMAIN"],
        "persona_cards": {
            "C.akito.WMAIN": {
                "name": "川口秋人",
                "inner_state": {"want_now": "处理眼前对话"},
                "scene_working_memory": {"goals": ["处理眼前对话"], "commitments": []},
            },
            "C.kakashi.WMAIN": {
                "name": "坂本晴明",
                "inner_state": {"want_now": "先观察"},
                "scene_working_memory": {"goals": ["先观察"], "commitments": []},
            },
        },
        "must_happen": [{"id": "SECRET_MH", "desc": "director-only goal text"}],
        "scene_frame": {"此刻想要什么": "SECRET_DIRECTOR_GOAL"},
    }


def _minds(card: dict) -> dict:
    return {
        cons: build_actor_mind(cons, persona)
        for cons, persona in card["persona_cards"].items()
    }


def test_private_thought_does_not_change_intent_or_floor():
    card = _card()
    minds = _minds(card)
    a = build_speaker_plan(
        copy.deepcopy(card),
        history=[],
        player_input={"speech": "没事，你们继续。", "action": "", "thought": "SECRET_A"},
        actor_minds=minds,
    )
    b = build_speaker_plan(
        copy.deepcopy(card),
        history=[],
        player_input={"speech": "没事，你们继续。", "action": "", "thought": "SECRET_B"},
        actor_minds=minds,
    )
    assert a["participation_intents"] == b["participation_intents"]
    assert a["floor_inputs"] == b["floor_inputs"]
    assert a["floor_grants"] == b["floor_grants"]
    assert "SECRET_A" not in json.dumps(a["floor_inputs"], ensure_ascii=False)
    assert "SECRET_B" not in json.dumps(b["floor_inputs"], ensure_ascii=False)


def test_director_mh_text_cannot_change_actor_intent():
    card_a = _card()
    card_b = _card()
    card_b["must_happen"] = [{"id": "OTHER_MH", "desc": "completely different director task"}]
    card_b["scene_frame"]["此刻想要什么"] = "DIFFERENT_DIRECTOR_GOAL"
    minds = _minds(card_a)
    kwargs = dict(
        history=[],
        player_input={"speech": "没事，你们继续。", "action": "", "thought": ""},
        actor_minds=minds,
    )
    a = build_speaker_plan(card_a, **kwargs)
    b = build_speaker_plan(card_b, **kwargs)
    assert a["participation_intents"] == b["participation_intents"]
    assert a["floor_inputs"] == b["floor_inputs"]


def test_mind_difference_changes_actor_owned_intent_without_floor_reading_content():
    no_commitment = build_actor_mind(
        "C.fixture.W1",
        {"inner_state": {"want_now": "观察"}, "scene_working_memory": {"commitments": []}},
    )
    with_commitment = build_actor_mind(
        "C.fixture.W1",
        {
            "inner_state": {"want_now": "观察"},
            "scene_working_memory": {"commitments": ["已答应的事"]},
        },
    )
    quiet = {"speech": "", "action": "", "thought": "private"}
    a = p4.deliberate_participation(
        "C.fixture.W1", no_commitment, quiet, participation_style="mixed"
    )
    b = p4.deliberate_participation(
        "C.fixture.W1", with_commitment, quiet, participation_style="mixed"
    )
    assert a.mode == "pass"
    assert b.mode == "speak"
    floor_blob = json.dumps(p4.floor_view(b), ensure_ascii=False)
    assert "已答应的事" not in floor_blob
    assert "观察" not in floor_blob


def test_side_and_action_modes_are_actor_owned_legal_results():
    mind = build_actor_mind(
        "C.fixture.W1",
        {"inner_state": {"want_now": "观察"}, "scene_working_memory": {"commitments": []}},
    )
    side = p4.deliberate_participation(
        "C.fixture.W1",
        mind,
        {"speech": "", "action": "", "thought": "private"},
        participation_style="mixed",
        recent_public_actor="C.other.W1",
    )
    assert (side.mode, side.lane) == ("side", "companion")

    action = p4.deliberate_participation(
        "C.fixture.W1",
        mind,
        {"speech": "", "action": "向旁边让开一步", "thought": "private"},
        participation_style="backchannel_preferred",
    )
    assert (action.mode, action.lane) == ("action", "stage")

    grants = p4.arbitrate_floor([side, action], max_floor=1, max_companion=2, max_stage=1)
    modes = {(item.mode, item.lane) for item in grants}
    assert ("side", "companion") in modes
    assert ("action", "stage") in modes


def test_floor_uses_obligation_urgency_and_fairness_only():
    a = p4.ParticipationIntent(
        actor_cons="C.a.W1", mode="speak", urgency=0.7, lane="floor",
        reason_codes=("SECRET_GOAL_A",),
    )
    b = p4.ParticipationIntent(
        actor_cons="C.b.W1", mode="speak", urgency=0.7, lane="floor",
        reason_codes=("SECRET_GOAL_B",),
    )
    fair = p4.arbitrate_floor([a, b], recent_occupancy={"C.a.W1": 3}, max_floor=1)
    assert fair[0].actor_cons == "C.b.W1"

    obligated = p4.ParticipationIntent(
        actor_cons="C.a.W1", mode="speak", urgency=1.0, lane="floor",
        addressee="player", public_obligation=True, obligation_kind="direct_address",
        reason_codes=("SECRET_GOAL_A",),
    )
    grant = p4.arbitrate_floor(
        [obligated, b], recent_occupancy={"C.a.W1": 9}, max_floor=1
    )
    assert grant[0].actor_cons == "C.a.W1"
    visible = json.dumps(p4.floor_view(obligated), ensure_ascii=False)
    assert "SECRET_GOAL" not in visible
    assert "reason_codes" not in visible


def test_single_actor_quiet_turn_may_pass_without_fallback_speaker():
    card = {
        "scene_id": "P4_SOLO",
        "present": ["C.fixture.W1"],
        "persona_cards": {
            "C.fixture.W1": {
                "name": "独处者",
                "inner_state": {"want_now": "观察"},
                "scene_working_memory": {"goals": ["观察"], "commitments": []},
            }
        },
    }
    mind = {"C.fixture.W1": build_actor_mind("C.fixture.W1", card["persona_cards"]["C.fixture.W1"])}
    plan = build_speaker_plan(
        card,
        history=[],
        player_input={"speech": "", "action": "", "thought": "只在心里"},
        actor_minds=mind,
    )
    assert plan["speakers"] == []
    assert plan["floor_grants"] == []
    assert plan["allow_silence"] is True
    shim = ensure_solo_or_prologue_speakers(plan, card)
    assert shim["speakers"] == []


def test_stall_escalation_cannot_allocate_floor():
    base = {
        "speakers": [],
        "floor_grants": [],
        "participation_intents": [],
        "allow_silence": True,
    }
    out = apply_stall_escalation_to_speaker_plan(
        base,
        {
            "kind": "stall_scene_working_goal",
            "actor_cons": "C.a.W1",
            "goal": "SECRET_GOAL",
            "instruction": "advance",
            "trigger_stall": 2,
        },
    )
    assert out["speakers"] == []
    assert out["floor_grants"] == []
    assert out["stall_escalation_floor_effect"] == "none"


def test_ungranted_actor_enactment_is_filtered():
    plan = {
        "speakers": [
            {
                "cons": "C.akito.WMAIN",
                "response_slot": "primary",
                "participation_mode": "speak",
            }
        ],
        "stage_actors": [],
        "backchannel_actors": [],
        "side_actors": [],
        "companion_actors": [],
    }
    turns = [
        {
            "speaker": "川口秋人", "cons": "C.akito.WMAIN",
            "text": "我来回应。", "stage": "",
        },
        {
            "speaker": "坂本晴明", "cons": "C.kakashi.WMAIN",
            "text": "UNGRANTED", "stage": "",
        },
    ]
    bounded, _ = apply_visible_group_output_budget(turns, plan, _card())
    blob = json.dumps(bounded, ensure_ascii=False)
    assert "我来回应" in blob
    assert "UNGRANTED" not in blob


def test_observable_request_grants_response_opportunity_but_actor_may_pass():
    base = {
        "max_speakers": 1,
        "speakers": [],
        "stage_actors": [],
        "backchannel_actors": [],
        "side_actors": [],
        "companion_actors": [],
        "participation_intents": [],
        "floor_inputs": [],
        "floor_grants": [],
        "allow_silence": True,
    }
    resolution = SimpleNamespace(
        feasibility=SimpleNamespace(
            status="negotiate_now",
            intent=SimpleNamespace(
                target="C.akito.WMAIN",
                intent_id="intent:p4:fixture",
            ),
        )
    )
    out = ensure_decision_target_in_speaker_plan(base, resolution)
    contract = out["conversation_contract"]
    assert contract["kind"] == "observable_intent_request"
    assert contract["actor_may_pass"] is True
    speaker = out["speakers"][0]
    assert speaker["cons"] == "C.akito.WMAIN"
    assert speaker["actor_may_pass"] is True
    grant = next(
        item for item in out["floor_grants"]
        if item["actor_cons"] == "C.akito.WMAIN"
    )
    assert grant["public_obligation"] is True
    blob = json.dumps(out, ensure_ascii=False)
    assert '"outcome"' not in blob
    assert '"answer"' not in blob


def test_barge_in_discards_unplayed_queue_without_recording_line_fact():
    card = ROOT / "runtime" / "free_stage_card_16zhong_gate.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = FreeStageSession(
            session_id="p4-queue-cancel",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=lambda **_: json.dumps(
                {"turns": [], "mh_progress": [], "director_note": ""},
                ensure_ascii=False,
            ),
        )
        before = json.dumps(session.history, ensure_ascii=False)
        session.utterance_pending_queue = [
            {
                "role": "npc",
                "speaker": "川口秋人",
                "cons": "C.akito.WMAIN",
                "text": "QUEUED_NOT_SPOKEN",
                "turn": 1,
                "provenance": {},
            }
        ]
        session._barge_in_stream()
        after = json.dumps(session.history, ensure_ascii=False)
        assert session.utterance_pending_queue == []
        assert "QUEUED_NOT_SPOKEN" not in after
        assert before == after


def test_actor_runner_metrics_count_only_actual_actor_calls():
    calls: list[str] = []

    def director_call(prompt, config, caller):
        return {
            "turns": [],
            "mh_progress": [],
            "director_note": "",
            "context_receipt": {"kind": "director"},
        }

    def actor_call(packet, config, caller):
        cons = str(packet.get("actor_cons") or "")
        calls.append(cons)
        return {
            "turns": [],
            "actor_decisions": [],
            "context_receipt": {"kind": "actor", "actor_cons": cons},
        }

    def degradation(*args, **kwargs):
        return {"kind": str(args[1] if len(args) > 1 else "degradation")}

    packets = [
        (
            "C.a.W1",
            {
                "actor_cons": "C.a.W1",
                "observable_dialogue": [],
                "conversation_contract": {
                    "response_slot": "primary",
                    "participation_mode": "speak",
                },
            },
        ),
        (
            "C.b.W1",
            {
                "actor_cons": "C.b.W1",
                "observable_dialogue": [],
                "conversation_contract": {
                    "response_slot": "backchannel",
                    "participation_mode": "backchannel",
                },
            },
        ),
    ]
    payload, _ = actor_orchestrator.dispatch_turn(
        "{}",
        packets,
        {},
        director_call=director_call,
        actor_call=actor_call,
        degradation=degradation,
        caller=lambda **_: "{}",
    )
    assert calls == ["C.a.W1", "C.b.W1"]
    assert payload["actor_call_count"] == 2
    metrics = payload["actor_call_metrics"]
    assert len(metrics) == 2
    assert all(float(item["latency_ms"]) >= 0.0 for item in metrics)
    assert [item["actor_cons"] for item in metrics] == calls

    empty_payload, _ = actor_orchestrator.dispatch_turn(
        "{}",
        [],
        {},
        director_call=director_call,
        actor_call=actor_call,
        degradation=degradation,
        caller=lambda **_: "{}",
    )
    assert empty_payload["actor_call_count"] == 0
    assert empty_payload["actor_call_metrics"] == []


def test_production_floor_builder_no_longer_calls_legacy_content_bidding():
    facade_source = inspect.getsource(build_speaker_plan)
    assert "build_participation_deliberation(" in facade_source
    assert "build_floor_plan(" in facade_source
    for forbidden in (
        "bid_turn_taking(",
        "_speaker_bid_modifiers(",
        "participation_runtime.deliberate_participation(",
        "participation_runtime.arbitrate_floor(",
    ):
        assert forbidden not in facade_source, forbidden

    deliberate_source = inspect.getsource(build_participation_deliberation)
    for forbidden in (
        "bid_turn_taking(",
        "_speaker_bid_modifiers(",
        "participation_runtime.arbitrate_floor(",
    ):
        assert forbidden not in deliberate_source, forbidden
    assert "participation_runtime.deliberate_participation(" in deliberate_source

    floor_source = inspect.getsource(build_floor_plan)
    assert floor_source.count("participation_runtime.arbitrate_floor(") == 1
    assert "participation_runtime.deliberate_participation(" not in floor_source
    for forbidden in (
        "short_term_agenda",
        "scene_working_memory",
        "must_happen",
        "director_instruction",
        "player_input",
        "history",
        "card",
    ):
        assert forbidden not in floor_source, forbidden

    request_source = inspect.getsource(ensure_decision_target_in_speaker_plan)
    assert "participation_runtime.arbitrate_floor(" in request_source
    assert "free_stage.floor_grant.v1" not in request_source


def test_failed_actor_call_attempt_is_still_measured():
    def failing_actor(packet, config, caller):
        raise RuntimeError("fixture actor failure")

    def degradation(*args, **kwargs):
        return {"kind": "fixture"}

    result = actor_orchestrator._run_actors_sequential(
        [
            (
                "C.fail.W1",
                {
                    "actor_cons": "C.fail.W1",
                    "observable_dialogue": [],
                    "conversation_contract": {
                        "response_slot": "primary",
                        "participation_mode": "speak",
                    },
                },
            )
        ],
        {},
        actor_call=failing_actor,
        degradation=degradation,
        caller=lambda **_: "{}",
    )
    turns, decisions, receipts, degradations, errors, metrics = result
    assert turns == []
    assert decisions == []
    assert receipts == []
    assert errors and "fixture actor failure" in errors[0]
    assert len(metrics) == 1
    assert metrics[0]["actor_cons"] == "C.fail.W1"
    assert metrics[0]["success"] is False
    assert float(metrics[0]["latency_ms"]) >= 0.0
    assert "fixture actor failure" in metrics[0]["error"]


def test_plan_adds_zero_llm_participation_and_floor_has_no_private_fields():
    card = _card()
    plan = build_speaker_plan(
        card,
        history=[],
        player_input={"speech": "你们好", "action": "", "thought": "SECRET_THOUGHT"},
        actor_minds=_minds(card),
    )
    assert plan["participation_llm_calls"] == 0
    floor_blob = json.dumps(plan["floor_inputs"], ensure_ascii=False)
    for forbidden in ("SECRET_THOUGHT", "SECRET_MH", "SECRET_DIRECTOR_GOAL", "处理眼前对话", "先观察"):
        assert forbidden not in floor_blob


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
