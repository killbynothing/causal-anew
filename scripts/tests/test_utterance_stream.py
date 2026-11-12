# -*- coding: utf-8 -*-
"""Utterance stream (one bubble) + player thought delta ledger."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime import utterance_stream as ustream
from runtime.thought_delta import ingest_player_thought
from runtime.free_stage_prototype import FreeStageSession


def test_split_for_stream_first_rest():
    turns = [
        {"role": "npc", "speaker": "A", "text": "第一句。"},
        {"role": "npc", "speaker": "B", "text": "第二句。"},
    ]
    first, rest = ustream.split_for_stream(turns, turn_no=3)
    assert first is not None
    assert first["text"] == "第一句。"
    assert len(rest) == 1
    assert rest[0]["text"] == "第二句。"


def test_stream_status_hold_blocks_advance():
    q = [{"role": "npc", "text": "x"}]
    st = ustream.stream_status(q, hold=True, generation=1)
    assert st["queue_remaining"] == 1
    assert st["can_advance"] is False


def test_ingest_player_thought_realization():
    ledger, deltas = ingest_player_thought(
        "原来龙也托付的不是普通项链。",
        ledger=[],
        turn=2,
        scene_id="OPENING_TIANANMEN_002",
    )
    assert ledger
    assert any(d.get("kind") == "player_realization" for d in deltas)


def test_ingest_player_thought_weighted_person():
    ledger, deltas = ingest_player_thought(
        "修哉刚才那句话有点可疑。",
        ledger=[],
        turn=1,
    )
    kinds = {d.get("kind") for d in deltas}
    assert "xiuzai" in kinds or any("修哉" in str(x.get("fact_text", "")) for x in ledger)


def test_session_emits_same_speaker_composite_turns(tmp_path):
    sid = "same-speaker-stream-test"
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    session = FreeStageSession(
        session_id=sid,
        state_dir=str(state_dir),
        autosave=False,
        load_existing=False,
    )
    raw_turns = [
        {"role": "npc", "speaker": "折原龙也", "cons": "C.ryuya.W1", "text": "不记得就算了。", "stage": "抹开雾"},
        {"role": "npc", "speaker": "折原龙也", "cons": "C.ryuya.W1", "text": "说正经的，有件事拜托你。", "stage": "停在桌沿"},
        {"role": "npc", "speaker": "川口秋人", "cons": "C.akito.WMAIN", "text": "我也在听。"},
    ]
    emitted = []
    shown = session._push_stream_turns(raw_turns, turn_no=1, emitted=emitted)
    # The same leading speaker's composite turns are emitted together
    assert len(shown) == 2
    assert shown[0]["text"] == "不记得就算了。"
    assert shown[1]["text"] == "说正经的，有件事拜托你。"
    # The second speaker is placed into the pending queue
    assert len(session.utterance_pending_queue) == 1
    assert session.utterance_pending_queue[0]["speaker"] == "川口秋人"


def test_session_advance_utterance_drains_queue(tmp_path):
    sid = "stream-test"
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    session = FreeStageSession(
        session_id=sid,
        state_dir=str(state_dir),
        autosave=False,
        load_existing=False,
    )
    session.utterance_pending_queue = [
        {"role": "npc", "speaker": "测试", "text": "queued", "turn": 1},
    ]
    res = session.advance_utterance()
    assert len(res["turns"]) == 1
    assert res["turns"][0]["text"] == "queued"
    assert res["stream"]["queue_remaining"] == 0


def test_session_barge_in_clears_queue(tmp_path):
    sid = "barge-test"
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    session = FreeStageSession(
        session_id=sid,
        state_dir=str(state_dir),
        autosave=False,
        load_existing=False,
    )
    session.utterance_pending_queue = [{"role": "npc", "text": "cut", "turn": 1}]
    gen = session.stream_generation
    session._barge_in_stream()
    assert session.utterance_pending_queue == []
    assert session.stream_generation == gen + 1
