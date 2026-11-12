# -*- coding: utf-8 -*-
"""Observer seven-slot projection: always seven keys, no actor-loop rewrite."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.agent_module_slots import SLOT_KEYS, project_agent_modules
from runtime.actor_mind import build_actor_mind, observer_state_projection


def test_empty_payload_still_seven_keys():
    slots = project_agent_modules({})
    assert tuple(slots) == SLOT_KEYS
    for key in SLOT_KEYS:
        assert "filled" in slots[key]
        assert slots[key]["summary"]


def test_filled_from_debug_shape():
    payload = {
        "world_cursor": {"run": 2, "ch_anchor": 0},
        "must_happen_progress": {"completed": ["RP1"]},
        "director_port_trace": [{"opportunity_kind": "ambient_extra"}],
        "private_reflections": [{"cons_id": "C.ryuya.W1", "thought": "别急着托付"}],
        "actor_context_packets": {
            "C.ryuya.W1": {
                "cog_loop": {
                    "decide": {"top_concern": "接住对方", "intention": "闲聊", "band": "idle"},
                    "reflect": {"thought": "别急着托付"},
                    "pacing_signal": {"mode": "hold"},
                },
                "spoken_this_turn": [{"text": "这雨下得没完。"}],
                "memory_activation": {"slow_memory_activated": [{"text": "初遇泼袖"}]},
                "persona": {"name": "折原龙也"},
            }
        },
        "actor_state": {
            "C.ryuya.W1": {
                "authority": "actor_mind",
                "persistent": {"receipt_count": 2},
                "working_context": {"attention_target": "player"},
                "decide": {"top_concern": "接住对方"},
            }
        },
    }
    slots = project_agent_modules(payload)
    assert slots["Planning"]["filled"] is True
    assert "接住" in slots["Planning"]["summary"]
    assert slots["Memory"]["filled"] is True
    assert slots["Tool Use"]["filled"] is True
    assert "这雨" in slots["Action"]["summary"]
    assert slots["Reflection"]["filled"] is True
    assert slots["Persona"]["filled"] is True
    assert "run=2" in slots["State Tracking"]["summary"]
    assert "mind=actor_mind" in slots["State Tracking"]["summary"]
    assert "pace=hold" in slots["State Tracking"]["summary"]


def test_filled_from_modern_context_assembly_packet():
    payload = {
        "world_cursor": {"run": 1, "ch_anchor": 0},
        "must_happen_progress": {"completed": ["RP1", "RP2"]},
        "actor_context_packets": {
            "C.ryuya.W1": {
                "self_core": {
                    "name": "折原龙也",
                    "seed_manners": ["口语自然", "熟络抬杠"],
                    "seed_boundaries": ["不得泄露后续因果"],
                    "voice_samples": ["不是清单。碰巧遇见张尘……"],
                },
                "self_memory": {
                    "slow_memory": [{"text": "初遇泼袖"}],
                    "episodic_recent": [{"text": "雨中旧桌"}],
                },
                "relevant_knowledge_top_k": [{"prop_id": "P.TEST"}],
                "identity_relations": [{"prop_id": "REL.IDENTITY.ryuya.to_player"}],
                "self_state": {
                    "inner_state": {"want_now": "说清托付", "top_concern": "托付与禁名"},
                    "body_frame_now": {"holding": "挂坠"},
                },
                "conversation_contract": {
                    "response_slot": "primary",
                    "participation_mode": "speak",
                },
                "cog_loop": {
                    "decide": {"top_concern": "托付与禁名", "band": "entrust"},
                    "reflect": {"thought": "托付已说清"},
                    "pacing_signal": {"mode": "normal"},
                },
                "spoken_this_turn": [{"text": "说正经的，帮我照应张尘。", "stage": "收回手"}],
            }
        },
    }
    slots = project_agent_modules(payload)
    assert slots["Planning"]["filled"] is True
    assert "托付" in slots["Planning"]["summary"]
    assert slots["Memory"]["filled"] is True
    assert "慢环" in slots["Memory"]["summary"]
    assert "正典K" in slots["Memory"]["summary"]
    assert slots["Tool Use"]["filled"] is True
    assert "primary" in slots["Tool Use"]["summary"]
    assert slots["Action"]["filled"] is True
    assert "照应" in slots["Action"]["summary"]
    assert slots["Reflection"]["filled"] is True
    assert "说清" in slots["Reflection"]["summary"]
    assert slots["Persona"]["filled"] is True
    assert "折原龙也" in slots["Persona"]["summary"]
    assert "MANNER" in slots["Persona"]["summary"]
    assert slots["State Tracking"]["filled"] is True
    assert "持物=挂坠" in slots["State Tracking"]["summary"]


def test_actor_state_projection_has_one_authority():
    mind = build_actor_mind(
        "C.ryuya.W1",
        {"inner_state": {"want_now": "临走前有件事", "stance_to_player": "熟人"}},
    )
    projected = observer_state_projection(
        mind,
        working_context={"attention_target": "player", "appraisal": "不应成为第二状态源"},
        decide={"top_concern_id": "banter", "top_concern": "先接住对方", "band": "idle"},
    )
    assert projected["authority"] == "actor_mind"
    assert projected["persistent"]["actor_cons"] == "C.ryuya.W1"
    assert projected["working_context"]["attention_target"] == "player"
    assert "appraisal" not in projected["working_context"]
    assert projected["decide"]["top_concern_id"] == "banter"


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
