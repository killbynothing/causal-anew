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

from runtime.causal_protocol import ReceiptConflict, RuntimeScope
from runtime.world_ledger_reducer import WorldLedgerReducer
from runtime import free_stage_prototype as proto


def _scope():
    return RuntimeScope(
        worldline="WMAIN", run=1, ch_anchor=1,
        session_id="p2c-ledger", scene_instance_id="S1:visit:1",
    )


def _report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_world_ledger_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_reducer_snapshots_are_copy_safe():
    reducer = WorldLedgerReducer(
        world_transactions={"tx": {"transaction_id": "tx", "kind": "k"}},
        causal_receipts=[{"receipt_id": "r1", "value": {"x": 1}}],
        run_observation_ledger=[{"id": "o1", "fact_text": "x"}],
    )
    tx = reducer.transaction_snapshot()
    causal = reducer.causal_snapshot()
    obs = reducer.observation_snapshot()
    tx["tx"]["kind"] = "mutated"
    causal[0]["value"]["x"] = 9
    obs[0]["fact_text"] = "mutated"
    assert reducer.transaction_snapshot()["tx"]["kind"] == "k"
    assert reducer.causal_snapshot()[0]["value"]["x"] == 1
    assert reducer.observation_snapshot()[0]["fact_text"] == "x"


def test_world_commit_still_decides_transaction_and_conflict_is_atomic():
    reducer = WorldLedgerReducer()
    first = reducer.commit_world_fact(
        scope=_scope(), request_id="req", turn_id="turn:1",
        transaction_id="tx", kind="event", outcome="happened",
        owner="world", scene_id="S1", turn=1,
    )
    assert first.committed is True
    before = reducer.transaction_snapshot()
    retry = reducer.commit_world_fact(
        scope=_scope(), request_id="req", turn_id="turn:1",
        transaction_id="tx", kind="event", outcome="happened",
        owner="world", scene_id="S1", turn=1,
    )
    assert retry.committed is False
    try:
        reducer.commit_world_fact(
            scope=_scope(), request_id="req", turn_id="turn:1",
            transaction_id="tx", kind="event", outcome="different",
            owner="world", scene_id="S1", turn=1,
        )
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("conflicting world transaction must fail")
    assert reducer.transaction_snapshot() == before


def test_causal_receipt_same_id_different_payload_conflicts():
    reducer = WorldLedgerReducer()
    assert reducer.append_causal_receipt({"receipt_id": "r1", "event": {"x": 1}}) is True
    assert reducer.append_causal_receipt({"receipt_id": "r1", "event": {"x": 1}}) is False
    before = reducer.causal_snapshot()
    try:
        reducer.append_causal_receipt({"receipt_id": "r1", "event": {"x": 2}})
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same causal receipt id with different payload must conflict")
    assert reducer.causal_snapshot() == before


def test_observation_append_is_idempotent():
    reducer = WorldLedgerReducer()
    assert reducer.append_observation(
        kind="pendant", fact_text="挂坠accepted", turn=1, scene_id="S1"
    ) is True
    assert reducer.append_observation(
        kind="pendant", fact_text="挂坠accepted", turn=1, scene_id="S1"
    ) is False
    assert len(reducer.observation_snapshot()) == 1


def test_session_ledgers_are_copy_safe_and_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-ledger",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._commit_world_transaction(
            "tx", kind="event", outcome="done", owner="world", turn_no=1
        ) is True
        session._world_ledger.append_causal_receipt({"receipt_id": "r1", "event": {"x": 1}})
        session._world_ledger.append_observation(
            kind="default", fact_text="看见一件事", turn=1, scene_id="S1"
        )
        leaked_tx = session.world_transactions
        leaked_causal = session.causal_receipts
        leaked_obs = session.run_observation_ledger
        leaked_tx.clear()
        leaked_causal.clear()
        leaked_obs.clear()
        assert "tx" in session.world_transactions
        assert len(session.causal_receipts) == 1
        assert len(session.run_observation_ledger) == 1
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-ledger",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.world_transactions == session.world_transactions
        assert resumed.causal_receipts == session.causal_receipts
        assert resumed.run_observation_ledger == session.run_observation_ledger


def test_authority_map_three_ledgers_have_one_writer_each():
    report = _report()
    expected = {
        "world_transactions": "WorldLedgerReducer._write_world_transactions",
        "causal_receipts": "WorldLedgerReducer._write_causal_receipts",
        "run_observation_ledger": "WorldLedgerReducer._write_run_observation_ledger",
    }
    for fact, symbol in expected.items():
        rows = [
            row for row in report["facts"][fact]["writers"]
            if row["classification"] in {"production", "production_tooling"}
        ]
        actual = {row["symbol"] for row in rows}
        assert actual == {symbol}, (fact, sorted(actual), rows)
        assert report["facts"][fact]["production_writer_count"] == 1, (
            fact, report["facts"][fact]["production_writer_count"], rows
        )


def test_free_stage_has_no_direct_three_ledger_writers():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    for forbidden in (
        "self.world_transactions =",
        "self.causal_receipts =",
        "self.causal_receipts.append",
        "self.run_observation_ledger =",
        "_ledger_append(",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
