#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import beat_reducer


def test_completion_idempotency_and_revisit_identity():
    state = beat_reducer.empty_state("S1")
    state, added, first = beat_reducer.complete(
        state, "B1", turn=1, source_kind="observed_progress", evidence_refs=["turn:1"]
    )
    assert added is True
    state, added, same = beat_reducer.complete(
        state, "B1", turn=2, source_kind="other", evidence_refs=["turn:2"]
    )
    assert added is False
    assert same["receipt_id"] == first["receipt_id"]

    state = beat_reducer.switch_scene(state, "S2")
    state = beat_reducer.switch_scene(state, "S1")
    state, added, revisit = beat_reducer.complete(
        state, "B1", turn=3, source_kind="observed_progress", evidence_refs=["turn:3"]
    )
    assert added is True
    assert revisit["receipt_id"] != first["receipt_id"]
    assert revisit["scene_epoch"] > first["scene_epoch"]


def test_legacy_migration_has_no_fake_player_evidence():
    state = beat_reducer.migrate_legacy(
        scene_id="S2",
        completed=["B2"],
        completed_by_card={"S1": ["B1"]},
    )
    current, by_card = beat_reducer.projections(state)
    assert current == ["B2"]
    assert by_card["S1"] == ["B1"]
    assert by_card["S2"] == ["B2"]
    assert state["receipts"][0]["source_kind"] == "legacy_load"
    assert state["receipts"][0]["evidence_refs"] == []


def test_switch_restore_and_checkpoint_are_explicit():
    state = beat_reducer.empty_state("MAIN")
    state, _, _ = beat_reducer.complete(state, "M1", turn=1, source_kind="observed")
    state = beat_reducer.switch_scene(state, "FLASH")
    assert beat_reducer.projections(state)[0] == []
    state, _, _ = beat_reducer.complete(state, "F1", turn=2, source_kind="observed")
    state = beat_reducer.switch_scene(state, "MAIN", restore_completed=["M1"])
    current, by_card = beat_reducer.projections(state)
    assert current == ["M1"]
    assert by_card["FLASH"] == ["F1"]
    assert by_card["MAIN"] == ["M1"]


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
