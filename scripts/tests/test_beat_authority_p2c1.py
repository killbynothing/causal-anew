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
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


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


def test_compat_facade_commits_authoritative_evidence_and_projects_only():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = FreeStageSession(
            session_id="beat-p2c-integration",
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
        active = beat_state.active_scene(session.beat_state)
        assert active["completion_order"] == ["RP1", "RP2"]
        assert active["evidence"]
        assert {row["source_kind"] for row in active["evidence"].values()} == {
            "test_observed_progress"
        }
        # Legacy beat_receipts are no longer a second authority.
        assert session.beat_receipts == []
        session.save()

        payload = json.loads((state_dir / "beat-p2c-integration.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == "free_stage.session.v2"
        assert payload["beat_state"]["schema_version"] == beat_state.BEAT_STATE_SCHEMA

        resumed = FreeStageSession(
            session_id="beat-p2c-integration",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=True,
        )
        assert resumed.beat_state == session.beat_state
        assert resumed.completed == ["RP1", "RP2"]


def test_scene_beat_business_writers_are_zero_but_frame_owner_remains_single():
    report = _report()
    completed = _production(report, "completed")
    by_card = _production(report, "completed_by_card")
    frame = _production(report, "completed_beats")
    assert completed == []
    assert by_card == []
    assert {row["symbol"] for row in frame} == {"FreeStageSession._reduce_frame_beats"}
    assert report["facts"]["completed"]["production_writer_count"] == 0
    assert report["facts"]["completed_by_card"]["production_writer_count"] == 0
    assert report["facts"]["completed_beats"]["production_writer_count"] == 1
    assert report["facts"]["completed_beats"]["unknown_alias_count"] == 0

    completed_projection = [
        row for row in report["facts"]["completed"]["writers"]
        if row["classification"] == "projection"
    ]
    by_card_projection = [
        row for row in report["facts"]["completed_by_card"]["writers"]
        if row["classification"] == "projection"
    ]
    assert {row["symbol"] for row in completed_projection} == {
        "FreeStageSession._sync_beat_projections"
    }
    assert {row["symbol"] for row in by_card_projection} == {
        "FreeStageSession._sync_beat_projections"
    }


def test_frame_projection_uses_authoritative_beat_evidence_not_legacy_receipts():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    start = source.index("    def _mark_frame_beats_for_progress(")
    end = source.index("\n    def _resolve_frame_beat_view(", start)
    block = source[start:end]
    assert "beat_state.active_scene(self.beat_state)" in block
    assert "self.beat_receipts" not in block


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
