#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime.causal_protocol import ReceiptConflict, RuntimeScope
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT, WorldCommitState


def _scope():
    return RuntimeScope(
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="p2c",
        scene_instance_id="S1:visit:1",
    )


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_world_commit_state_views_are_copy_only():
    state = WorldCommitState(
        scene_receipts=[{"scene_id": "S1", "fact_id": "f1"}],
        world_transactions={"tx": {"transaction_id": "tx", "kind": "k"}},
        causal_receipts=[{"receipt_id": "r1", "event": {"x": 1}}],
    )
    scenes = state.scene_receipts_view()
    txs = state.world_transactions_view()
    causal = state.causal_receipts_view()
    scenes.append({"scene_id": "S1", "fact_id": "evil"})
    txs["tx"]["kind"] = "evil"
    causal[0]["event"]["x"] = 99
    assert [x["fact_id"] for x in state.scene_receipts_view()] == ["f1"]
    assert state.world_transactions_view()["tx"]["kind"] == "k"
    assert state.causal_receipts_view()[0]["event"]["x"] == 1


def test_scene_and_causal_receipts_are_idempotent_inside_owner():
    state = WorldCommitState()
    scene = {"scene_id": "S1", "fact_id": "seen", "owner": "player", "turn": 1}
    assert state.append_scene_receipt(scene) is True
    assert state.append_scene_receipt({**scene, "turn": 2}) is False

    causal = {"receipt_id": "r1", "event": {"event_id": "e1"}}
    assert state.append_causal_receipt(causal) is True
    assert state.append_causal_receipt(copy.deepcopy(causal)) is False
    try:
        state.append_causal_receipt({"receipt_id": "r1", "event": {"event_id": "DIFF"}})
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same causal receipt id with different payload must conflict")


def test_world_commit_state_owns_transaction_mutation():
    state = WorldCommitState()
    result = state.commit_fact(
        scope=_scope(),
        request_id="req:1",
        turn_id="turn:1",
        transaction_id="tx1",
        kind="public_event",
        outcome="done",
        owner="world",
        scene_id="S1",
        turn=1,
        public_effect="visible",
        source_refs=(),
        base_revision=0,
    )
    assert result.committed is True
    tx = state.get_transaction("tx1")
    assert tx["receipt"]["producer"] == "WorldCommit"
    view = state.world_transactions_view()
    view["tx1"]["outcome"] = "tampered"
    assert state.get_transaction("tx1")["outcome"] == "done"


def test_session_roundtrip_uses_world_commit_state_not_direct_ledgers():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-state",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._record_scene_receipt("fact-a", owner="player", turn_no=1)
        session._commit_world_transaction(
            "tx-a", kind="public_event", outcome="done", owner="world",
            turn_no=1, public_effect="visible",
        )
        session._world_commit_state.append_causal_receipt(
            {"receipt_id": "causal-a", "event": {"event_id": "e-a"}}
        )
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-state",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.scene_receipts[0]["fact_id"] == "fact-a"
        assert resumed.world_transactions["tx-a"]["outcome"] == "done"
        assert resumed.causal_receipts[0]["receipt_id"] == "causal-a"

        # compatibility views cannot mutate the owner
        resumed.scene_receipts.append({"scene_id": "evil", "fact_id": "evil"})
        resumed.world_transactions["tx-a"]["outcome"] = "evil"
        resumed.causal_receipts.clear()
        assert len(resumed.scene_receipts) == 1
        assert resumed.world_transactions["tx-a"]["outcome"] == "done"
        assert len(resumed.causal_receipts) == 1


def test_authority_map_has_zero_production_direct_writers_for_migrated_ledgers():
    audit = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_authority_audit", audit)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.build_report(False)

    for fact in ("scene_receipts", "world_transactions", "causal_receipts"):
        rows = [
            row for row in report["facts"][fact]["writers"]
            if row["classification"] in {"production", "production_tooling"}
        ]
        assert rows == [], (fact, rows)

    debt = set(P2A_WORLD_MIGRATION_DEBT)
    assert "scene_receipts" not in debt
    assert "world_transactions" not in debt
    assert "causal_receipts" not in debt
    assert debt == {"branch_progress"}
    assert "player_state" not in debt
    assert "world_cursor" not in debt
    assert "run_observation_ledger" not in debt
    assert "body_frames" not in debt


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
