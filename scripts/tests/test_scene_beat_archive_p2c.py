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

from runtime import free_stage_prototype as proto
from runtime.beat_reducer import SceneBeatArchive


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_scene_archive_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_archive_copy_safe_retry_and_source():
    archive = SceneBeatArchive.empty()
    assert archive.record(
        "S1", ["A", "B", "A"],
        source_kind="fixture",
        source_ref="turn:3",
        turn=3,
    )
    view = archive.completed_by_card
    view["S1"].append("FAKE")
    assert archive.completed_by_card["S1"] == ["A", "B"]
    before = archive.to_dict()
    assert not archive.record(
        "S1", ["A", "B"],
        source_kind="later_retry",
        source_ref="turn:4",
        turn=4,
    )
    assert archive.to_dict() == before
    assert archive.sources["S1"]["source_kind"] == "fixture"


def test_archive_preserves_legacy_overwrite_semantics():
    archive = SceneBeatArchive.empty()
    archive.record("S1", ["A", "B"], source_kind="first", turn=1)
    assert archive.record("S1", ["A"], source_kind="revisit", turn=2)
    assert archive.completed_by_card["S1"] == ["A"]
    assert archive.sources["S1"]["source_kind"] == "revisit"


def test_legacy_migration_and_snapshot_roundtrip():
    legacy = SceneBeatArchive.from_snapshot(
        None,
        legacy_completed_by_card={"S1": ["A"], "S2": ["B", "C"]},
    )
    assert legacy.completed_by_card == {"S1": ["A"], "S2": ["B", "C"]}
    assert legacy.sources["S1"]["source_kind"] == "legacy_snapshot"
    restored = SceneBeatArchive.from_snapshot(
        legacy.to_dict(),
        legacy_completed_by_card={},
    )
    assert restored.to_dict() == legacy.to_dict()


def test_session_archive_save_load_and_copy_safe_view():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-scene-archive",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session.completed = ["X", "Y"]
        scene_id = str(session.card.get("scene_id", session.card_path))
        assert session._archive_scene_beats(
            scene_id,
            source_kind="fixture",
            source_ref="case:1",
            turn_no=1,
        )
        view = session.completed_by_card
        view[scene_id].append("FAKE")
        assert session.completed_by_card[scene_id] == ["X", "Y"]
        session.save()
        raw = json.loads((state_dir / "p2c-scene-archive.json").read_text(encoding="utf-8"))
        assert raw["scene_beat_archive"]["schema_version"] == "free_stage.scene_beat_archive.v1"
        resumed = proto.FreeStageSession(
            session_id="p2c-scene-archive",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed_by_card == session.completed_by_card
        assert resumed.scene_beat_archive.sources[scene_id]["source_ref"] == "case:1"


def test_no_direct_completed_by_card_mutation_remains():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.completed_by_card =" not in source
    assert "self.completed_by_card[" not in source
    assert "self._archive_scene_beats(" in source


def test_authority_map_reports_zero_archive_production_and_unknown_writers():
    report = _audit_report()
    meta = report["facts"]["completed_by_card"]
    rows = [
        row for row in meta["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert meta["production_writer_count"] == 0, rows
    assert meta["unknown_alias_count"] == 0, rows
    assert rows == [], rows


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
