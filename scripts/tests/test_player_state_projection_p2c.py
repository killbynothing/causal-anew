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
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT
from runtime.world_projection import PENDANT_PROP, WorldProjectionState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_player_state_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_player_state_view_is_copy_only_and_defaults_are_owned():
    state = WorldProjectionState()
    view = state.player_state_view()
    assert view["convergence_rate"] == 100
    assert view["elapsed_minutes"] == 0
    view["injury"] = "EVIL"
    assert state.player_state_view()["injury"] == "正常/良好"


def test_player_state_updates_preserve_requested_fields():
    state = WorldProjectionState(player_state={"elapsed_minutes": 8, "injury": "ok"})
    state.update_player_fields(
        {"elapsed_minutes": 999, "injury": "hurt", "status": "offscreen"},
        preserve=("elapsed_minutes",),
    )
    view = state.player_state_view()
    assert view["elapsed_minutes"] == 8
    assert view["injury"] == "hurt"
    assert view["status"] == "offscreen"
    assert state.advance_elapsed(2) == 10
    assert state.reduce_convergence(10) == 90


def test_pendant_projection_updates_owned_player_state():
    from runtime.causal_protocol import RuntimeScope
    from runtime.world_commit import commit_world_fact

    ledger = {}
    tx = commit_world_fact(
        ledger,
        scope=RuntimeScope(
            worldline="WMAIN", run=1, ch_anchor=1,
            session_id="p2c-player", scene_instance_id="S1:visit:1",
        ),
        request_id="req:pendant",
        turn_id="turn:1",
        transaction_id="ryuya_pendant_disposition",
        kind="item_disposition",
        outcome="accepted",
        owner="player",
        scene_id="S1",
        turn=1,
        public_effect="pendant_transferred_to_player",
    ).record
    state = WorldProjectionState()
    state.apply_world_transaction(tx, session_id="p2c-player")
    assert PENDANT_PROP in state.player_state_view()["body_props"]


def test_session_player_state_roundtrip_is_copy_only():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-player-state",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._world_projection_state.advance_elapsed(6)
        session._world_projection_state.set_player_field("injury", "测试伤势")
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-player-state",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.player_state["elapsed_minutes"] == 6
        assert resumed.player_state["injury"] == "测试伤势"
        leaked = resumed.player_state
        leaked["elapsed_minutes"] = 999
        assert resumed.player_state["elapsed_minutes"] == 6


def test_authority_map_zeroes_player_state_direct_writers():
    report = _audit()
    rows = [
        row for row in report["facts"]["player_state"]["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert rows == [], rows
    debt = set(P2A_WORLD_MIGRATION_DEBT)
    assert debt == set()
    assert "branch_progress" not in debt


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
