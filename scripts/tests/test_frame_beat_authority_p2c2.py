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
    spec = importlib.util.spec_from_file_location("frame_beat_p2c2_audit", AUDIT)
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


def test_frame_reducer_is_copy_safe_ordered_idempotent_and_run_isolated():
    source = {"1": ["F::BE0"], "2": ["F::BE9"]}
    first = beat_state.reduce_frame_beats(
        completed_beats=source,
        run=1,
        frame_id="F",
        operation="mark_done",
        beat_ids=["BE1", "BE2", "BE1"],
        turn_no=4,
        source_kind="scene_beat_projection",
        evidence_refs=["beat:scene"],
    )
    assert source == {"1": ["F::BE0"], "2": ["F::BE9"]}
    assert first.completed_beats == {
        "1": ["F::BE0", "F::BE1", "F::BE2"],
        "2": ["F::BE9"],
    }
    assert first.added_keys == ("F::BE1", "F::BE2")
    assert first.receipt is not None
    assert first.receipt["schema_version"] == "free_stage.frame_beat_transition.v1"
    assert first.receipt["added"] == ["BE1", "BE2"]
    assert first.receipt["evidence_refs"] == ["beat:scene"]

    retry = beat_state.reduce_frame_beats(
        completed_beats=first.completed_beats,
        run=1,
        frame_id="F",
        operation="mark_done",
        beat_ids=["BE1", "BE2"],
        turn_no=4,
        source_kind="scene_beat_projection",
        evidence_refs=["beat:scene"],
    )
    assert retry.completed_beats == first.completed_beats
    assert retry.added_keys == ()
    assert retry.receipt is None


def test_frame_reducer_reset_preserves_no_fake_receipt():
    result = beat_state.reduce_frame_beats(
        completed_beats={"1": ["F::BE1"], "2": ["F::BE2"]},
        run=1,
        frame_id="",
        operation="reset_all",
        turn_no=8,
        source_kind="session_reset",
    )
    assert result.completed_beats == {}
    assert result.added_keys == ()
    assert result.receipt is None


def test_session_projects_scene_receipt_into_frame_receipt_and_save_load():
    synthetic = {
        "scene_id": "FRAME_VIEW_A",
        "scene_frame": {"frame_id": "F.SHARED"},
        "must_happen": [
            {"id": "RP1", "frame_beat": ["BE1", "BE2"]},
            {"id": "LOCAL", "frame_beat": []},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = FreeStageSession(
            session_id="frame-p2c2",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=False,
        )
        added = session._reduce_beat_state(
            "complete",
            beat_ids=["RP1"],
            turn_no=2,
            source_kind="fixture_visible",
            evidence_refs=("visible-output:2",),
        )
        assert added == ["RP1"]
        active = beat_state.active_scene(session.beat_state)
        evidence_ids = active["satisfied"]["RP1"]["evidence_ids"]
        assert len(evidence_ids) == 1
        scene_evidence_id = evidence_ids[0]
        assert session.beat_receipts == []

        session._mark_frame_beats_for_progress(
            synthetic,
            added,
            turn_no=2,
        )
        assert session.completed_beats == {
            str(session.run_no): ["F.SHARED::BE1", "F.SHARED::BE2"]
        }
        assert len(session.frame_beat_receipts) == 1
        frame_receipt = dict(session.frame_beat_receipts[0])
        assert frame_receipt["added"] == ["BE1", "BE2"]
        assert frame_receipt["evidence_refs"] == [scene_evidence_id]

        # Retry does not duplicate keys or receipts.
        session._mark_frame_beats_for_progress(synthetic, added, turn_no=2)
        assert len(session.frame_beat_receipts) == 1
        assert session.completed_beats[str(session.run_no)] == [
            "F.SHARED::BE1", "F.SHARED::BE2"
        ]
        session.save()

        resumed = FreeStageSession(
            session_id="frame-p2c2",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=True,
        )
        assert resumed.completed_beats == session.completed_beats
        assert resumed.frame_beat_receipts == [frame_receipt]


def test_frame_view_folding_semantics_are_unchanged():
    synthetic = {
        "scene_id": "FRAME_VIEW_B",
        "scene_frame": {"frame_id": "F.SHARED"},
        "must_happen": [
            {"id": "REMOTE", "frame_beat": ["BE1"], "desc": "共享事件"},
            {"id": "LOCAL", "frame_beat": [], "desc": "纯视角事件"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        session = FreeStageSession(
            session_id="frame-fold",
            card_path=CARD,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=False,
            load_existing=False,
        )
        session._reduce_frame_beats(
            "mark_done",
            frame_id="F.SHARED",
            beat_ids=["BE1"],
            turn_no=1,
            source_kind="fixture",
            evidence_refs=("beat:x",),
        )
        resolved = session._resolve_frame_beat_view(synthetic)
        assert [item["id"] for item in resolved["must_happen"]] == ["LOCAL"]
        assert [item["id"] for item in resolved["_folded_frame_beats"]] == ["REMOTE"]


def test_authority_map_has_one_frame_beat_writer_and_no_alias_debt():
    report = _report()
    frame = _production(report, "completed_beats")
    assert {row["symbol"] for row in frame} == {"FreeStageSession._reduce_frame_beats"}
    assert report["facts"]["completed_beats"]["production_writer_count"] == 1
    assert report["facts"]["completed_beats"]["unknown_alias_count"] == 0


def test_free_stage_does_not_pass_session_ledger_to_mutating_helper():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "mark_done(self.completed_beats" not in source
    assert "frame_beat_ledger.mark_done(self.completed_beats" not in source
    # Legacy load migration + one production reducer facade only.
    assert source.count("self.completed_beats =") == 2


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
