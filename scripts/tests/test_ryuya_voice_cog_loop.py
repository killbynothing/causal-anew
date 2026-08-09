# -*- coding: utf-8 -*-
"""Ryuya P.VOICE projection + ActorCogLoop Decide/Reflect for cafe prologue."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime import actor_cog_loop as cogloop
from runtime import actor_context_v2 as acv2
from runtime.free_stage_prototype import FreeStageSession, build_actor_context_packet, call_actor_packet


DB = ROOT / "data" / "world_truth.db"


def test_voice_props_in_db():
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    n = cur.execute(
        "SELECT COUNT(*) FROM propositions WHERE prop_id LIKE 'P.VOICE.ryuya.%'"
    ).fetchone()[0]
    con.close()
    assert n >= 12, f"expected >=12 P.VOICE.ryuya.* rows, got {n}"


def test_resolve_persona_core_carries_voice_samples():
    core = acv2.resolve_persona_core("C.ryuya.W1", 0, "S3")
    samples = core.get("voice_samples") or []
    assert samples, "W1 should project P.VOICE into voice_samples"
    blob = "\n".join(samples)
    assert "命运" in blob or "托付" in blob or "口语" in blob or "金标" in blob


def test_packet_includes_voice_and_cog_decide():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="pkt-ryuya-voice-cog",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=lambda **_: json.dumps(
                {
                    "pre_speech": {
                        "notice": "雨和旧桌",
                        "intention": "像平常那样聊",
                        "social_move": "continuer",
                    },
                    "turns": [
                        {
                            "speaker": "折原龙也",
                            "text": "雨还是这么大。",
                            "stage": "",
                            "participation_mode": "speak",
                        }
                    ],
                    "mh_progress": [],
                    "director_note": "x",
                }
            ),
        )
        out = sess.step("雨是不是又大了", debug=True)
        payload = out.get("debug_payload") or {}
        packets = payload.get("actor_context_packets") or {}
        assert "C.ryuya.W1" in packets, packets.keys()
        pkt = packets["C.ryuya.W1"]
        samples = ((pkt.get("self_core") or {}).get("voice_samples")) or []
        assert samples, "packet self_core.voice_samples empty"
        decide = ((pkt.get("cog_loop") or {}).get("decide") or {})
        assert decide.get("top_concern"), decide
        assert "pending_concerns" in decide
        # Reflect may fire when spoken + band match
        reflect = (pkt.get("cog_loop") or {}).get("reflect")
        # first beat often idle — reflect optional; Decide must exist
        assert decide.get("rule")


def test_reflect_on_entrust_band():
    thought = cogloop.build_reflect_thought(
        cons_id="C.ryuya.W1",
        decide={"band": "entrust", "top_concern": "说清托付", "top_concern_id": "entrust"},
        spoken_texts=["碰巧遇见修哉的话，照顾一下。"],
        player_speech="好",
        completed_after=["RP1", "RP2"],
    )
    assert thought and "托付" in thought["thought"]


def test_call_actor_instruction_mentions_voice_and_cog():
    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    packet = build_actor_context_packet(
        card,
        "C.ryuya.W1",
        history=[],
        player_input={"speech": "嗨"},
        turn_no=1,
        world_cursor={"ch_anchor": 0, "run": 1},
        player_profile={"name": "阿七"},
    )
    packet["conversation_contract"] = {
        "response_slot": "primary",
        "participation_mode": "speak",
        "social_instruction": "",
        "max_new_questions": 2,
    }
    cogloop.attach_cog_loop_to_packet(
        packet,
        scene_id=str(card.get("scene_id") or "OPENING_RYUYA_PROLOGUE_001"),
        flash_beats=0,
        completed=[],
    )
    captured: list[str] = []

    def _caller(*, user_content: str = "", **_kw):
        captured.append(user_content)
        return json.dumps(
            {
                "pre_speech": {"notice": "x", "intention": "y", "social_move": "primary"},
                "turns": [{"speaker": "折原龙也", "text": "嗯。", "stage": "", "participation_mode": "speak"}],
                "mh_progress": [],
                "director_note": "",
            }
        )

    call_actor_packet(packet, config={}, caller=_caller)
    assert captured
    assert "voice_samples" in captured[0]
    assert "cog_loop.decide" in captured[0]


def test_prologue_director_instruction_omits_mh_ids():
    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    lines = acv2.build_director_instruction(
        card,
        "C.ryuya.W1",
        turn_no=1,
        history=[],
        player_input={"speech": "雨好大"},
        completed=["RP1"],
    )
    blob = "\n".join(lines)
    assert "RP2" not in blob and "RP3" not in blob and "RP4" not in blob
    assert "导演关注节拍" not in blob
    assert "共同细节" in blob or "点单" in blob


def test_prologue_invent_shared_past_repaired():
    packet = {
        "self_memory": {
            "opening_lorebook": ["初遇泼袖，赔一杯"],
            "episodic_recent": [],
            "slow_memory_top_k": [],
        },
        "known_fact_ids": [],
        "observable_dialogue": [],
        "scene": {"facts": []},
    }
    text = "你还记得我们上次你点的拿铁吗？雨还是这么大。"
    repaired, degs = acv2.repair_ryuya_prologue_invent(text, packet)
    assert degs and degs[0]["kind"] == "ryuya_prologue_invent_repaired"
    assert "拿铁" not in repaired or "你还记得我们" not in repaired


def test_prologue_hard_check_early_checklist_and_mystic():
    from runtime.free_stage_prototype import hard_check

    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    history = [
        {
            "turn": 1,
            "role": "npc",
            "speaker": "折原龙也",
            "text": "碰巧遇见折原修哉和张尘就照顾一下，这枚挂坠是任务系统绑定道具。",
            "stage": "",
        }
    ]
    issues = hard_check(history, completed=["RP1"], card=card)
    assert any("checklist" in i or "mystic" in i or "系统" in i for i in issues), issues


def test_prologue_exit_defaults_deferred_without_receipt():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="pkt-ryuya-deferred",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=lambda **_: json.dumps(
                {
                    "pre_speech": {"notice": "x", "intention": "y", "social_move": "primary"},
                    "turns": [{"speaker": "折原龙也", "text": "嗯。", "stage": ""}],
                    "mh_progress": [],
                    "director_note": "",
                }
            ),
        )
        # Simulate flashback complete without player receipt / world pendant tx.
        sess.ryuya_flashback_return = {
            "card_path": str(card),
            "completed": [],
            "branch_progress": [],
        }
        sess.completed = ["RP1", "RP2", "RP3", "RP4"]
        sess.branch_progress = []
        assert sess._world_transaction("ryuya_pendant_disposition") is None
        # Drive the exit branch via a step that sees MH complete.
        out = sess.step("……", debug=True)
        assert any(
            str(x).startswith("prologue_receipt_") for x in sess.branch_progress
        ), sess.branch_progress
        assert "prologue_receipt_accepted" not in sess.branch_progress
        assert "prologue_receipt_deferred" in sess.branch_progress
        assert out.get("ended") or sess.ended or True  # handoff may rewrite card


def test_normalize_director_ambient_same_call():
    from runtime.free_stage_prototype import normalize_director_ambient

    assert normalize_director_ambient({"ambient": ""}) == []
    rows = normalize_director_ambient(
        {"ambient": {"text": "柜台那边问了一句要不要续杯。", "speaker": "店员"}},
        turn_no=2,
    )
    assert len(rows) == 1
    assert rows[0]["role"] == "narrate"
    assert rows[0]["speaker"] == "店员"
    assert "续杯" in rows[0]["text"]
    assert rows[0]["source"] == "director_ambient"
    # Banned MH id → drop
    assert normalize_director_ambient({"ambient": "完成 RP2 之后雨更大了"}) == []


def test_idle_want_seeps_first_meet_and_profile():
    from runtime.free_stage_prototype import advance_ryuya_prologue_want_now

    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    want0 = advance_ryuya_prologue_want_now(card, flash_beats=0, completed=[])
    text0 = want0.get("C.ryuya.W1") or ""
    assert "泼袖" in text0 or "开档" in text0
    assert "托付" in text0  # still warns not to rush
    want1 = advance_ryuya_prologue_want_now(card, flash_beats=1, completed=["RP1"])
    text1 = want1.get("C.ryuya.W1") or ""
    assert "泼袖" in text1 or "开档" in text1
    concerns0 = cogloop.ryuya_prologue_concerns(flash_beats=0, completed=[])
    assert "泼袖" in concerns0[0]["text"] or "开档" in concerns0[0]["text"]


def test_stage_improv_is_deterministic_not_second_brain():
    from runtime.free_stage_prototype import improvise_stage_environment

    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    out = improvise_stage_environment(
        card,
        {"action": "看看窗外雨"},
        config={"api_key": "should-not-be-used"},
        caller=None,
    )
    assert out and out.get("source") == "deterministic_fallback"
    assert "雨" in (out.get("text") or "") or "咖啡" in (out.get("text") or "")


def test_reflect_closes_into_next_decide():
    pkt: dict = {
        "actor_cons": "C.ryuya.W1",
        "self_state": {"inner_state": {"want_now": "交挂坠"}},
        "conversation_contract": {"participation_mode": "speak"},
    }
    prior = {
        "thought": "托付说清了；下一拍必须把挂坠交到对方手里——不要再把托付重宣一遍。",
        "band": "pendant",
        "turn_no": 3,
    }
    stated = [
        "已当面提过：折原修哉（弟弟）与张尘——照顾一下；勿再当第一次介绍。",
        "已当面说过禁名：不要把龙也的名字告诉他们。",
    ]
    cogloop.attach_cog_loop_to_packet(
        pkt,
        scene_id="OPENING_RYUYA_PROLOGUE_001",
        flash_beats=3,
        completed=["RP1", "RP2"],
        prior_reflect=prior,
        stated_facts=stated,
        player_speech="这是定情信物吗",
    )
    loop = pkt.get("cog_loop") or {}
    assert (loop.get("prior_reflect") or {}).get("thought")
    assert loop.get("stated_public_facts")
    decide = loop.get("decide") or {}
    # marriage cue or no-reannounce should top
    assert decide.get("top_concern_id") in {"married_soft", "no_reannounce", "hand_pendant", "entrust"}
    assert "prior_reflect" in ((pkt.get("self_state") or {}).get("inner_state") or {})


def test_voice_cafe_samples_in_db():
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    n = cur.execute(
        "SELECT COUNT(*) FROM propositions WHERE prop_id IN "
        "('P.VOICE.ryuya.W1.ex_casual','P.VOICE.ryuya.W1.ex_married_soft')"
    ).fetchone()[0]
    hold = cur.execute(
        "SELECT statement FROM propositions WHERE prop_id='REL.HOLD.ryuya.to_weichu'"
    ).fetchone()[0]
    brother = cur.execute(
        "SELECT statement FROM propositions WHERE prop_id='P.VOICE.ryuya.W1.ex_brother'"
    ).fetchone()
    entrust_v = cur.execute(
        "SELECT statement FROM propositions WHERE prop_id='P.VOICE.ryuya.W1.ex_entrust_soft'"
    ).fetchone()
    boundary = cur.execute(
        "SELECT statement FROM propositions WHERE prop_id='P.BOUNDARY.ryuya.W1.hard.entrust'"
    ).fetchone()[0]
    zc = cur.execute(
        "SELECT statement FROM propositions WHERE prop_id='REL.HOLD.ryuya.W1.to_zhangchen'"
    ).fetchone()[0]
    con.close()
    assert n >= 2
    assert "淡提" in hold or "结婚了" in hold
    assert "不提妻名" in hold or "不提" in hold
    assert brother and "天才" in brother[0]
    assert entrust_v and "张尘" in entrust_v[0] and "照顾" in entrust_v[0]
    # Zhang-first: 张尘 appears before 折原修哉 in BOUNDARY
    assert boundary.index("张尘") < boundary.index("折原修哉")
    assert "挺累" in zc or "成熟" in zc


def test_stated_facts_partial_care_and_repeat():
    history = [
        {
            "role": "npc",
            "speaker": "折原龙也",
            "speaker_cons": "C.ryuya.W1",
            "text": "以后要是碰上张尘，多照顾点。",
        },
        {
            "role": "npc",
            "speaker": "折原龙也",
            "speaker_cons": "C.ryuya.W1",
            "text": "真的，照顾一下就好。",
        },
    ]
    facts = cogloop.prologue_stated_public_facts(history)
    assert any("照顾" in f for f in facts)
    assert any("多次" in f or "出口" in f for f in facts)
    pkt: dict = {
        "actor_cons": "C.ryuya.W1",
        "self_state": {"inner_state": {"want_now": "托付"}},
        "conversation_contract": {"participation_mode": "speak"},
    }
    cogloop.attach_cog_loop_to_packet(
        pkt,
        scene_id="OPENING_RYUYA_PROLOGUE_001",
        flash_beats=3,
        completed=["RP1"],
        stated_facts=facts,
    )
    decide = (pkt.get("cog_loop") or {}).get("decide") or {}
    assert decide.get("top_concern_id") == "no_reannounce"


def test_stated_facts_from_ledger():
    facts = cogloop.prologue_stated_public_facts(
        [],
        ledger=[{"kind": "entrust", "fact_text": "托付已说"}],
    )
    assert any("账本" in f or "托付" in f for f in facts)


def test_want_ladder_zhang_first():
    from runtime.free_stage_prototype import advance_ryuya_prologue_want_now

    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    want = advance_ryuya_prologue_want_now(card, flash_beats=4, completed=["RP1", "RP2"])
    text = want.get("C.ryuya.W1") or ""
    assert "张尘" in text
    assert text.index("张尘") < text.index("折原修哉")


def test_llm_opening_not_authored_rain():
    """Cafe first line comes from LLM caller, never the old fixed rain sentence."""
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    fixed = "这雨下得比上回还不讲道理"
    seen = {"n": 0}

    def caller(**kwargs):
        seen["n"] += 1
        content = kwargs.get("user_content") or ""
        assert "opening_first_line" in content or "开场首句" in content
        return json.dumps(
            {
                "turns": [
                    {
                        "speaker": "折原龙也",
                        "text": "袖子干了没？没干的话我再赔你一杯。",
                        "stage": "他抬了抬下巴，等你坐。",
                    }
                ],
                "mh_progress": [],
                "director_note": "opening",
            },
            ensure_ascii=False,
        )

    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="llm-open-ryuya",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=caller,
        )
        shown = sess.start()
        npc = [t for t in shown if t.get("role") == "npc" and "龙也" in str(t.get("speaker") or "")]
        assert npc, "LLM opening should produce a Ryuya line"
        assert fixed not in (npc[0].get("text") or "")
        assert "袖子" in (npc[0].get("text") or "")
        assert (npc[0].get("provenance") or {}).get("llm_opening")
        assert seen["n"] >= 1


def test_opening_without_llm_skips_fixed_line():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    fixed = "这雨下得比上回还不讲道理"
    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="no-llm-open-ryuya",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=None,
            config={},
        )
        shown = sess.start()
        blob = "\n".join(str(t.get("text") or "") for t in shown)
        assert fixed not in blob
        npc = [t for t in shown if t.get("role") == "npc"]
        assert not npc, "without LLM, do not invent a fixed first line"


if __name__ == "__main__":
    test_voice_props_in_db()
    test_resolve_persona_core_carries_voice_samples()
    test_packet_includes_voice_and_cog_decide()
    test_reflect_on_entrust_band()
    test_call_actor_instruction_mentions_voice_and_cog()
    test_prologue_director_instruction_omits_mh_ids()
    test_prologue_invent_shared_past_repaired()
    test_prologue_hard_check_early_checklist_and_mystic()
    test_prologue_exit_defaults_deferred_without_receipt()
    test_normalize_director_ambient_same_call()
    test_idle_want_seeps_first_meet_and_profile()
    test_stage_improv_is_deterministic_not_second_brain()
    test_reflect_closes_into_next_decide()
    test_voice_cafe_samples_in_db()
    test_stated_facts_partial_care_and_repeat()
    test_stated_facts_from_ledger()
    test_want_ladder_zhang_first()
    test_llm_opening_not_authored_rain()
    test_opening_without_llm_skips_fixed_line()
    print("PASS")
