# -*- coding: utf-8 -*-
"""Solidified facts → actor packets; no hard roster suppress; HOLD slot hint."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime.actor_orchestrator import enrich_packet_with_same_turn_prior
from runtime.free_stage_prototype import (
    annotate_packets_with_spoken_turns,
    apply_body_frame_holding,
    build_actor_context_packet,
    build_solidified_visible_facts,
    build_visible_holding_map,
    ensure_card_body_frames,
    extract_object_use_memory,
    fact_packet_coverage,
    hold_slot_social_hint,
    settle_body_frames_from_npc_turns,
)


def _mini_tiananmen_card() -> dict:
    return {
        "scene_id": "OPENING_TIANANMEN_002",
        "scene_frame": {"where": "天安门广场", "when": "清晨"},
        "present": ["C.xiuzai.WMAIN", "C.akito.WMAIN", "C.haruaki.WMAIN"],
        "persona_cards": {
            "C.xiuzai.WMAIN": {"name": "折原修哉", "inner_state": {"want_now": "把场面撑住"}},
            "C.akito.WMAIN": {"name": "川口秋人", "inner_state": {"want_now": "借视频"}},
            "C.haruaki.WMAIN": {"name": "坂本晴明", "inner_state": {"want_now": "少开口"}},
        },
    }


def test_solidified_name_facts_land_in_packet():
    card = _mini_tiananmen_card()
    ensure_card_body_frames(card, {})
    history = [
        {
            "role": "npc",
            "speaker": "折原修哉",
            "cons": "C.xiuzai.WMAIN",
            "text": "我是折原修哉，请多指教。",
            "turn": 1,
        }
    ]
    facts = build_solidified_visible_facts(card, history, branch_progress=[])
    assert any("折原修哉" in f and "自报" in f for f in facts), facts
    card["_solidified_visible_facts"] = facts
    packet = build_actor_context_packet(
        card,
        "C.akito.WMAIN",
        history=history,
        player_input={"speech": "走吧"},
        turn_no=2,
        world_cursor={"ch_anchor": 0, "run": 1},
    )
    scene = packet.get("physical_scene") or {}
    landed = scene.get("场面已成立的事实") or []
    assert any("折原修哉" in str(x) for x in landed), landed
    coverage = fact_packet_coverage(facts, {"C.akito.WMAIN": packet})
    assert coverage and not coverage[0]["missing"], coverage


def test_visible_holding_and_phone_settle():
    card = _mini_tiananmen_card()
    frames = ensure_card_body_frames(card, {})
    body_id = None
    for bid, fr in frames.items():
        if fr.get("cons_id") == "C.akito.WMAIN" or "akito" in str(bid).lower():
            body_id = bid
            break
    if body_id is None:
        body_id = "B.akito.WMAIN"
        frames[body_id] = {
            "cons_id": "C.akito.WMAIN",
            "posture": "standing",
            "hands": "free",
            "holding": None,
        }
    apply_body_frame_holding(
        frames,
        body_id=body_id,
        holding="I.PHONE",
        note="正拿着玩家手机看视频",
        last_action_type="object_handle",
    )
    card["_body_frames"] = frames
    holding_lines = build_visible_holding_map(card)
    assert any("手机" in line for line in holding_lines), holding_lines
    card["_solidified_visible_facts"] = []
    packet = build_actor_context_packet(
        card,
        "C.akito.WMAIN",
        history=[],
        player_input={"speech": "拍得不错"},
        turn_no=1,
        world_cursor={"ch_anchor": 0, "run": 1},
    )
    assert "场上可见物态" in (packet.get("physical_scene") or {})
    turns = [
        {
            "role": "npc",
            "speaker": "川口秋人",
            "cons": "C.akito.WMAIN",
            "text": "嗯。",
            "stage": "他把手机还给对方",
        }
    ]
    settle_body_frames_from_npc_turns(frames, card, turns)
    assert frames[body_id].get("holding") is None
    assert "手机" in str(frames[body_id].get("note") or "")


def test_hold_slot_and_secondary_no_phone_script():
    hint = hold_slot_social_hint(
        [{"prop_id": "REL.HOLD.x", "fact": "依赖修哉拦截漏嘴", "projection": "relation_hold"}],
        "secondary",
        actor_cons="C.akito.WMAIN",
    )
    assert "单反" in hint or "借" in hint or "实诚" in hint
    assert "还手机" not in hint
    packet = {
        "observable_dialogue": [],
        "conversation_contract": {"response_slot": "secondary", "social_instruction": ""},
    }
    enriched = enrich_packet_with_same_turn_prior(
        packet,
        [{"speaker": "折原修哉", "text": "借个视频呗", "stage": ""}],
    )
    si = str((enriched.get("conversation_contract") or {}).get("social_instruction") or "")
    assert "听见" in si or "接" in si
    assert "还手机" not in si
    assert "批准旁听" not in si


def test_annotate_spoken_and_no_suppress_symbol():
    import runtime.free_stage_prototype as fsp

    assert not hasattr(fsp, "suppress_repeat_roster_after_intro")
    card = _mini_tiananmen_card()
    packets = {"C.xiuzai.WMAIN": {}}
    annotate_packets_with_spoken_turns(
        packets,
        [{"cons": "C.xiuzai.WMAIN", "text": "走吧。", "stage": ""}],
        card,
    )
    assert packets["C.xiuzai.WMAIN"]["spoken_this_turn"][0]["text"] == "走吧。"


def test_prologue_locks_without_negative_whitelist():
    card = json.loads((ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8"))
    locks = "\n".join(card.get("locks") or [])
    gate = "\n".join((card.get("memory_layers") or {}).get("knowledge_gate") or [])
    assert "不要补造对方点单口味" not in locks
    assert "不要补造对方点单口味" not in gate
    assert "共同经历只轻提" in locks or "轻提" in gate


def test_object_use_memory_and_pendant_hidden():
    card = _mini_tiananmen_card()
    frames = ensure_card_body_frames(card, {})
    for bid, fr in list(frames.items()):
        if fr.get("cons_id") == "C.akito.WMAIN" or "akito" in str(bid).lower():
            apply_body_frame_holding(
                frames, body_id=bid, holding="I.CAMERA_DSLR", note="挎着单反",
            )
            break
    else:
        frames["B.akito.WMAIN"] = {
            "cons_id": "C.akito.WMAIN", "holding": "I.CAMERA_DSLR", "note": "挎着单反",
            "hands": "holding:I.CAMERA_DSLR", "posture": "standing",
        }
    card["_body_frames"] = frames
    frames["B.fake"] = {
        "cons_id": "C.xiuzai.WMAIN", "holding": "I.PENDANT_ANCHOR", "note": "挂坠",
        "hands": "holding:I.PENDANT_ANCHOR",
    }
    holding = build_visible_holding_map(card)
    assert any("单反" in x for x in holding), holding
    assert not any("挂坠" in x or "PENDANT" in x for x in holding), holding
    history = [
        {
            "role": "npc", "speaker": "川口秋人", "cons": "C.akito.WMAIN",
            "text": "我拿单反拍升旗了。", "stage": "举起相机", "turn": 1,
        }
    ]
    used = extract_object_use_memory(card, history)
    assert any("单反" in x for x in used), used
    packet = build_actor_context_packet(
        card, "C.akito.WMAIN", history=history,
        player_input={"speech": "拍得怎么样"}, turn_no=2,
        world_cursor={"ch_anchor": 0, "run": 1},
    )
    scene = packet.get("physical_scene") or {}
    assert scene.get("本场用过的物件")
    assert scene.get("场上可见物态")


def test_pre_speech_synthesized():
    from runtime.free_stage_prototype import synthesize_pre_speech
    packet = {
        "self_state": {"inner_state": {"want_now": "把场面撑住"}},
        "conversation_contract": {"response_slot": "primary"},
        "physical_scene": {},
        "body_frame_now": {},
    }
    pre = synthesize_pre_speech(packet, None)
    assert pre["intention"]
    assert pre["synthesized"] is True
    authored = synthesize_pre_speech(packet, {"notice": "听见借视频", "intention": "先打圆场", "social_move": "pivot"})
    assert authored["synthesized"] is False
    assert authored["social_move"] == "pivot"


def test_hard_check_respects_progressive_name_binding():
    from runtime.free_stage_prototype import hard_check

    card = _mini_tiananmen_card()
    history_leak = [
        {"role": "npc", "speaker": "川口秋人", "text": "嗨。", "turn": 1},
    ]
    issues = hard_check(history_leak, completed=[], card=card)
    assert any("pre-intro real name" in x and "川口秋人" in x for x in issues), issues
    history_ok = [
        {
            "role": "npc",
            "speaker": "圆脸青年",
            "cons": "C.akito.WMAIN",
            "text": "我是川口秋人，请多指教。",
            "turn": 1,
        },
        {"role": "npc", "speaker": "川口秋人", "text": "那个视频…", "turn": 2},
    ]
    issues_ok = hard_check(history_ok, completed=[], card=card)
    assert not any("pre-intro real name" in x for x in issues_ok), issues_ok


def test_tiananmen_speaker_plan_floor_only_no_content_boost():
    from runtime.free_stage_prototype import build_speaker_plan, MAX_BID_SPEAKERS

    card = _mini_tiananmen_card()
    plan = build_speaker_plan(
        card,
        history=[],
        player_input={"speech": "听得懂，你们继续说。"},
        completed=["TM1", "TM2"],
        branch_progress=["tiananmen_japanese_understood"],
    )
    assert int(plan.get("max_speakers") or 0) == MAX_BID_SPEAKERS
    bids = plan.get("bids") or []
    assert not any("natural_video_ask_opening" in (b.get("reasons") or []) for b in bids)
    bc = plan.get("backchannel_actors") or []
    assert any(str(x.get("cons")) == "C.kakashi.WMAIN" for x in bc) or len(plan.get("speakers") or []) >= 1


def test_observatory_inner_does_not_fill_toxic_unsaid():
    from runtime.free_stage_prototype import _merge_inner_for_observatory, project_initial_inner_state

    default = project_initial_inner_state("C.kakashi.WMAIN", 0)
    assert "一进场就察觉" not in str(default.get("unsaid") or "")
    merged = _merge_inner_for_observatory({"want_now": "少开口"}, "C.kakashi.WMAIN", 0)
    assert merged.get("want_now") == "少开口"
    assert "unsaid" not in merged or merged.get("unsaid") in (None, "")


if __name__ == "__main__":
    test_solidified_name_facts_land_in_packet()
    test_visible_holding_and_phone_settle()
    test_hold_slot_and_secondary_no_phone_script()
    test_annotate_spoken_and_no_suppress_symbol()
    test_prologue_locks_without_negative_whitelist()
    test_object_use_memory_and_pendant_hidden()
    test_pre_speech_synthesized()
    test_hard_check_respects_progressive_name_binding()
    test_tiananmen_speaker_plan_floor_only_no_content_boost()
    test_observatory_inner_does_not_fill_toxic_unsaid()
    print("PASS")
