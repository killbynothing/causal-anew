# -*- coding: utf-8 -*-
"""Dual-lane companion: side actors + floor/companion stream routing."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime import social_participation as soc
from runtime import utterance_stream as ustream
from runtime.free_stage_prototype import build_speaker_plan


def _mini_card() -> dict:
    return {
        "scene_id": "OPENING_TIANANMEN_002",
        "present": ["C.xiuzai.WMAIN", "C.akito.WMAIN", "C.kakashi.WMAIN"],
        "persona_cards": {
            "C.xiuzai.WMAIN": {"name": "折原修哉", "inner_state": {}},
            "C.akito.WMAIN": {"name": "川口秋人", "inner_state": {}},
            "C.kakashi.WMAIN": {"name": "坂本晴明", "inner_state": {}},
        },
    }


def test_pick_side_actors_prefers_xiuzai():
    card = _mini_card()
    plan = {
        "speakers": [{"cons": "C.akito.WMAIN", "name": "川口秋人"}],
        "bids": [
            {"cons": "C.xiuzai.WMAIN", "name": "折原修哉", "score": 0.4, "reasons": []},
            {"cons": "C.kakashi.WMAIN", "name": "坂本晴明", "score": 0.2, "reasons": []},
        ],
        "backchannel_actors": [
            {
                "cons": "C.kakashi.WMAIN",
                "participation_mode": "backchannel",
                "response_slot": "backchannel",
            }
        ],
    }
    side = soc.pick_side_actors(plan, card, max_n=1)
    assert side
    assert side[0]["cons"] == "C.xiuzai.WMAIN"
    assert side[0]["participation_mode"] == "side"
    assert side[0]["stream_lane"] == "companion"


def test_speaker_plan_has_companion_actors():
    plan = build_speaker_plan(
        _mini_card(),
        history=[],
        player_input={"speech": "没事。"},
        completed=["TM1"],
        branch_progress=[],
    )
    assert plan.get("speakers")
    companion = plan.get("companion_actors") or []
    modes = {str(x.get("participation_mode")) for x in companion}
    assert modes & {"backchannel", "side"}
    # Companion slots must not steal floor speaker cons.
    floor = {str(x.get("cons")) for x in (plan.get("speakers") or [])}
    for row in companion:
        assert row["cons"] not in floor


def test_route_turns_by_lane_splits():
    turns = [
        {"role": "npc", "speaker": "秋人", "text": "对不起。", "participation_mode": "speak"},
        {
            "role": "npc",
            "speaker": "修哉",
            "text": "行了行了。",
            "participation_mode": "side",
            "cons": "C.xiuzai.WMAIN",
        },
        {
            "role": "npc",
            "speaker": "晴明",
            "text": "嗯。",
            "participation_mode": "backchannel",
            "cons": "C.kakashi.WMAIN",
        },
    ]
    floor, companion = ustream.route_turns_by_lane(turns, None, turn_no=1)
    assert len(floor) == 1 and floor[0]["text"] == "对不起。"
    assert len(companion) == 2
    assert all(t["stream_lane"] == "companion" for t in companion)


def test_habit_text_side_skips_single_fta():
    text = soc.habit_text("C.xiuzai.WMAIN", participation_mode="side")
    assert "单 FTA" not in text and "face-sensitive" not in text
    assert "损" in text or "同伴" in text or "秋人" in text


def test_enrich_synthetic_last_resort_only():
    card = _mini_card()
    plan = {
        "companion_actors": [
            {
                "cons": "C.kakashi.WMAIN",
                "participation_mode": "backchannel",
                "response_slot": "backchannel",
            }
        ]
    }
    # Already spoke — no synthetic.
    out = ustream.enrich_turns_with_companion_queue(
        [{"role": "npc", "cons": "C.kakashi.WMAIN", "text": "嗯。", "participation_mode": "backchannel"}],
        plan,
        card,
        turn_no=1,
    )
    assert len(out) == 1
    # Silent — one synthetic fallback.
    out2 = ustream.enrich_turns_with_companion_queue([], plan, card, turn_no=1)
    assert len(out2) == 1
    assert out2[0].get("synthetic_fallback") is True


def test_side_ja_mark_before_language_confirm():
    from runtime.free_stage_prototype import localize_kakashi_surface

    card = _mini_card()
    turns = [
        {
            "role": "npc",
            "speaker": "折原修哉",
            "cons": "C.xiuzai.WMAIN",
            "text": "行了行了，别把人吓跑。",
            "participation_mode": "side",
        }
    ]
    before = localize_kakashi_surface(turns, understood_by_player=False, card=card)
    assert before[0]["text"].startswith("（日语）")
    after = localize_kakashi_surface(turns, understood_by_player=True, card=card)
    assert not after[0]["text"].startswith("（日语）")
    assert "日语" not in after[0]["text"]


def test_must_happen_env_hint_not_speaker_script():
    card = {
        **_mini_card(),
        "must_happen": [{"id": "TM2", "desc": "秋人试探借视频"}],
    }
    assert soc.must_happen_director_env_hint(card, [], stall=0) is None
    hint = soc.must_happen_director_env_hint(card, [], stall=2)
    assert hint and hint["beat_id"] == "TM2"
    assert "不要派" in hint["hint"] or "环境" in hint["hint"]
    plan = build_speaker_plan(
        card,
        history=[],
        player_input={"speech": ""},
        completed=[],
        branch_progress=[],
    )
    # Empty beat_speaker_hints — MH must not assign speakers.
    assert plan.get("beat_speaker_hints") == []


def test_normalize_participation_mode():
    assert soc.normalize_participation_mode("side") == "side"
    try:
        soc.normalize_participation_mode("chorus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_actor_decision_participation_mode_field():
    from runtime.director_intent import ActorDecision, validate_actor_decision

    ok = ActorDecision(
        actor_cons="C.xiuzai.WMAIN",
        intent_id="i1",
        outcome="defer",
        visible_response="先这样。",
        reason_sources=("self_state.inner_state.want_now",),
        participation_mode="side",
    )
    validate_actor_decision(ok)
    bad = dict(ok.to_dict())
    bad["participation_mode"] = "chorus"
    try:
        validate_actor_decision(bad)
        assert False, "expected ValueError"
    except ValueError:
        pass


if __name__ == "__main__":
    test_pick_side_actors_prefers_xiuzai()
    test_speaker_plan_has_companion_actors()
    test_route_turns_by_lane_splits()
    test_habit_text_side_skips_single_fta()
    test_enrich_synthetic_last_resort_only()
    test_side_ja_mark_before_language_confirm()
    test_must_happen_env_hint_not_speaker_script()
    test_normalize_participation_mode()
    test_actor_decision_participation_mode_field()
    print("PASS")
