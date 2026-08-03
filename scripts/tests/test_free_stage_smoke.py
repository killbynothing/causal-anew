# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto


def test_selftest_pipeline_covers_must_happen_and_hard_checks():
    config = {"api_key": "", "api_url": "", "model": "mock"}
    result = proto.run_session(
        ["你好。", "可以，视频给你们看。", "我听得懂日语。", "你们叫什么？", "你看过火影忍者吗？", "好啊，去海洋馆看看。"],
        config,
        caller=proto.fixed_selftest_actor,
        card_path=ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
    )
    # run_session follows the accepted invitation into the target card; the
    # source-card receipts remain available by card rather than being erased.
    assert ["TM1", "TM2", "TM3", "TM4"] in result["completed_by_card"].values()
    assert result["issues"] == []
    assert any(proto.END_MARKER in item.get("text", "") for item in result["history"])


def test_hard_check_catches_pre_intro_name_and_continue_leak():
    history = [
        {"role": "npc", "speaker": "秋人", "text": "卡卡西，我们继续吧。", "stage": "", "turn": 1},
        {"role": "director_note", "speaker": "导演暗注", "text": "无", "mh_progress": [], "turn": 1},
    ]
    issues = proto.hard_check(history, completed=["MH1", "MH2", "MH3", "MH4"])
    assert any("pre-intro real name" in item for item in issues)
    assert any("continue token" in item for item in issues)


def test_pre_intro_redaction_covers_speaker_name():
    turns = [
        {"speaker": "川口秋人", "text": "早上多亏你借升旗视频。", "stage": "折原修哉坐在旁边。"},
    ]
    fixed = proto.redact_pre_intro(turns, intro_done=False)
    surface = json.dumps(fixed, ensure_ascii=False)
    assert "川口秋人" not in surface
    assert "折原修哉" not in surface
    assert fixed[0]["speaker"] == "圆脸青年"


def test_hard_check_rejects_kakashi_visible_japanese_leak():
    history = [
        {"role": "npc", "speaker": "坂本晴明", "text": "まあ、僕は気にしませんよ。", "stage": "", "turn": 1},
    ]
    issues = proto.hard_check(history, completed=["MH1", "MH2", "MH3", "MH4"])
    assert any("kakashi visible surface leaked Japanese" in item for item in issues)


def test_hard_check_allows_kakashi_chinese_surface():
    history = [
        {
            "role": "npc",
            "speaker": "坂本晴明",
            "text": "别着急，只是顺手而已。",
            "stage": "",
            "turn": 1,
            "lang": "ja",
            "original_text": "慌てなくていい。",
        },
    ]
    issues = proto.hard_check(history, completed=["MH1", "MH2", "MH3", "MH4"])
    assert not any("leaked Japanese" in item for item in issues)
    assert not any("kakashi dialogue is not Japanese" in item for item in issues)


def test_hard_check_catches_descriptor_intro_names():
    history = [
        {"role": "npc", "speaker": "秋人", "text": "我是圆脸青年，这位是懒散青年。", "stage": "", "turn": 1},
        {"role": "director_note", "speaker": "导演暗注", "text": "介绍完成", "mh_progress": ["MH2"], "turn": 1},
    ]
    issues = proto.hard_check(history, completed=["MH1", "MH2", "MH3", "MH4"])
    assert any("descriptor used as introduced name" in item for item in issues)


def test_tiananmen_descriptor_names_allowed_until_t3_intro():
    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    before_t3 = [
        {"role": "npc", "speaker": "圆脸青年", "text": "我和旁边那个懒散青年想借一下视频。", "stage": "", "turn": 1},
        {"role": "director_note", "speaker": "导演暗注", "text": "借视频", "mh_progress": ["TM2"], "turn": 1},
    ]
    issues = proto.hard_check(before_t3, completed=["TM1", "TM2"], card=card)
    assert not any("descriptor used as introduced name" in item for item in issues)

    after_t3 = before_t3 + [
        {"role": "npc", "speaker": "圆脸青年", "text": "我是圆脸青年。", "stage": "", "turn": 2},
        {"role": "director_note", "speaker": "导演暗注", "text": "介绍", "mh_progress": ["TM3"], "turn": 2},
    ]
    issues = proto.hard_check(after_t3, completed=["TM1", "TM2", "TM3"], card=card)
    assert any("descriptor used as introduced name" in item for item in issues)


def test_actor_error_survives_hard_check_issues():
    def broken_actor(**kw):
        raise RuntimeError("contract failed loudly")

    session = proto.FreeStageSession(
        session_id="actor-error-test",
        config={"api_key": "", "api_url": "", "model": "mock"},
        caller=broken_actor,
        autosave=False,
    )
    res = session.step("你好。")
    assert any("contract failed loudly" in item for item in res["issues"])


def test_config_experiment_keeps_dsv4flash_without_copying_key():
    exp_path = ROOT / "c1_web_console" / "config_experiment.json"
    payload = json.loads(exp_path.read_text(encoding="utf-8"))
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["api_url"] == "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
    assert payload.get("chat_request_options") == {"thinking": {"type": "disabled"}}
    assert "api_key" not in payload


def test_live_play_config_pins_volc_coding_plan_without_thinking():
    cfg, mode = proto.load_config()
    assert mode in {"base_config", "experiment_config"}
    assert cfg.get("model") == "deepseek-v4-flash"
    assert cfg.get("api_url") == "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
    assert proto.chat_request_options(cfg) == {"thinking": {"type": "disabled"}}
    # Key may be present locally; never assert its value in tests.
    assert "api_key" in cfg


def test_real_actor_allows_empty_mh_progress_when_scene_can_pause():
    from c1_web_console import llm_transport

    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    prompt = proto.build_prompt(
        card=card,
        history=[],
        player_input="你好。",
        completed=[],
        stall=0,
    )
    calls = []
    old_post = llm_transport.post_json_with_retry

    def fake_post_json(api_url, api_key, body, attempt_plan):
        calls.append(body)
        content = {
            "turns": [{"speaker": "秋人", "text": "你好。", "stage": "他先看了看你，语气并不急。"}],
            "mh_progress": [],
            "director_note": "秋人先接住了招呼。",
        }
        return {
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]
        }, {"ok": True}

    try:
        llm_transport.post_json_with_retry = fake_post_json
        payload = proto.call_actor(
            prompt,
            {"api_key": "k", "api_url": "u", "model": "m"},
            caller=None,
        )
    finally:
        llm_transport.post_json_with_retry = old_post

    assert payload["mh_progress"] == []
    assert len(calls) == 1
    assert calls[0]["max_tokens"] >= 2000


def test_real_actor_retries_when_progress_skips_next_must():
    from c1_web_console import llm_transport

    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    prompt = proto.build_prompt(
        card=card,
        history=[],
        player_input="好啊，去看看吧。",
        completed=[],
        stall=0,
    )
    calls = []
    old_post = llm_transport.post_json_with_retry

    def fake_post_json(api_url, api_key, body, attempt_plan):
        calls.append(body)
        if len(calls) == 1:
            content = {
                "turns": [{"speaker": "川口秋人", "text": "我叫川口秋人，我们去咖啡厅吧。", "stage": "他先把相机往肩上一甩。"}],
                "mh_progress": ["TM3", "TM4"],
                "director_note": "skipped",
            }
        else:
            assert "如果推进，只能推进 1 个，而且必须是剩余列表中的第一个" in body["messages"][-1]["content"]
            content = {
                "turns": [{"speaker": "圆脸青年", "text": "能不能借我们看一下你刚才的升旗视频？", "stage": "他把语气放轻了一点。"}],
                "mh_progress": ["TM1"],
                "director_note": "fixed order",
            }
        return {
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]
        }, {"ok": True}

    try:
        llm_transport.post_json_with_retry = fake_post_json
        payload = proto.call_actor(
            prompt,
            {"api_key": "k", "api_url": "u", "model": "m"},
            caller=None,
        )
    finally:
        llm_transport.post_json_with_retry = old_post

    assert payload["mh_progress"] == ["TM1"]
    assert len(calls) == 2


def test_real_actor_retries_user_visible_continue_token():
    from c1_web_console import llm_transport

    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    prompt = proto.build_prompt(
        card=card,
        history=[],
        player_input="你好。",
        completed=[],
        stall=0,
    )
    calls = []
    old_post = llm_transport.post_json_with_retry

    def fake_post_json(api_url, api_key, body, attempt_plan):
        calls.append(body)
        if len(calls) == 1:
            content = {
                "turns": [{"speaker": "秋人", "text": "我们继续往下聊。", "stage": "他又看了一眼你手里的手机。"}],
                "mh_progress": ["TM1"],
                "director_note": "bad token",
            }
        else:
            assert "用户可见台词" in body["messages"][-1]["content"]
            content = {
                "turns": [{"speaker": "秋人", "text": "刚才升旗那段视频，多亏你肯借我们看。", "stage": "他先把话题拢回了早上的事。"}],
                "mh_progress": ["TM1"],
                "director_note": "fixed token",
            }
        return {
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]
        }, {"ok": True}

    try:
        llm_transport.post_json_with_retry = fake_post_json
        payload = proto.call_actor(
            prompt,
            {"api_key": "k", "api_url": "u", "model": "m"},
            caller=None,
        )
    finally:
        llm_transport.post_json_with_retry = old_post

    assert payload["mh_progress"] == ["TM1"]
    assert len(calls) == 2


def test_real_actor_retries_false_maki_aquarium_route():
    from c1_web_console import llm_transport

    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    prompt = proto.build_prompt(
        card=card,
        history=[],
        player_input="水母好漂亮。",
        completed=["TM1", "TM2", "TM3"],
        stall=0,
    )
    calls = []
    old_post = llm_transport.post_json_with_retry

    def fake_post_json(api_url, api_key, body, attempt_plan):
        calls.append(body)
        if len(calls) == 1:
            content = {
                "turns": [{"speaker": "川口秋人", "text": "真纪姐说去海族馆等我们，水母应该也很漂亮。", "stage": "他像是想起了刚才那条消息。"}],
                "mh_progress": ["TM4"],
                "director_note": "bad maki aquarium link",
            }
        else:
            assert "不是真纪指示" in body["messages"][-1]["content"]
            content = {
                "turns": [{"speaker": "川口秋人", "text": "真纪姐还没回，我们自己去有动物看的地方转转吧。", "stage": "他朝人群散去的方向看了看。"}],
                "mh_progress": ["TM4"],
                "director_note": "fixed maki aquarium link",
            }
        return {
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]
        }, {"ok": True}

    try:
        llm_transport.post_json_with_retry = fake_post_json
        payload = proto.call_actor(
            prompt,
            {"api_key": "k", "api_url": "u", "model": "m"},
            caller=None,
        )
    finally:
        llm_transport.post_json_with_retry = old_post

    assert payload["mh_progress"] == ["TM4"]
    assert len(calls) == 2


def test_real_actor_retries_descriptor_names_on_intro_progress():
    from c1_web_console import llm_transport

    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    prompt = proto.build_prompt(
        card=card,
        history=[],
        player_input="你们叫什么？",
        completed=["TM1", "TM2"],
        stall=0,
    )
    calls = []
    old_post = llm_transport.post_json_with_retry

    def fake_post_json(api_url, api_key, body, attempt_plan):
        calls.append(body)
        if len(calls) == 1:
            content = {
                "turns": [{"speaker": "圆脸青年", "text": "我是圆脸青年，这位是懒散青年。", "stage": "他先抬手点了点自己。"}],
                "mh_progress": ["TM3"],
                "director_note": "bad intro",
            }
        else:
            repair_text = body["messages"][-1]["content"]
            for name in proto.intro_descriptor_names():
                assert name in repair_text
            content = {
                "turns": [{"speaker": "川口秋人", "text": "其实我叫川口秋人。这两位是坂本晴明和折原修哉。", "stage": "他顺势把另外两人也介绍了出来。"}],
                "mh_progress": ["TM3"],
                "director_note": "fixed intro",
            }
        return {
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]
        }, {"ok": True}

    try:
        llm_transport.post_json_with_retry = fake_post_json
        payload = proto.call_actor(
            prompt,
            {"api_key": "k", "api_url": "u", "model": "m"},
            caller=None,
        )
    finally:
        llm_transport.post_json_with_retry = old_post

    assert payload["mh_progress"] == ["TM3"]
    assert len(calls) == 2


def test_no_immediate_transition_without_intent():
    config = {"api_key": "", "api_url": "", "model": "mock"}
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
        config=config,
        caller=proto.fixed_selftest_actor,
        autosave=False
    )
    
    # 1. Turn 1 (completes TM1)
    res = session.step("你好。")
    assert "TM1" in res["completed"]
    assert len(res["completed"]) == 1
    assert not res["ended"]
    
    # 2. Turn 2 (completes TM2)
    res = session.step("可以，视频给你们看。")
    assert "TM2" in res["completed"]
    assert len(res["completed"]) == 2
    assert not res["ended"]
    
    # 3. Turn 3: language receipt, then TM3 can introduce names.
    res = session.step("我听得懂日语。")
    assert "TM3" in res["completed"]
    assert len(res["completed"]) == 3
    assert not res["ended"]
    
    # 4. Turn 4 (completes TM4)
    res = session.step("你看过火影忍者吗？")
    assert "TM4" in res["completed"]
    assert len(res["completed"]) == 4
    assert not res["ended"]
    
    # 5. The optional Naruto topic does not add another required beat; the
    # next unrelated line is already the first post-beat chat turn.
    res = session.step("继续聊聊")
    assert session.stall == 1
    assert session.card.get("scene_id") == "OPENING_TIANANMEN_002"

    # 6. Turn 6 (2nd turn of chatting after MH complete) -> stall becomes 2
    res = session.step("聊火影")
    assert session.stall == 2
    assert session.card.get("scene_id") == "OPENING_TIANANMEN_002"
    
    # 7. Turn 7 (3rd turn of chatting after MH complete) -> stall becomes 3
    res = session.step("再聊一拍")
    assert session.stall == 3
    assert session.card.get("scene_id") == "OPENING_TIANANMEN_002"
    
    # 8. Turn 8: a real同行承诺，而不是泛泛的“走吧”。
    res = session.step("走吧，我们一起去海洋馆。")
    # Transition happened!
    assert res["transition"]["source_scene_id"] == "OPENING_TIANANMEN_002"
    assert res["transition"]["target_scene_id"] == "OPENING_AQUARIUM_001"
    assert session.card.get("scene_id") == "OPENING_AQUARIUM_001"


def test_fallback_clock_transition_on_stall():
    config = {"api_key": "", "api_url": "", "model": "mock"}
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_tiananmen_v2.json",
        config=config,
        caller=proto.fixed_selftest_actor,
        autosave=False
    )
    
    # Complete the authored Tiananmen beats; optional Naruto talk is not one.
    session.step("你好。")
    session.step("可以，视频给你们看。")
    session.step("我听得懂日语。")
    session.step("你们叫什么？")
    session.step("你看过火影忍者吗？")
    session.step("这里风真大。")
    
    assert len(session.completed) == len(proto.card_must_happen_ids(session.card))
    
    # Chatting may make characters react, but cannot move the player.
    session.step("聊1") # stall = 1
    session.step("聊2") # stall = 2
    session.step("聊3") # stall = 3
    res = session.step("聊4")
    
    assert "transition" not in res
    assert session.card.get("scene_id") == "OPENING_TIANANMEN_002"


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
