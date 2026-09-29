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
from runtime.world_commit import (
    P2A_WORLD_MIGRATED_FACTS,
    P2A_WORLD_MIGRATION_DEBT,
    WorldCommitLedgerState,
)


def _scope():
    return RuntimeScope(
        worldline="WMAIN", run=1, ch_anchor=1,
        session_id="p2c4", scene_instance_id="S1:visit:1",
    )


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c4_authority_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_owner_views_are_copy_only():
    state = WorldCommitLedgerState(
        world_transactions={"tx": {"transaction_id": "tx", "kind": "k"}},
        causal_receipts=[{"receipt_id": "r1", "event": {"x": 1}}],
    )
    txs = state.world_transactions_view()
    causal = state.causal_receipts_view()
    txs["tx"]["kind"] = "evil"
    causal[0]["event"]["x"] = 99
    assert state.world_transactions_view()["tx"]["kind"] == "k"
    assert state.causal_receipts_view()[0]["event"]["x"] == 1


def test_causal_receipt_retry_is_idempotent_and_conflict_safe():
    state = WorldCommitLedgerState()
    row = {"receipt_id": "r1", "event": {"event_id": "e1"}}
    assert state.append_causal_receipt(row) is True
    assert state.append_causal_receipt(copy.deepcopy(row)) is False
    before = state.causal_receipts_view()
    try:
        state.append_causal_receipt({"receipt_id": "r1", "event": {"event_id": "DIFF"}})
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same receipt id/different payload must conflict")
    assert state.causal_receipts_view() == before


def test_world_transaction_commit_is_owned_and_view_cannot_mutate_it():
    state = WorldCommitLedgerState()
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
    )
    assert result.committed is True
    assert state.get_transaction("tx1")["receipt"]["producer"] == "WorldCommit"
    leaked = state.world_transactions_view()
    leaked["tx1"]["outcome"] = "evil"
    assert state.get_transaction("tx1")["outcome"] == "done"


def test_legacy_load_does_not_fabricate_provenance():
    legacy = {
        "world_transactions": {
            "old": {
                "transaction_id": "old", "kind": "legacy", "outcome": "seen",
                "owner": "world", "scene_id": "S1", "turn": 0,
                "worldline": "WMAIN", "run": 1, "public_effect": "seen",
            }
        },
        "causal_receipts": [{"receipt_id": "legacy-r", "event": {"event_id": "e"}}],
    }
    state = WorldCommitLedgerState.from_legacy(legacy)
    assert state.get_transaction("old") == legacy["world_transactions"]["old"]
    assert "receipt" not in state.get_transaction("old")
    assert state.causal_receipts_view() == legacy["causal_receipts"]


def test_session_roundtrip_uses_owner_and_compatibility_views_are_read_only():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c4-session",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._commit_world_transaction(
            "tx-a", kind="public_event", outcome="done", owner="world",
            turn_no=1, public_effect="visible",
        ) is True
        session._world_commit_ledger.append_causal_receipt(
            {"receipt_id": "causal-a", "event": {"event_id": "e-a"}}
        )
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c4-session",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed._world_transaction("tx-a")["outcome"] == "done"
        assert resumed.causal_receipts[0]["receipt_id"] == "causal-a"

        leaked_tx = resumed.world_transactions
        leaked_tx["tx-a"]["outcome"] = "evil"
        leaked_causal = resumed.causal_receipts
        leaked_causal.clear()
        assert resumed._world_transaction("tx-a")["outcome"] == "done"
        assert len(resumed.causal_receipts) == 1

        resumed.reset()
        assert resumed.world_transactions == {}
        assert resumed.causal_receipts == []


def test_authority_map_zeroes_direct_world_ledger_writers():
    report = _audit()
    for fact in ("world_transactions", "causal_receipts"):
        rows = [
            row for row in report["facts"][fact]["writers"]
            if row["classification"] in {"production", "production_tooling", "unknown_alias"}
        ]
        assert rows == [], (fact, rows)

    debt = set(P2A_WORLD_MIGRATION_DEBT)
    migrated = set(P2A_WORLD_MIGRATED_FACTS)
    assert {"world_transactions", "causal_receipts"} <= migrated
    assert {"world_transactions", "causal_receipts"}.isdisjoint(debt)
    # P2c-5 moves BodyFrame/observation into their own projection owner.
    # Only player_state/world_cursor remain as WorldCommit migration debt.
    assert debt == {"player_state", "world_cursor"}
    assert {"run_observation_ledger", "body_frames"} <= migrated


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
