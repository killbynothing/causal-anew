# -*- coding: utf-8 -*-
"""两场收口：BodyFrame 连续态 × 挂坠层 C × 天安门泄漏闸（零 LLM）。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime.free_stage_prototype import (
    FreeStageSession,
    opening_scene_secret_leak_violations,
    settle_body_frames_from_npc_turns,
    ensure_card_body_frames,
)


def _dummy_caller(**_kwargs):
    return json.dumps(
        {
            "turns": [
                {
                    "speaker": "川口秋人",
                    "text": "不好意思！",
                    "stage": "他把单反往身侧垂了一点。",
                }
            ],
            "mh_progress": [],
            "director_note": "x",
        },
        ensure_ascii=False,
    )


def test_tiananmen_body_frames_seeded():
    card = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="tm-body",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=_dummy_caller,
        )
        assert sess.body_frames
        akito = sess.body_frames.get("B.akito.WMAIN")
        assert isinstance(akito, dict)
        assert akito.get("holding") == "I.CAMERA_DSLR"
        assert akito.get("posture") == "standing"
        xiuzai = sess.body_frames.get("B.xiuzai.WMAIN")
        assert isinstance(xiuzai, dict)
        assert not xiuzai.get("holding")


def test_body_frame_settle_and_busy_hands():
    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_tiananmen_v2.json").read_text(encoding="utf-8")
    )
    frames = ensure_card_body_frames(card, {})
    body_id = "B.akito.WMAIN"
    assert frames[body_id]["holding"] == "I.CAMERA_DSLR"
    turns = [
        {
            "speaker": "川口秋人",
            "cons": "C.akito.WMAIN",
            "role": "npc",
            "text": "呃",
            "stage": "他又拿起旁边的水瓶想递过去。",
        }
    ]
    issues = settle_body_frames_from_npc_turns(frames, card, turns)
    assert issues, "busy hands should block"
    assert turns[0]["stage"] == ""
    # Legal: put camera down then record last stage
    turns2 = [
        {
            "speaker": "川口秋人",
            "cons": "C.akito.WMAIN",
            "role": "npc",
            "text": "好了",
            "stage": "他把单反放下，揉了揉手腕。",
        }
    ]
    issues2 = settle_body_frames_from_npc_turns(frames, card, turns2)
    assert not issues2
    assert frames[body_id].get("holding") is None
    assert frames[body_id].get("last_visible_stage")


def test_tiananmen_secret_leak_gate():
    card = {"scene_id": "OPENING_TIANANMEN_002"}
    bad = [{"role": "npc", "speaker": "折原修哉", "text": "龙也托付过我什么吗？", "stage": ""}]
    assert opening_scene_secret_leak_violations(bad, card)
    good = [{"role": "npc", "speaker": "折原修哉", "text": "我叫折原修哉。", "stage": "他懒洋洋摊了摊手。"}]
    assert not opening_scene_secret_leak_violations(good, card)
    assert not opening_scene_secret_leak_violations(bad, {"scene_id": "OTHER"})


def test_pendant_layer_c_emits_once():
    card = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="tm-layerc",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=_dummy_caller,
            opening_id="aline_tiananmen",
        )
        # Opening path seeds pendant accepted for entry cards with opening_id.
        sess._ensure_opening_synopsis_and_pendant()
        assert sess._pendant_accepted()
        first = sess._maybe_emit_pendant_layer_c(
            {"speech": "", "action": "摸了摸胸口的挂坠", "thought": ""},
            turn_no=1,
        )
        assert len(first) == 2
        assert any("雨声" in str(t.get("text")) for t in first)
        second = sess._maybe_emit_pendant_layer_c(
            {"speech": "这挂坠……", "action": "", "thought": ""},
            turn_no=2,
        )
        assert second == []


def test_ryuya_prologue_rp1_no_forced_entrust_in_seed_want():
    """RP1 允许心里有托付，但开场闲聊不得被写成任务清单（卡 locks 已约束）。"""
    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    locks = " ".join(str(x) for x in (card.get("locks") or []))
    assert "禁止开场宣读托付" in locks or "禁止开场宣读" in locks
    mh = {str(x.get("id")): x for x in card.get("must_happen") or [] if isinstance(x, dict)}
    assert "不急着托付" in str(mh.get("RP1", {}).get("desc") or "")


def test_observer_beat_io_projection():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        def caller(**_):
            return json.dumps(
                {
                    "turns": [
                        {
                            "speaker": "折原龙也",
                            "text": "我有点事想跟你说。",
                            "stage": "他把勺子放在杯碟边。",
                        }
                    ],
                    "mh_progress": ["RP2"],
                    "director_note": "x",
                },
                ensure_ascii=False,
            )

        sess = FreeStageSession(
            session_id="obs-beat-io",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=caller,
        )
        sess.start()
        zero = sess.initial_debug_payload()
        assert "beat_io" in zero
        assert "assembly_projection" in zero
        assert "body_frames" in zero
        assert zero["assembly_projection"]["scope"] == "opening_two_scenes"
        assert zero["assembly_projection"].get("top_tier") is True
        assert "FSM/session affect" in " ".join(zero["assembly_projection"].get("wired_now") or [])
        assert zero["body_frames"].get("B.ryuya.WMAIN", {}).get("holding") == "I.PENDANT_ANCHOR"

        out = sess.step({"speech": "嗯", "action": "", "thought": "他今天有点不一样"})
        payload = out.get("debug_payload") or (sess.debug_history[-1] if sess.debug_history else {})
        # step() without debug=True still appends debug_history
        payload = sess.debug_history[-1]
        bio = payload["beat_io"]
        assert bio["input"]["speech"] == "嗯"
        assert bio["input"]["thought"] == "他今天有点不一样"
        assert bio["displayed"]["visible_count"] >= 1
        assert "B.ryuya.WMAIN" in bio["happened"]["body_frames"]
        assert payload["assembly_projection"]["wired_now"]
        asm = payload["assembly_projection"]
        assert asm.get("top_tier") is True
        assert asm.get("deferred_not_top_tier") == []
        joined = " ".join(asm.get("wired_now") or [])
        assert "actor_context_isolation" in joined
        assert "KnowledgeGateEngine" in joined
        assert "cos+emo" in joined
        assert "fronting_canon runtime select" in joined
        assert "Storylet generate_cards overlay" in joined
        assert "β soft→director threshold" in joined
        assert sess.fsm_by_cons.get("C.ryuya.W1")
        assert sess.rel_state_by_cons.get("C.ryuya.W1")
        assert sess.card.get("_fronting_runtime") is True
        assert (sess.card.get("compiler") or {}).get("mode") == "authored_overlay"


def test_opening_isolation_forced_with_caller():
    """With a real caller, opening scenes must still use isolated actor packets."""
    card = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
    seen = {"packet": False, "calls": 0}

    def _caller(**kwargs):
        seen["calls"] += 1
        content = kwargs.get("user_content") or ""
        if "actor_context_packet" in content:
            seen["packet"] = True
        return _dummy_caller(**kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="tm-iso",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=_caller,
        )
        sess.start()
        sess.step({"speech": "你好", "action": "", "thought": ""})
        assert seen["calls"] >= 2, "director + at least one isolated actor"
        assert seen["packet"], "opening top-tier must call_actor_packet path"
        asm = sess._assembly_projection_status()
        assert asm["top_tier"] is True


if __name__ == "__main__":
    test_tiananmen_body_frames_seeded()
    test_body_frame_settle_and_busy_hands()
    test_tiananmen_secret_leak_gate()
    test_pendant_layer_c_emits_once()
    test_ryuya_prologue_rp1_no_forced_entrust_in_seed_want()
    test_observer_beat_io_projection()
    test_opening_isolation_forced_with_caller()
    print("PASS")
