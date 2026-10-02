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

from runtime.causal_protocol import ReceiptConflict
from runtime import free_stage_prototype as proto
from runtime.world_commit import WorldLedgerState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_world_ledger_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_world_ledger_views_are_copy_safe_and_reset_owned():
    state = WorldLedgerState.from_snapshot(
        {"tx": {"transaction_id": "tx", "kind": "x"}},
        [{"receipt_id": "r1", "event": {"x": 1}}],
    )
    tx = state.transactions
    tx["tx"]["kind"] = "MUTATED"
    receipts = state.causal_receipts
    receipts[0]["receipt_id"] = "MUTATED"
    receipts[0]["event"]["x"] = 999
    assert state.transactions["tx"]["kind"] == "x"
    assert state.causal_receipts[0]["receipt_id"] == "r1"
    assert state.causal_receipts[0]["event"]["x"] == 1
    state.reset()
    assert state.transactions == {}
    assert state.causal_receipts == []


def test_causal_receipt_retry_is_idempotent_and_conflict_hard():
    state = WorldLedgerState.empty()
    receipt = {"receipt_id": "r1", "event": {"kind": "wait"}}
    assert state.record_causal_receipt(receipt) is True
    receipt["event"]["kind"] = "MUTATED_AFTER_COMMIT"
    assert state.causal_receipts[0]["event"]["kind"] == "wait"
    assert state.record_causal_receipt(
        {"receipt_id": "r1", "event": {"kind": "wait"}}
    ) is False
    try:
        state.record_causal_receipt({"receipt_id": "r1", "event": {"kind": "leave"}})
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same causal receipt id with different payload must conflict")
    assert state.causal_receipts == [receipt]


def test_session_world_ledger_save_load_and_reset():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-world-ledger",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._commit_world_transaction(
            "tx1",
            kind="public_event",
            outcome="happened",
            owner="world",
            turn_no=1,
        )
        session.world_ledger.record_causal_receipt(
            {"receipt_id": "resolver:r1", "event": {"kind": "wait"}}
        )
        world_view = session.world_transactions
        causal_view = session.causal_receipts
        world_view.clear()
        causal_view.clear()
        assert "tx1" in session.world_transactions
        assert len(session.causal_receipts) == 1
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-world-ledger",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_transactions == session.world_transactions
        assert resumed.causal_receipts == session.causal_receipts
        resumed.reset()
        assert resumed.world_transactions == {}
        assert resumed.causal_receipts == []


def test_no_direct_world_ledger_mutation_remains_in_free_stage():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = (
        "self.world_transactions =",
        "self.world_transactions[",
        "self.world_transactions.append(",
        "self.causal_receipts =",
        "self.causal_receipts.append(",
        "self.causal_receipts.extend(",
    )
    for token in forbidden:
        assert token not in source, token
    assert "self.world_ledger.commit_fact(" in source
    assert "self.world_ledger.record_causal_receipt(" in source


def test_authority_map_reports_zero_world_ledger_production_writers():
    report = _audit_report()
    for fact in ("world_transactions", "causal_receipts"):
        meta = report["facts"][fact]
        rows = [
            row for row in meta["writers"]
            if row["classification"] in {"production", "production_tooling"}
        ]
        assert meta["production_writer_count"] == 0, rows
        assert rows == [], rows


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
