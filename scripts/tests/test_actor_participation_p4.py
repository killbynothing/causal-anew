#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import participation as p4
from runtime.actor_mind import build_actor_mind
from runtime.free_stage_prototype import (
    apply_stall_escalation_to_speaker_plan,
    apply_visible_group_output_budget,
    build_speaker_plan,
    ensure_solo_or_prologue_speakers,
)


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
