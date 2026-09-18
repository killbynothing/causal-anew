# -*- coding: utf-8 -*-
"""Observer seven-slot projection: always seven keys, no actor-loop rewrite."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.agent_module_slots import SLOT_KEYS, project_agent_modules


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
                },
                "spoken_this_turn": [{"text": "这雨下得没完。"}],
                "memory_activation": {"slow_memory_activated": [{"text": "初遇泼袖"}]},
                "persona": {"name": "折原龙也"},
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


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
