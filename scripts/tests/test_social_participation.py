# -*- coding: utf-8 -*-
"""Social participation: concern queues, floor-only bidding, backchannel."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime import social_participation as soc
from runtime.free_stage_prototype import advance_tiananmen_want_now, build_speaker_plan


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


def test_concern_queue_single_top_after_language():
    concerns = soc.build_open_concerns_tiananmen(
        "C.akito.WMAIN",
        branch_progress={"tiananmen_japanese_understood"},
        history=[],
        player_input={"speech": "听得懂，没事。"},
    )
    assert len(concerns) == 1
    assert any(tok in concerns[0] for tok in ("视频", "录像", "单反"))
    assert "并试着" not in concerns[0]
    assert "若这个人居然听得懂" not in concerns[0]


def test_concern_queue_bump_first():
    concerns = soc.build_open_concerns_tiananmen(
        "C.akito.WMAIN",
        branch_progress=set(),
        history=[],
        player_input={"speech": ""},
    )
    assert concerns and ("道歉" in concerns[0] or "蹭" in concerns[0])
    assert "借" not in concerns[0]


def test_advance_tiananmen_splits_want_not_checklist():
    card = _mini_card()
    advance_tiananmen_want_now(
        card,
        ["tiananmen_japanese_understood"],
        history=[{"role": "player", "text": "没事，听得懂日语。", "turn": 1}],
        player_input={"speech": "听得懂日语。"},
    )
    inner = card["persona_cards"]["C.akito.WMAIN"]["inner_state"]
    want = str(inner.get("want_now") or "")
    assert "并" not in want or ("借" in want and "道歉" not in want)
    assert "pending_concerns" in inner
    assert not any("并试着借" in str(x) for x in [want] + list(inner.get("pending_concerns") or []))


def test_speaker_plan_no_content_boost_reason():
    card = _mini_card()
    plan = build_speaker_plan(
        card,
        history=[],
        player_input={"speech": "听得懂，你们继续说。"},
        completed=["TM1", "TM2"],
        branch_progress=["tiananmen_japanese_understood"],
    )
    bids = plan.get("bids") or []
    assert not any("natural_video_ask_opening" in (b.get("reasons") or []) for b in bids)
    bc = plan.get("backchannel_actors") or []
    bc_cons = [str(x.get("cons")) for x in bc]
    assert "C.kakashi.WMAIN" in bc_cons or len(plan.get("speakers") or []) >= 1


def test_habit_includes_single_fta_and_language():
    hint = soc.hold_slot_social_hint_v2([], actor_cons="C.kakashi.WMAIN", participation_mode="backchannel")
    assert "backchannel" in hint.lower() or "短接" in hint
    assert "中文" in hint
    assert "face-sensitive" in hint or "一个" in hint


if __name__ == "__main__":
    test_concern_queue_single_top_after_language()
    test_concern_queue_bump_first()
    test_advance_tiananmen_splits_want_not_checklist()
    test_speaker_plan_no_content_boost_reason()
    test_habit_includes_single_fta_and_language()
    print("PASS")
