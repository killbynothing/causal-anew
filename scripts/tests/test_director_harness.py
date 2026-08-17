# -*- coding: utf-8 -*-
"""刀 1 导演 Harness：闭集出招 × Resolver 三层闸 × 证据先行会计（零 LLM）。

覆盖：
- director_harness：出招/裁招/闭集/复核（turns 拒收、mh hint 封顶、opportunity 合法闸、slim 提示）
- beat_evidence：RP1·RP2·RP3·TM1-4 注册表、after 顺序、隐式前置
- 软证据双向样例：RP3 托付、TM2 借视频（防假阳/防漏检）
- 生产集成：天安门无 hint 也凭可见证据走完 TM1-4；maki 假链接软闸；opportunity 落 Dramaturgy 口
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import beat_evidence, director_harness
from runtime import free_stage_prototype as proto


# ── director_harness 纯函数 ──────────────────────────────────────────────


def test_legal_moves_include_pressure_when_cap_or_clock():
    inputs = director_harness.snapshot_harness_inputs(
        spine_remaining=2,
        casual_cap=True,
        exit_clock_active=True,
        close_window_near=True,
        active_exit_state="pending_close",
    )
    moves = director_harness.legal_moves(inputs)
    assert "time_pressure" in moves
    assert "close_window" in moves


def test_legal_moves_are_closed_subset_with_quiet():
    moves = director_harness.legal_moves(director_harness.snapshot_harness_inputs())
    assert moves == ["quiet"]
    assert set(moves) <= set(director_harness.CLOSED_MOVES)


def test_adjudicate_blocks_missing_preconditions():
    calm = director_harness.snapshot_harness_inputs(
        spine_remaining=0, active_exit_state="converged"
    )
    assert director_harness.adjudicate_move("time_pressure", calm)[0] is False
    assert director_harness.adjudicate_move("close_window", calm)[0] is False
    no_barista = director_harness.snapshot_harness_inputs(
        has_barista=False, player_ordering=True
    )
    assert director_harness.adjudicate_move("ambient_extra", no_barista)[0] is False
    no_stranger = director_harness.snapshot_harness_inputs(
        has_stranger_profile=False, player_requested_stage=True
    )
    assert director_harness.adjudicate_move("admit_extra", no_stranger)[0] is False


def test_adjudicate_allows_legal_preconditions():
    inputs = director_harness.snapshot_harness_inputs(
        spine_remaining=1,
        stall=3,
        has_barista=True,
        player_ordering=True,
        has_stranger_profile=True,
        player_requested_stage=True,
        active_exit_state="pending_close",
    )
    for move in ("ambient_extra", "time_pressure", "admit_extra", "close_window"):
        assert director_harness.adjudicate_move(move, inputs)[0], move


def test_validate_harness_output_drops_director_turns():
    clean, degs, fatal = director_harness.validate_harness_output(
        {"turns": [{"speaker": "秋人", "text": "你好。", "stage": ""}], "mh_progress": []},
        allowed_mh_ids=["TM1"],
    )
    assert "turns" not in clean
    assert any(d.get("kind") == "director_turns_rejected" for d in degs)
    assert fatal == []


def test_validate_harness_output_caps_hint_and_drops_illegal():
    clean, degs, fatal = director_harness.validate_harness_output(
        {"mh_progress": ["TM3", "TM4", "BOGUS"], "director_note": "x"},
        allowed_mh_ids=["TM1", "TM2", "TM3", "TM4"],
    )
    assert clean["mh_progress"] == ["TM3"]
    assert any(
        d.get("kind") == "director_mh_hint_dropped" and d.get("id") == "BOGUS"
        for d in degs
    )
    assert fatal == []


def test_validate_harness_output_rejects_illegal_opportunity():
    _, _, fatal = director_harness.validate_harness_output(
        {"opportunity": {"kind": "explode", "visible_reason": "x"}},
        allowed_mh_ids=["TM1"],
    )
    assert fatal and "illegal move" in fatal[0]


def test_validate_harness_output_keeps_legal_opportunity_and_voice():
    clean, degs, fatal = director_harness.validate_harness_output(
        {
            "opportunity": {"kind": "time_pressure", "visible_reason": "闲聊满拍", "actor_target": ""},
            "voice": {"text": "吧台那边问要不要续杯。", "speaker": "店员"},
            "actor_decision": {"outcome": "accepted"},
        },
        allowed_mh_ids=["TM1"],
        legal_moves=["quiet", "time_pressure"],
    )
    assert clean["opportunity"]["kind"] == "time_pressure"
    assert clean["voice"]["speaker"] == "店员"
    assert clean["ambient"]["speaker"] == "店员"
    assert "续杯" in clean["ambient"]["text"]
    assert fatal == []
    assert any(d.get("kind") == "director_forbidden_key" for d in degs)


def test_validate_harness_output_drops_opportunity_outside_this_beat():
    clean, degs, fatal = director_harness.validate_harness_output(
        {"opportunity": {"kind": "time_pressure", "visible_reason": "不该压"}},
        allowed_mh_ids=["TM1"],
        legal_moves=["quiet"],
    )
    assert "opportunity" not in clean
    assert fatal == []
    assert any(d.get("kind") == "director_opportunity_not_legal" for d in degs)


def test_fold_voice_and_stage_hint_into_ambient():
    from_voice = director_harness.fold_world_skin_into_ambient(
        {"voice": {"text": "好的，美式。", "speaker": "店员"}}
    )
    assert from_voice["ambient"]["text"] == "好的，美式。"
    from_stage = director_harness.fold_world_skin_into_ambient(
        {"stage": {"active": True, "scene_hint": "雨打在窗上。"}}
    )
    assert "雨" in from_stage["ambient"]["text"]
    keep = director_harness.fold_world_skin_into_ambient(
        {
            "ambient": {"text": "留着旧场声。", "speaker": "旁白"},
            "voice": {"text": "好的，美式。", "speaker": "店员"},
        }
    )
    assert keep["ambient"]["text"] == "留着旧场声。"


def test_normalize_director_ambient_reads_voice():
    rows = proto.normalize_director_ambient(
        {"voice": {"text": "好的，一杯美式。", "speaker": "店员"}},
        turn_no=3,
    )
    assert len(rows) == 1
    assert rows[0]["speaker"] == "店员"
    assert "美式" in rows[0]["text"]


def test_build_harness_prompt_slim_no_persona_cards_no_turns():
    card = {
        "scene_id": "OPENING_TIANANMEN_002",
        "scene_frame": {"where": "北京天安门广场升旗区旁"},
        "persona_cards": {"C.akito.WMAIN": {"name": "川口秋人"}},
        "must_happen": [{"id": "TM1"}, {"id": "TM2", "after": ["TM1"]}],
    }
    prompt = json.loads(
        director_harness.build_harness_prompt(
            {
                "constraint_card": card,
                "completed_must_happen": [],
                "branch_progress": [],
                "player_input": "你好。",
                "active_exit_state": "converged",
            },
            ["quiet", "time_pressure"],
        )
    )
    body = json.dumps(prompt, ensure_ascii=False)
    assert "persona_cards" not in body
    contract = json.dumps(prompt["director_harness"]["output_contract"], ensure_ascii=False)
    assert "turns" not in contract
    assert prompt["director_harness"]["legal_moves"] == ["quiet", "time_pressure"]


# ── beat_evidence 纯函数 ─────────────────────────────────────────────────


def _ctx(**flags):
    return {
        "card": {
            "must_happen": [
                {"id": "TM1"},
                {"id": "TM2", "after": ["TM1"]},
                {"id": "TM3", "after": ["TM2"]},
                {"id": "TM4", "after": ["TM3"]},
            ]
        },
        "history": [{"role": "player", "text": "你好。"}],
        "turns": [],
        "evidence_flags": flags,
    }


def test_evidence_after_ordering_blocks_skip():
    # TM3 证据在，但 TM2 没完成、证据也不在 → TM3 被 after 顺序拦下。
    ctx = _ctx(tm3_intro=True)
    got = beat_evidence.resolve_completions(
        ctx, allowed={"TM1", "TM2", "TM3", "TM4"}, completed=set()
    )
    assert "TM3" not in got
    assert got == ["TM1"]


def test_evidence_advances_in_order():
    ctx = _ctx(tm2_visible=True)
    got = beat_evidence.resolve_completions(
        ctx, allowed={"TM1", "TM2", "TM3", "TM4"}, completed={"TM1"}
    )
    assert got == ["TM2"]


def test_implied_prereq_rp3_completes_rp2():
    ctx = _ctx(rp3_entrust=True)
    got = beat_evidence.resolve_completions(
        ctx,
        allowed={"RP1", "RP2", "RP3", "RP4"},
        completed=set(),
        after={"RP1": set(), "RP2": {"RP1"}, "RP3": {"RP2"}},
    )
    assert got == ["RP1", "RP2", "RP3"]


# ── 软证据双向样例（防假阳 / 防漏检）─────────────────────────────────────


def test_rp3_soft_evidence_bidirectional():
    positive = [
        {
            "speaker": "折原龙也",
            "role": "npc",
            "text": "以后要是碰巧遇见张尘——看着什么都能扛、其实挺累的那个——多照顾点。"
            "还有我弟弟折原修哉，天才一个，人倒是好人，嘴损点，也照应一下。"
            "还有，别把我的名字告诉他们。你得答应我，这个不能说，说了会有危险，会死人。",
            "stage": "",
        }
    ]
    assert proto.turns_cover_ryuya_entrust(positive, history=[])
    # 假阳防护：只提张尘/修哉、没有照顾/照应 + 没有禁名危险，不能算托付。
    negative = [
        {
            "speaker": "折原龙也",
            "role": "npc",
            "text": "张尘和折原修哉都挺好的，没什么大事。",
            "stage": "",
        }
    ]
    assert not proto.turns_cover_ryuya_entrust(negative, history=[])


def test_tm2_soft_evidence_bidirectional():
    positive = [
        {
            "speaker": "秋人",
            "role": "npc",
            "text": "不好意思，能不能借我们刚才录的升旗视频拷一下？",
            "stage": "",
        }
    ]
    assert proto.tiananmen_tm2_visible_evidence([], positive)
    # 假阳防护：只有语言发现、没有借视频，不能算 TM2。
    negative = [
        {
            "speaker": "坂本晴明",
            "role": "npc",
            "text": "那还真是方便呢，我也听得懂中文。",
            "stage": "",
        }
    ]
    assert not proto.tiananmen_tm2_visible_evidence([], negative)


# ── 生产集成：证据先行会计 ───────────────────────────────────────────────


def _no_hint_selftest(**kwargs):
    """包装固定自测演员：台词照给，mh 提示一律清零，验证证据先行。"""
    raw = proto.fixed_selftest_actor(**kwargs)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(payload, dict):
        payload["mh_progress"] = []
    return json.dumps(payload, ensure_ascii=False)


def test_tiananmen_evidence_advances_without_hint():
    config = {"api_key": "", "api_url": "", "model": "mock"}
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
        config=config,
        caller=_no_hint_selftest,
        autosave=False,
    )
    for text in ["你好。", "可以，视频给你们看。", "我听得懂日语。", "你看过火影忍者吗？"]:
        session.step(text)
    # 模型从不报 mh，但注册节拍仍凭可见证据全部走完。
    assert {"TM1", "TM2", "TM3", "TM4"} <= set(session.completed)


def test_maki_link_on_tiananmen_actor_line_degraded():
    def caller(**_kwargs):
        return json.dumps(
            {
                "turns": [
                    {
                        "speaker": "川口秋人",
                        "text": "真纪姐说去海族馆等我们，水母应该也很漂亮。",
                        "stage": "他像是想起了刚才那条消息。",
                    }
                ],
                "mh_progress": [],
                "director_note": "maki link",
            },
            ensure_ascii=False,
        )

    config = {"api_key": "", "api_url": "", "model": "mock"}
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
        config=config,
        caller=caller,
        autosave=False,
    )
    res = session.step("水母好漂亮。")
    assert any(
        d.get("kind") == "maki_aquarium_false_link"
        for d in res.get("degradations", [])
    )
    # 台词已被拦下：可见层不再有「真纪 → 海族馆」假链接。
    for item in res.get("history", []):
        text = str(item.get("text") or "")
        assert not ("真纪" in text and "海族馆" in text)


def test_session_lands_voice_as_visible_narrate():
    """导演只出 voice 时，店员薄声仍要进玩家可见层。"""

    def caller(*, user_content="", **kwargs):
        text = str(user_content or "")
        if "director_charter" in text or "director_harness" in text:
            return json.dumps(
                {
                    "voice": {"text": "好的，一杯美式马上好。", "speaker": "店员"},
                    "mh_progress": [],
                    "director_note": "点单",
                },
                ensure_ascii=False,
            )
        return proto.fixed_selftest_actor(user_content=text, **kwargs)

    config = {"api_key": "", "api_url": "", "model": "mock"}
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
        config=config,
        caller=caller,
        autosave=False,
    )
    res = session.step("来一杯美式。")
    surface = " ".join(str(item.get("text") or "") for item in res.get("turns") or [])
    assert "美式马上好" in surface
    assert any(item.get("speaker") == "店员" for item in res.get("turns") or [])


def test_director_opportunity_publishes_dramaturgy_port():
    config = {"api_key": "", "api_url": "", "model": "mock"}
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
        config=config,
        caller=_no_hint_selftest,
        autosave=False,
    )
    session._publish_director_opportunity(
        {"kind": "time_pressure", "visible_reason": "闲聊满拍", "actor_target": ""},
        turn_no=1,
    )
    assert any(
        t.get("port") == "Dramaturgy"
        and t.get("opportunity_kind") == "time_pressure"
        and t.get("closed_move")
        for t in session.director_port_trace
    )
    # quiet / 非法招不落 Dramaturgy 口。
    session._publish_director_opportunity({"kind": "quiet"}, turn_no=2)
    session._publish_director_opportunity({"kind": "nuke"}, turn_no=2)
    assert not any(
        t.get("opportunity_kind") in ("quiet", "nuke")
        for t in session.director_port_trace
    )


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
