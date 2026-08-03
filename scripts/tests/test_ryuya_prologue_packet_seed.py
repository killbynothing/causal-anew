# -*- coding: utf-8 -*-
"""Ryuya prologue packet: BodyFrame + authored slow_memory + want/托付 memory."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "runtime")]

from runtime.free_stage_prototype import FreeStageSession, build_actor_context_packet


def test_ryuya_prologue_packet_has_want_memory_bodyframe_slow():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        sess = FreeStageSession(
            session_id="pkt-ryuya-assert",
            card_path=card,
            state_dir=Path(tmp) / "s",
            runtime_state_path=Path(tmp) / "r.db",
            load_existing=False,
            autosave=False,
            caller=lambda **_: json.dumps({"turns": [], "mh_progress": [], "director_note": "x"}),
        )
        assert sess.body_frames, "session should seed BodyFrame on open"
        frame = sess.body_frames.get("B.ryuya.WMAIN")
        assert isinstance(frame, dict)
        assert frame.get("holding") == "I.PENDANT_ANCHOR"
        assert frame.get("posture") == "seated"

        packet = build_actor_context_packet(
            sess.card,
            "C.ryuya.W1",
            history=[],
            player_input={"speech": "你好"},
            turn_no=1,
            world_cursor={"ch_anchor": 0, "run": 1},
            player_profile={"name": "阿七"},
        )
        want = ((packet.get("self_state") or {}).get("inner_state") or {}).get("want_now") or ""
        assert "托付" in want or "挂坠" in want
        rel = (packet.get("self_memory") or {}).get("relationship_memory") or []
        assert len(rel) >= 3
        assert any("折原修哉" in str(x) for x in rel)
        bf = packet.get("body_frame_now") or (packet.get("self_state") or {}).get("body_frame_now")
        assert isinstance(bf, dict)
        assert bf.get("holding") == "I.PENDANT_ANCHOR"
        slow_cands = (packet.get("memory_activation") or {}).get("slow_memory_candidates") or []
        assert any(int(x.get("mem_id") or 0) == 12 for x in slow_cands), slow_cands
        slow_act = (packet.get("memory_activation") or {}).get("slow_memory_activated") or []
        assert any(int(x.get("mem_id") or 0) == 12 for x in slow_act), slow_act


if __name__ == "__main__":
    test_ryuya_prologue_packet_has_want_memory_bodyframe_slow()
    print("PASS")
