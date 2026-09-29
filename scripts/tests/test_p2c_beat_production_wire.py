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

from runtime import free_stage_prototype as proto


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_beat_wire_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def _production(report, field):
    return [
        row for row in report["facts"][field]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]


def test_completed_and_by_card_have_no_production_bypass():
    report = _audit()
    assert _production(report, "completed") == []
    assert _production(report, "completed_by_card") == []
    beat_rows = _production(report, "beat_state")
    assert {row["symbol"] for row in beat_rows} == {"FreeStageSession._apply_beat_state"}


def test_free_stage_source_has_no_direct_completed_mutators():
    source = inspect.getsource(proto.FreeStageSession)
    for token in (
        "self.completed.append(",
        "self.completed.extend(",
        "self.completed_by_card[",
    ):
        assert token not in source, token


def test_complete_receipt_survives_save_load_as_projection():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-beat-save",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            truth_db_path=None,
            autosave=True,
            load_existing=False,
            caller=proto.fixed_selftest_actor,
        )
        assert session._complete_beat(
            "RP1",
            turn_no=1,
            source_kind="test_evidence",
            evidence_refs=("visible-turn:1",),
        ) is True
        assert session.completed == ["RP1"]
        assert session.completed_by_card[session.card["scene_id"]] == ["RP1"]
        assert session.beat_state["receipts"][-1]["source_kind"] == "test_evidence"
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-beat-save",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            truth_db_path=None,
            autosave=True,
            load_existing=True,
            caller=proto.fixed_selftest_actor,
        )
        assert resumed.beat_state == session.beat_state
        assert resumed.completed == ["RP1"]
        assert resumed.completed_by_card == session.completed_by_card


def test_skip_scene_creates_explicit_skip_receipts():
    with tempfile.TemporaryDirectory() as tmp:
        card = Path(tmp) / "brief.json"
        card.write_text(json.dumps({
            "scene_id": "P2C_BRIEF",
            "scene": "P2C brief",
            "ch_anchor": 1,
            "pacing": "brief",
            "must_happen": [{"id": "M1"}, {"id": "M2"}],
            "exits": [],
            "auto_end_on_complete": True,
            "persona_cards": {},
        }, ensure_ascii=False), encoding="utf-8")
        session = proto.FreeStageSession(
            session_id="p2c-skip",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            truth_db_path=None,
            autosave=False,
            load_existing=False,
            caller=proto.fixed_selftest_actor,
        )
        session.skip_scene(caller=proto.fixed_selftest_actor)
        assert session.completed == ["M1", "M2"]
        receipts = [
            row for row in session.beat_state["receipts"]
            if row["source_kind"] == "skip_scene"
        ]
        assert [row["beat_id"] for row in receipts] == ["M1", "M2"]


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
