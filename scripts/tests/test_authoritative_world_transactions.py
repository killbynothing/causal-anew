#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.causal_protocol import ReceiptConflict, RuntimeScope
from runtime.player_action import build_player_action, commit_player_action
from runtime.world_commit import (
    P2A_WORLD_MIGRATION_DEBT,
    commit_world_batch,
    commit_world_fact,
)
from runtime import free_stage_prototype as proto


def _scope(scene="S1:visit:1"):
    return RuntimeScope(
        worldline="WMAIN",
        run=1,
        ch_anchor=1,
        session_id="p2a-fixture",
        scene_instance_id=scene,
    )


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_player_action_receipt_records_behavior_not_world_result():
    record = build_player_action(
        scope=_scope(),
        request_id="req:accept",
        turn_id="turn:3",
        action_id="accept-pendant",
        action_kind="item_response",
        target="pendant",
        value="accept",
        turn=3,
        source_refs=["input:3"],
    )
    action = record["action"]
    assert action == {
        "action_id": "accept-pendant",
        "actor": "player",
        "action_kind": "item_response",
        "target": "pendant",
        "value": "accept",
        "turn": 3,
    }
    blob = json.dumps(action, ensure_ascii=False)
    for forbidden in ("custody", "holding", "owner_after", "public_effect", "world_outcome"):
        assert forbidden not in blob
    assert record["receipt"]["producer"] == "PlayerAction"


def test_player_action_same_id_conflict_is_hard_and_non_mutating():
    ledger = {}
    a = build_player_action(
        scope=_scope(), request_id="req:a", turn_id="turn:1",
        action_id="a1", action_kind="branch_choice", target="route", value="left", turn=1,
    )
    assert commit_player_action(ledger, a).committed is True
    assert commit_player_action(ledger, a).committed is False
    before = json.dumps(ledger, sort_keys=True, ensure_ascii=False)
    b = build_player_action(
        scope=_scope(), request_id="req:a", turn_id="turn:1",
        action_id="a1", action_kind="branch_choice", target="route", value="right", turn=1,
    )
    try:
        commit_player_action(ledger, b)
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same player action id with different payload must conflict")
    assert json.dumps(ledger, sort_keys=True, ensure_ascii=False) == before


def test_world_commit_receipt_is_scoped_and_conflict_safe():
    ledger = {}
    result = commit_world_fact(
        ledger,
        scope=_scope(),
        request_id="req:world:1",
        turn_id="turn:2",
        transaction_id="tx1",
        kind="presence_exit",
        outcome="actor_chose_leave",
        owner="C.actor.WMAIN",
        scene_id="S1",
        turn=2,
        public_effect="removed_from_current_scene",
        source_refs=["player:source"],
    )
    assert result.committed is True
    record = result.record
    assert record["receipt"]["producer"] == "WorldCommit"
    assert record["receipt"]["source_refs"] == ["player:source"]
    assert record["run"] == 1 and record["worldline"] == "WMAIN"

    same = commit_world_fact(
        ledger,
        scope=_scope(),
        request_id="req:world:1",
        turn_id="turn:2",
        transaction_id="tx1",
        kind="presence_exit",
        outcome="actor_chose_leave",
        owner="C.actor.WMAIN",
        scene_id="S1",
        turn=2,
        public_effect="removed_from_current_scene",
        source_refs=["player:source"],
    )
    assert same.committed is False

    before = json.dumps(ledger, sort_keys=True, ensure_ascii=False)
    try:
        commit_world_fact(
            ledger,
            scope=_scope(),
            request_id="req:world:1",
            turn_id="turn:2",
            transaction_id="tx1",
            kind="presence_exit",
            outcome="actor_stayed",
            owner="C.actor.WMAIN",
            scene_id="S1",
            turn=2,
            public_effect="still_present",
            source_refs=["player:source"],
        )
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same world transaction id with different outcome must conflict")
    assert json.dumps(ledger, sort_keys=True, ensure_ascii=False) == before


def test_world_batch_is_atomic_and_has_stable_batch_id():
    ledger = {}
    first = commit_world_batch(
        ledger,
        scope=_scope(),
        request_id="req:batch",
        turn_id="turn:5",
        facts=(
            {
                "transaction_id": "b1",
                "kind": "public_event",
                "outcome": "one",
                "owner": "world",
                "scene_id": "S1",
                "turn": 5,
                "public_effect": "one",
            },
            {
                "transaction_id": "b2",
                "kind": "public_event",
                "outcome": "two",
                "owner": "world",
                "scene_id": "S1",
                "turn": 5,
                "public_effect": "two",
            },
        ),
    )
    assert first.committed_ids == ("b1", "b2")
    assert first.records[0]["batch_id"] == first.batch_id
    assert first.records[1]["batch_id"] == first.batch_id
    assert first.records[0]["receipt"]["sequence"] == 0
    assert first.records[1]["receipt"]["sequence"] == 1

    retry = commit_world_batch(
        ledger,
        scope=_scope(),
        request_id="req:batch",
        turn_id="turn:5",
        facts=(
            {
                "transaction_id": "b1",
                "kind": "public_event",
                "outcome": "one",
                "owner": "world",
                "scene_id": "S1",
                "turn": 5,
                "public_effect": "one",
            },
            {
                "transaction_id": "b2",
                "kind": "public_event",
                "outcome": "two",
                "owner": "world",
                "scene_id": "S1",
                "turn": 5,
                "public_effect": "two",
            },
        ),
    )
    assert retry.batch_id == first.batch_id
    assert retry.committed_ids == ()
    assert retry.existing_ids == ("b1", "b2")

    before = json.dumps(ledger, ensure_ascii=False, sort_keys=True)
    try:
        commit_world_batch(
            ledger,
            scope=_scope(),
            request_id="req:conflict-batch",
            turn_id="turn:6",
            facts=(
                {
                    "transaction_id": "new-before-conflict",
                    "kind": "public_event",
                    "outcome": "new",
                    "owner": "world",
                    "scene_id": "S1",
                    "turn": 6,
                },
                {
                    "transaction_id": "b2",
                    "kind": "public_event",
                    "outcome": "DIFFERENT",
                    "owner": "world",
                    "scene_id": "S1",
                    "turn": 6,
                },
            ),
        )
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("one conflicting fact must abort the whole batch")
    assert json.dumps(ledger, ensure_ascii=False, sort_keys=True) == before
    assert "new-before-conflict" not in ledger


def test_legacy_world_transaction_retry_is_read_only_compatible():
    legacy = {
        "transaction_id": "legacy",
        "kind": "opening_synopsis",
        "outcome": "shown",
        "owner": "world",
        "scene_id": "S1",
        "turn": 0,
        "worldline": "WMAIN",
        "run": 1,
        "public_effect": "shown",
    }
    ledger = {"legacy": dict(legacy)}
    result = commit_world_fact(
        ledger,
        scope=_scope(),
        request_id="req:legacy",
        turn_id="turn:0",
        transaction_id="legacy",
        kind="opening_synopsis",
        outcome="shown",
        owner="world",
        scene_id="S1",
        turn=0,
        public_effect="shown",
    )
    assert result.committed is False
    assert ledger["legacy"] == legacy
    assert "receipt" not in ledger["legacy"]


def test_free_stage_world_transaction_delegates_to_world_commit():
    source = inspect.getsource(proto.FreeStageSession._commit_world_transaction)
    assert "_world_commit_state.commit_fact" in source
    assert "self.world_transactions[" not in source
    assert "world_commit.commit_world_fact" not in source

    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2a-session",
            state_dir=Path(tmp) / "states",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        assert session._commit_world_transaction(
            "p2a-demo",
            kind="public_event",
            outcome="happened",
            owner="world",
            turn_no=1,
            public_effect="visible",
        ) is True
        tx = session._world_transaction("p2a-demo")
        assert tx["receipt"]["producer"] == "WorldCommit"
        assert session._commit_world_transaction(
            "p2a-demo",
            kind="public_event",
            outcome="happened",
            owner="world",
            turn_no=1,
            public_effect="visible",
        ) is False
        try:
            session._commit_world_transaction(
                "p2a-demo",
                kind="public_event",
                outcome="different",
                owner="world",
                turn_no=1,
                public_effect="changed",
            )
        except ReceiptConflict:
            pass
        else:
            raise AssertionError("production helper must reject conflicting retry")


def test_player_branch_fact_uses_player_action_entry_and_survives_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2a-player",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._record_player_branch_fact(
            "route_left", turn_no=1, player_input="走左边"
        ) is True
        assert "branch:route_left" in session.player_action_receipts
        action = session.player_action_receipts["branch:route_left"]
        assert action["action"]["value"] == "asserted"
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2a-player",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.player_action_receipts == session.player_action_receipts
        assert resumed._record_player_branch_fact(
            "route_left", turn_no=1, player_input="走左边"
        ) is False


def test_p2a_debt_list_covers_current_worldcommit_authority_families():
    audit_path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2a_authority_audit", audit_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.build_report(False)
    current = {
        fact
        for fact, meta in report["facts"].items()
        if meta.get("target_owner") == "WorldCommit"
        and int(meta.get("production_writer_count") or 0) > 0
    }
    debt = set(P2A_WORLD_MIGRATION_DEBT)
    assert current <= debt, f"unlisted P2a world authority debt: {sorted(current - debt)}"
    assert {"branch_progress", "body_frames", "player_state"} <= debt


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
