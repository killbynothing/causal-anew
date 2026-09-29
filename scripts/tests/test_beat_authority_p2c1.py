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

from runtime import beat_state
from runtime.free_stage_prototype import FreeStageSession

CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
AUDIT = ROOT / "scripts" / "audit_runtime_authority.py"


def _caller(**_kwargs):
    return json.dumps(
        {"turns": [], "mh_progress": [], "director_note": ""},
        ensure_ascii=False,
    )


def _report():
    spec = importlib.util.spec_from_file_location("beat_authority_p2c1_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def _production(report, fact):
    return [
        row for row in report["facts"][fact]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]


def test_pure_reducer_complete_is_ordered_idempotent_and_sourced():
    first = beat_state.reduce_beat_state(
        completed=["RP1"],
        completed_by_card={"OLD": ["X"]},
        scene_id="CAFE",
        operation="complete",
        beat_ids=["RP1", "RP2", "RP2"],
        turn_no=3,
        source_kind="observed_progress",
        evidence_refs=["visible-output:turn:3"],
    )
    assert first.completed == ("RP1", "RP2")
    assert first.completed_by_card == {"OLD": ["X"]}
    assert first.added == ("RP2",)
    assert first.receipt is not None
    assert first.receipt["added"] == ["RP2"]
    assert first.receipt["evidence_refs"] == ["visible-output:turn:3"]
    assert first.receipt["receipt_id"].startswith("beat:")

    retry = beat_state.reduce_beat_state(
        completed=first.completed,
        completed_by_card=first.completed_by_card,
        scene_id="CAFE",
        operation="complete",
        beat_ids=["RP2"],
        turn_no=3,
        source_kind="observed_progress",
        evidence_refs=["visible-output:turn:3"],
    )
    assert retry.completed == first.completed
    assert retry.added == ()
    assert retry.receipt is None


def test_pure_reducer_projection_operations_do_not_invent_completion():
    by_card = {"A": ["A1"]}
    snap = beat_state.reduce_beat_state(
        completed=["B1"],
        completed_by_card=by_card,
        scene_id="B",
        operation="snapshot",
        turn_no=4,
        source_kind="scene_snapshot",
    )
    assert snap.completed == ("B1",)
    assert snap.completed_by_card == {"A": ["A1"], "B": ["B1"]}
    assert snap.receipt is None

    empty = beat_state.reduce_beat_state(
        completed=snap.completed,
        completed_by_card=snap.completed_by_card,
        scene_id="C",
        operation="enter_empty",
        turn_no=5,
        source_kind="scene_enter",
    )
    assert empty.completed == ()
    assert empty.completed_by_card == snap.completed_by_card
    assert empty.receipt is None

    restored = beat_state.reduce_beat_state(
        completed=empty.completed,
        completed_by_card=empty.completed_by_card,
        scene_id="B",
        operation="restore",
        beat_ids=["B1"],
        turn_no=6,
        source_kind="flashback_return_restore",
    )
    assert restored.completed == ("B1",)
    assert restored.completed_by_card == empty.completed_by_card
    assert restored.receipt is None

    reset = beat_state.reduce_beat_state(
        completed=restored.completed,
        completed_by_card=restored.completed_by_card,
        scene_id="",
        operation="reset_all",
        turn_no=7,
        source_kind="session_reset",
    )
    assert reset.completed == ()
    assert reset.completed_by_card == {}
    assert reset.receipt is None


def test_replace_complete_preserves_brief_skip_exact_semantics_with_receipt():
    result = beat_state.reduce_beat_state(
        completed=["STALE"],
        completed_by_card={"OLD": ["OLD1"]},
        scene_id="BRIEF",
        operation="replace_complete",
        beat_ids=["B1", "B2"],
        turn_no=2,
        source_kind="brief_skip",
        evidence_refs=["brief-skip:BRIEF"],
    )
    assert result.completed == ("B1", "B2")
    assert result.added == ("B1", "B2")
    assert result.completed_by_card == {"OLD": ["OLD1"]}
    assert result.receipt is not None
    assert result.receipt["operation"] == "replace_complete"


def test_session_facade_persists_beat_receipt_and_projection():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = FreeStageSession(
            session_id="beat-p2c1",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=False,
        )
        added = session._reduce_beat_state(
            "complete",
            beat_ids=["RP1", "RP2"],
            turn_no=2,
            source_kind="test_observed_progress",
            evidence_refs=("fixture:visible",),
        )
        assert added == ["RP1", "RP2"]
        assert session.completed == ["RP1", "RP2"]
        assert len(session.beat_receipts) == 1
        receipt = dict(session.beat_receipts[0])
        assert receipt["source_kind"] == "test_observed_progress"

        session._reduce_beat_state(
            "snapshot",
            scene_id="OPENING_RYUYA_PROLOGUE_001",
            turn_no=2,
            source_kind="scene_snapshot",
        )
        assert session.completed_by_card["OPENING_RYUYA_PROLOGUE_001"] == ["RP1", "RP2"]
        session.save()

        resumed = FreeStageSession(
            session_id="beat-p2c1",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=True,
        )
        assert resumed.completed == ["RP1", "RP2"]
        assert resumed.completed_by_card["OPENING_RYUYA_PROLOGUE_001"] == ["RP1", "RP2"]
        assert resumed.beat_receipts == [receipt]


def test_authority_map_has_one_scene_beat_writer_and_p2c2_resolves_frame_debt():
    report = _report()
    completed = _production(report, "completed")
    by_card = _production(report, "completed_by_card")
    assert {row["symbol"] for row in completed} == {"FreeStageSession._reduce_beat_state"}
    assert {row["symbol"] for row in by_card} == {"FreeStageSession._reduce_beat_state"}
    assert report["facts"]["completed"]["production_writer_count"] == 1
    assert report["facts"]["completed_by_card"]["production_writer_count"] == 1

    # P2c-2 is the required successor invariant: the previously frozen
    # completed_beats alias debt must now be gone, not silently deleted.
    frame = _production(report, "completed_beats")
    assert {row["symbol"] for row in frame} == {"FreeStageSession._reduce_frame_beats"}
    assert report["facts"]["completed_beats"]["production_writer_count"] == 1
    assert report["facts"]["completed_beats"]["unknown_alias_count"] == 0


def test_free_stage_has_no_direct_business_append_or_by_card_subscript_writer():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.completed.append(" not in source
    assert "self.completed.extend(" not in source
    assert "self.completed_by_card[" not in source

    # Direct assignment is allowed only for legacy load migration and the
    # single production reducer facade. Initialization is an annotated field.
    assert source.count("self.completed =") == 2
    assert source.count("self.completed_by_card =") == 2


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
