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

from runtime.beat_reducer import (
    BEAT_STATE_SCHEMA,
    BEAT_STATE_SCHEMA_V1,
    BeatReducer,
)
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c2_authority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_v1_beat_state_migrates_legacy_ancillary_fields():
    raw_v1 = {
        "schema_version": BEAT_STATE_SCHEMA_V1,
        "completed": ["RP1"],
        "receipts": [],
    }
    reducer = BeatReducer.from_state(
        raw_v1,
        legacy_completed=["WRONG"],
        legacy_completed_by_card={"S0": ["A"]},
        legacy_completed_beats={"1": ["F::BE1"]},
        legacy_canon_performance_state={
            "S0": {
                "completed_segments": ["SEG1"],
                "pending_stop": "STOP",
            }
        },
        scene_id="S0",
    )
    assert reducer.view() == ["RP1"]
    assert reducer.completed_by_card_view() == {"S0": ["A"]}
    assert reducer.completed_beats_view() == {"1": ["F::BE1"]}
    assert reducer.canon_scene_state("S0")["completed_segments"] == ["SEG1"]
    assert reducer.to_dict()["schema_version"] == BEAT_STATE_SCHEMA


def test_v2_roundtrip_owns_all_beat_state():
    reducer = BeatReducer()
    reducer.complete(
        "RP1", scene_id="S1", turn=1,
        source_kind="visible_conversation", source_ref="turn:1",
    )
    reducer.snapshot_scene("S1")
    reducer.mark_frame_beats(run=1, frame_id="F1", beat_ids=["BE1", "BE2"])
    reducer.update_canon_scene(
        "S1",
        completed_segment="SEG1",
        hidden_segment="SEG1",
        pending_stop="STOP1",
        player_position="counter",
    )
    restored = BeatReducer.from_state(reducer.to_dict(), scene_id="S1")
    assert restored.to_dict() == reducer.to_dict()


def test_ancillary_views_are_copy_safe():
    reducer = BeatReducer()
    reducer.complete("A", scene_id="S", turn=1, source_kind="fixture")
    reducer.snapshot_scene("S")
    reducer.mark_frame_beats(run=1, frame_id="F", beat_ids=["BE1"])
    reducer.update_canon_scene("S", completed_segment="SEG")

    by_card = reducer.completed_by_card_view()
    by_card["S"].append("FAKE")
    beats = reducer.completed_beats_view()
    beats["1"].append("FAKE")
    canon = reducer.canon_scene_state("S")
    canon["completed_segments"].append("FAKE")

    assert reducer.completed_by_card_view() == {"S": ["A"]}
    assert "FAKE" not in reducer.completed_beats_view()["1"]
    assert reducer.canon_scene_state("S")["completed_segments"] == ["SEG"]


def test_frame_ledger_is_append_only_idempotent_and_run_isolated():
    reducer = BeatReducer()
    assert reducer.mark_frame_beats(run=1, frame_id="F", beat_ids=["BE1"]) == ("BE1",)
    assert reducer.mark_frame_beats(run=1, frame_id="F", beat_ids=["BE1"]) == ()
    assert reducer.mark_frame_beats(run=2, frame_id="F", beat_ids=["BE2"]) == ("BE2",)
    assert reducer.frame_completed_beats(run=1, frame_id="F") == {"BE1"}
    assert reducer.frame_completed_beats(run=2, frame_id="F") == {"BE2"}


def test_canon_cursor_updates_without_mutable_alias():
    reducer = BeatReducer()
    first = reducer.update_canon_scene(
        "S",
        completed_segment="SEG1",
        pending_stop="STOP1",
        player_position="p1",
    )
    first["completed_segments"].append("FAKE")
    second = reducer.update_canon_scene(
        "S",
        completed_segment="SEG1",
        hidden_segment="SEG1",
        pending_stop="",
    )
    assert second["completed_segments"] == ["SEG1"]
    assert second["not_visible_segments"] == ["SEG1"]
    assert second["pending_stop"] == ""
    assert second["player_position"] == "p1"


def test_session_legacy_top_level_ancillary_migrates_into_beat_state():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c2-legacy",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session.save()
        path = state_dir / "p2c2-legacy.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["beat_state"] = {
            "schema_version": BEAT_STATE_SCHEMA_V1,
            "completed": ["RP1"],
            "receipts": [],
        }
        raw["completed_by_card"] = {"OLD": ["X"]}
        raw["completed_beats"] = {"1": ["F::BE1"]}
        raw["canon_performance_state"] = {
            "OLD": {"completed_segments": ["SEG"], "pending_stop": "STOP"}
        }
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        resumed = proto.FreeStageSession(
            session_id="p2c2-legacy",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["RP1"]
        assert resumed.completed_by_card == {"OLD": ["X"]}
        assert resumed.completed_beats == {"1": ["F::BE1"]}
        assert resumed.canon_performance_state["OLD"]["completed_segments"] == ["SEG"]
        resumed.save()
        rewritten = json.loads(path.read_text(encoding="utf-8"))
        assert rewritten["beat_state"]["schema_version"] == BEAT_STATE_SCHEMA
        assert rewritten["beat_state"]["completed_by_card"] == {"OLD": ["X"]}


def test_session_projections_are_copy_safe_and_snapshot_routes_reducer():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c2-session",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._complete_beat("RP1", turn_no=1, source_kind="fixture")
        scene_id = session._beat_scene_id()
        assert session._snapshot_completed_scene(scene_id) == ["RP1"]
        projected = session.completed_by_card
        projected[scene_id].append("FAKE")
        assert session.completed_by_card[scene_id] == ["RP1"]


def test_authority_map_beat_ancillary_has_only_reducer_production_writers():
    report = _report()
    for fact in ("completed_by_card", "completed_beats", "canon_performance_state"):
        rows = [
            row for row in report["facts"][fact]["writers"]
            if row["classification"] in {"production", "production_tooling"}
        ]
        assert rows, fact
        assert all(row["path"] == "runtime/beat_reducer.py" for row in rows), fact
        assert all(row["symbol"].startswith("BeatReducer.") for row in rows), fact


def test_free_stage_has_no_direct_beat_ancillary_mutation():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = (
        "self.completed_by_card[",
        "self.completed_by_card =",
        "self.completed_beats =",
        "self.canon_performance_state =",
        "self.canon_performance_state.setdefault(",
    )
    for token in forbidden:
        assert token not in source, token
    assert "frame_beat_ledger.mark_done(self.completed_beats" not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
