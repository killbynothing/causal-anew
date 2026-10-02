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

from runtime.beat_reducer import BeatReducer
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _authority_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_beat_authority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_reducer_copy_safe_and_semantics():
    reducer = BeatReducer(["A"])
    view = reducer.snapshot()
    view.append("B")
    assert reducer.snapshot() == ["A"]
    assert reducer.complete("A") is False
    assert reducer.complete("B") is True
    assert reducer.snapshot() == ["A", "B"]
    reducer.extend(["B", "C"])
    assert reducer.snapshot() == ["A", "B", "B", "C"]
    reducer.replace(["X", "Y"])
    assert reducer.snapshot() == ["X", "Y"]
    reducer.clear()
    assert reducer.snapshot() == []


def test_session_completed_projection_cannot_be_mutated_by_list_alias():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-beat",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session.completed = ["RP1"]
        leaked = session.completed
        leaked.append("RP2")
        assert session.completed == ["RP1"]
        session._beat_reducer.complete("RP2")
        assert session.completed == ["RP1", "RP2"]


def test_session_completed_save_load_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-beat-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session.completed = ["RP1", "RP2"]
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-beat-save",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.completed == ["RP1", "RP2"]
        copy_view = resumed.completed
        copy_view.clear()
        assert resumed.completed == ["RP1", "RP2"]


def test_authority_map_completed_is_one_writer():
    report = _authority_report()
    rows = [
        row for row in report["facts"]["completed"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    assert {row["symbol"] for row in rows} == {"BeatReducer._write_completed"}
    assert report["facts"]["completed"]["production_writer_count"] == 1


def test_free_stage_source_has_no_direct_completed_mutators():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.completed.append" not in source
    assert "self.completed.extend" not in source
    assert "self.completed =" not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
