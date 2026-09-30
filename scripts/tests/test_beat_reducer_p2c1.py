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

from runtime.beat_reducer import BEAT_STATE_SCHEMA, BeatReducer
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c1_authority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_reducer_deduplicates_and_records_source():
    reducer = BeatReducer()
    assert reducer.complete(
        "RP1", scene_id="S1", turn=1,
        source_kind="visible_conversation", source_ref="turn:1",
    ) is True
    assert reducer.complete(
        "RP1", scene_id="S1", turn=1,
        source_kind="visible_conversation", source_ref="turn:1",
    ) is False
    assert reducer.view() == ["RP1"]
    receipts = reducer.receipts()
    assert len(receipts) == 1
    assert receipts[0]["beat_id"] == "RP1"
    assert receipts[0]["source_kind"] == "visible_conversation"
    assert receipts[0]["source_ref"] == "turn:1"


def test_legacy_completed_migrates_without_player_evidence():
    reducer = BeatReducer.from_state(
        None,
        legacy_completed=["RP1", "RP2"],
        scene_id="OPENING_RYUYA_PROLOGUE_001",
    )
    assert reducer.view() == ["RP1", "RP2"]
    receipts = reducer.receipts()
    assert {row["source_kind"] for row in receipts} == {"legacy_load"}
    assert all("player" not in row["source_kind"] for row in receipts)


def test_nested_beat_state_roundtrip_wins_over_legacy_projection():
    source = BeatReducer()
    source.complete(
        "TM1", scene_id="OPENING_TIANANMEN_002", turn=2,
        source_kind="observed_progress", source_ref="turn:2",
    )
    state = source.to_dict()
    assert state["schema_version"] == BEAT_STATE_SCHEMA
    restored = BeatReducer.from_state(
        state,
        legacy_completed=["WRONG_LEGACY"],
        scene_id="OPENING_TIANANMEN_002",
    )
    assert restored.view() == ["TM1"]
    assert restored.receipts() == source.receipts()


def test_session_completed_is_projection_and_save_load_preserves_beat_receipts():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c1",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._complete_beat(
            "RP1", turn_no=1,
            source_kind="visible_conversation", source_ref="turn:1",
        ) is True
        projected = session.completed
        projected.append("FAKE")
        assert session.completed == ["RP1"]
        session.save()

        raw = json.loads((state_dir / "p2c1.json").read_text(encoding="utf-8"))
        assert raw["completed"] == ["RP1"]
        assert raw["beat_state"]["completed"] == ["RP1"]
        assert raw["beat_state"]["receipts"][0]["source_kind"] == "visible_conversation"

        resumed = proto.FreeStageSession(
            session_id="p2c1",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["RP1"]
        assert resumed.beat_reducer.receipts() == session.beat_reducer.receipts()


def test_compat_assignment_routes_through_reducer_not_session_list():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c1-compat",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.completed = ["RP1", "RP2"]
        assert session.completed == ["RP1", "RP2"]
        assert {row["source_kind"] for row in session.beat_reducer.receipts()} == {
            "compat_assignment"
        }


def test_authority_map_has_no_free_stage_completed_production_writer():
    report = _report()
    rows = [
        row for row in report["facts"]["completed"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    assert rows
    assert all(row["path"] == "runtime/beat_reducer.py" for row in rows)
    assert all(row["symbol"].startswith("BeatReducer.") for row in rows)
    assert not any("FreeStageSession." in row["symbol"] for row in rows)


def test_free_stage_source_has_no_direct_completed_mutation():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = (
        "self.completed =",
        "self.completed.append(",
        "self.completed.extend(",
        "self.completed.clear(",
        "self.completed.remove(",
    )
    for token in forbidden:
        assert token not in source, token


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
