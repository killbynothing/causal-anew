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
