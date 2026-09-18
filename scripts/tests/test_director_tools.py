# -*- coding: utf-8 -*-
"""Director closed moves as Function Calling: schema + illegal call reject."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.director_harness import CLOSED_MOVES, snapshot_harness_inputs
from runtime import director_tools as tools


def test_list_tools_closed_and_filtered():
    all_tools = tools.list_tools()
    names = [t["function"]["name"] for t in all_tools]
    assert names == list(CLOSED_MOVES)
    quiet_only = tools.list_tools(["quiet"])
    assert [t["function"]["name"] for t in quiet_only] == ["quiet"]


def test_reject_unknown_tool_name():
    got = tools.parse_tool_call({"name": "explode", "arguments": {}})
    assert got["ok"] is False
    assert "illegal move" in got["reason"]


def test_reject_not_legal_this_beat():
    inputs = snapshot_harness_inputs(has_barista=True, player_ordering=True)
    got = tools.parse_tool_call(
        {"name": "ambient_extra", "arguments": {"visible_reason": "点了美式"}},
        legal_moves=["quiet"],
        harness_inputs=inputs,
    )
    assert got["ok"] is False
    assert "legal_moves" in got["reason"]


def test_reject_missing_precondition():
    inputs = snapshot_harness_inputs(has_barista=False)
    got = tools.parse_tool_call(
        {"name": "ambient_extra", "arguments": {"visible_reason": "点了美式"}},
        legal_moves=["quiet", "ambient_extra"],
        harness_inputs=inputs,
    )
    assert got["ok"] is False
    assert "barista" in got["reason"]


def test_reject_extra_fields():
    got = tools.parse_tool_call(
        {"name": "quiet", "arguments": {"nuke": True}},
        legal_moves=["quiet"],
        harness_inputs=snapshot_harness_inputs(),
    )
    assert got["ok"] is False
    assert "extra" in got["reason"]


def test_accept_legal_ambient():
    inputs = snapshot_harness_inputs(has_barista=True, player_ordering=True)
    got = tools.parse_tool_call(
        {
            "type": "function",
            "function": {
                "name": "ambient_extra",
                "arguments": '{"visible_reason":"点了美式","speaker":"店员","text":"美式，好。"}',
            },
        },
        legal_moves=["quiet", "ambient_extra"],
        harness_inputs=inputs,
    )
    assert got["ok"] is True, got
    assert got["name"] == "ambient_extra"
    assert got["arguments"]["speaker"] == "店员"


def test_opportunity_roundtrip_quiet():
    call = tools.opportunity_to_tool_call(None)
    got = tools.parse_tool_call(call, legal_moves=["quiet"], harness_inputs=snapshot_harness_inputs())
    assert got["ok"] is True
    assert got["name"] == "quiet"


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
