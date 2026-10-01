#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.causal_protocol import ReceiptConflict, RuntimeScope
from runtime.world_commit import (
    active_scene_fact_ids,
    assert_branch_fact,
    migrate_legacy_scene_facts,
    new_scene_fact_ledger,
    normalize_scene_fact_ledger,
    project_branch_progress,
    project_scene_receipts,
    record_scene_receipt,
    revoke_branch_facts,
)


def _scope(visit: int = 1, run: int = 1) -> RuntimeScope:
    return RuntimeScope(
        worldline="WMAIN",
        run=run,
        ch_anchor=1,
        session_id="p2c-scene-facts",
        scene_instance_id=f"SCENE_A:visit:{visit}",
    )


def test_assert_revoke_is_append_only_projection():
    ledger = new_scene_fact_ledger()
    first = assert_branch_fact(
        ledger,
        scope=_scope(),
        request_id="branch:left",
        fact_id="left",
        owner="player",
        turn=1,
        source_kind="player_branch",
        source_refs=("player:1",),
    )
    assert first.committed is True
    assert project_branch_progress(ledger) == ["left"]
    before_events = copy.deepcopy(ledger["events"])

    assert revoke_branch_facts(
        ledger,
        scope=_scope(),
        request_id="exclusive:right",
        fact_ids=("left", "missing"),
        owner="world",
        turn=2,
        source_kind="branch_exclusive",
        source_refs=("player:2",),
    ) == ("left",)
    assert project_branch_progress(ledger) == []
    assert set(before_events) < set(ledger["events"])
    assert ledger["events"][first.event["event_id"]]["operation"] == "assert"

    second = assert_branch_fact(
        ledger,
        scope=_scope(),
        request_id="branch:right",
        fact_id="right",
        owner="player",
        turn=2,
        source_kind="player_branch",
        source_refs=("player:2",),
    )
    assert second.committed is True
    assert project_branch_progress(ledger) == ["right"]


def test_same_request_conflict_is_hard_and_non_mutating():
    ledger = new_scene_fact_ledger()
    assert_branch_fact(
        ledger,
        scope=_scope(),
        request_id="same-request",
        fact_id="x",
        owner="player",
        turn=1,
        source_kind="player_branch",
        source_refs=("player:1",),
    )
    before = copy.deepcopy(ledger)
    try:
        assert_branch_fact(
            ledger,
            scope=_scope(),
            request_id="same-request",
            fact_id="x",
            owner="actor",
            turn=1,
            source_kind="actor_outcome",
            source_refs=("actor:1",),
        )
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same event key with different payload must conflict")
    assert ledger == before


def test_scene_receipt_is_idempotent_per_visit_but_not_across_revisit():
    ledger = new_scene_fact_ledger()
    r1, committed1 = record_scene_receipt(
        ledger,
        scope=_scope(1),
        request_id="receipt:fact-a",
        scene_id="SCENE_A",
        fact_id="fact-a",
        owner="player",
        turn=3,
        source_kind="player_input",
        source_input="说了",
        source_refs=("player:3",),
    )
    r2, committed2 = record_scene_receipt(
        ledger,
        scope=_scope(1),
        request_id="receipt:fact-a:retry",
        scene_id="SCENE_A",
        fact_id="fact-a",
        owner="player",
        turn=99,
        source_kind="player_input",
        source_input="另一句",
        source_refs=("player:99",),
    )
    assert committed1 is True
    assert committed2 is False
    assert r2 == r1
    assert r1["world_receipt_id"].startswith("world-scene:")

    r3, committed3 = record_scene_receipt(
        ledger,
        scope=_scope(2),
        request_id="receipt:fact-a:visit2",
        scene_id="SCENE_A",
        fact_id="fact-a",
        owner="player",
        turn=1,
        source_kind="player_input",
        source_input="重访",
        source_refs=("player:visit2",),
    )
    assert committed3 is True
    assert r3["receipt_id"] != r1["receipt_id"]
    assert r3["scene_instance_id"] != r1["scene_instance_id"]
    assert len(project_scene_receipts(ledger)) == 2


def test_legacy_migration_preserves_markers_and_receipt_ids_without_player_action():
    ledger = new_scene_fact_ledger()
    legacy_receipt = {
        "scene_id": "OLD_SCENE",
        "scene_instance_id": "OLD_SCENE:legacy:old",
        "fact_id": "old-fact",
        "owner": "player",
        "turn": 4,
        "source_input": "old input",
        "source_kind": "player_input",
        "receipt_id": "scene:legacy-preserved",
    }
    migrate_legacy_scene_facts(
        ledger,
        scope=_scope(),
        branch_progress=["old-branch", "old-fact"],
        scene_receipts=[legacy_receipt],
    )
    assert project_branch_progress(ledger) == ["old-branch", "old-fact"]
    receipts = project_scene_receipts(ledger)
    assert receipts[0]["receipt_id"] == "scene:legacy-preserved"
    assert receipts[0]["fact_id"] == "old-fact"
    assert active_scene_fact_ids(ledger) == {"old-branch", "old-fact"}
    assert not any(
        "player_action" in str(event).lower()
        for event in ledger["events"].values()
    )
    assert normalize_scene_fact_ledger(ledger) == ledger


def test_run_zero_legacy_projection_is_readonly_adapter_without_commit_receipt():
    ledger = new_scene_fact_ledger()
    migrate_legacy_scene_facts(
        ledger,
        scope=_scope(run=0),
        branch_progress=["legacy-run0"],
        scene_receipts=[],
    )
    assert project_branch_progress(ledger) == ["legacy-run0"]
    event = next(iter(ledger["events"].values()))
    assert event["source_kind"] == "legacy_branch_progress"
    assert event["commit_receipt"] == {}


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
