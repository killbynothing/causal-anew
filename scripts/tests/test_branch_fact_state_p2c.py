#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime.causal_protocol import RuntimeScope
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT, WorldCommitState


def _scope():
    return RuntimeScope(
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="p2c-branch",
        scene_instance_id="S1:visit:1",
    )


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_branch_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_legacy_branch_snapshot_does_not_fabricate_provenance():
    state = WorldCommitState.from_legacy({"branch_progress": ["legacy-a", "legacy-b"]})
    assert state.branch_progress_view() == ["legacy-a", "legacy-b"]
    assert state.branch_fact_events_view() == []


def test_branch_assert_retract_are_append_only_events():
    state = WorldCommitState()
    assert state.assert_branch_fact(
        scope=_scope(),
        request_id="req:a",
        fact_id="route-a",
        source_kind="player_branch",
        owner="player",
        scene_id="S1",
        turn=2,
        source_refs=("player:r1",),
    ) is True
    assert state.assert_branch_fact(
        scope=_scope(),
        request_id="req:a",
        fact_id="route-a",
        source_kind="player_branch",
        owner="player",
        scene_id="S1",
        turn=2,
        source_refs=("player:r1",),
    ) is False
    assert state.branch_progress_view() == ["route-a"]

    assert state.retract_branch_fact(
        scope=_scope(),
        request_id="req:switch",
        fact_id="route-a",
        source_kind="exclusive_switch",
        owner="player",
        scene_id="S1",
        turn=3,
    ) is True
    assert state.branch_progress_view() == []
    events = state.branch_fact_events_view()
    assert [row["operation"] for row in events] == ["assert", "retract"]
    assert all(row["schema_version"] == "free_stage.branch_fact.v1" for row in events)
    assert all(row["receipt"]["producer"] == "WorldCommit.BranchFact" for row in events)


def test_branch_views_are_copy_only():
    state = WorldCommitState(branch_progress=["a"])
    leaked = state.branch_progress_view()
    leaked.append("evil")
    assert state.branch_progress_view() == ["a"]


def test_player_branch_links_player_action_to_branch_receipt_and_roundtrips():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-branch-session",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._record_player_branch_fact(
            "route_left", turn_no=1, player_input="走左边"
        ) is True
        action_id = "branch:route_left:turn:1"
        action = session.player_action_receipts[action_id]
        assert session.branch_progress == ["route_left"]
        events = session.branch_fact_events
        assert len(events) == 1
        assert events[0]["fact_id"] == "route_left"
        assert events[0]["receipt"]["source_refs"] == [action["receipt"]["receipt_id"]]

        leaked = session.branch_progress
        leaked.append("evil")
        assert session.branch_progress == ["route_left"]
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-branch-session",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.branch_progress == ["route_left"]
        assert resumed.branch_fact_events == events
        assert resumed._record_player_branch_fact(
            "route_left", turn_no=1, player_input="走左边"
        ) is False
        assert resumed.branch_fact_events == events


def test_runtime_retraction_keeps_history():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-branch-retract",
            state_dir=Path(tmp) / "states",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._assert_branch_fact("a", turn_no=1, source_kind="fixture")
        session._assert_branch_fact("b", turn_no=1, source_kind="fixture")
        removed = session._retract_branch_facts(
            {"a", "missing"},
            turn_no=2,
            source_kind="fixture_switch",
        )
        assert removed == ["a"]
        assert session.branch_progress == ["b"]
        assert [row["operation"] for row in session.branch_fact_events] == [
            "assert", "assert", "retract"
        ]


def test_authority_map_zeroes_branch_progress_writers_and_world_debt():
    report = _audit()
    rows = [
        row for row in report["facts"]["branch_progress"]["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert rows == [], rows
    assert P2A_WORLD_MIGRATION_DEBT == ()


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
