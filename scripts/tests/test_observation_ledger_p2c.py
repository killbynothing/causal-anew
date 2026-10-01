#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.run_observation_ledger import ObservationLedgerState
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_observation_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_state_append_is_idempotent_and_copy_safe():
    state = ObservationLedgerState.empty()
    assert state.append(
        kind="entrust",
        fact_text="托付已说出",
        turn=3,
        scene_id="S1",
    )
    assert not state.append(
        kind="entrust",
        fact_text="托付已说出",
        turn=99,
        scene_id="S1",
    )
    view = state.rows
    view[0]["fact_text"] = "MUTATED"
    assert state.rows[0]["fact_text"] == "托付已说出"


def test_state_replace_and_boost_are_owned_mutations():
    state = ObservationLedgerState.from_snapshot([
        {
            "id": "obs_x",
            "turn": 1,
            "scene_id": "S",
            "fact_text": "x",
            "kind": "default",
            "importance0": 2,
            "importance": 2,
            "caused_by": [],
            "session_id": "",
            "run_id": 1,
        }
    ])
    assert state.boost("obs_x", 3, caused_by_event="E1")
    assert state.rows[0]["importance"] == 5
    assert state.rows[0]["caused_by"] == ["E1"]
    state.replace([])
    assert state.rows == []


def test_session_observation_view_save_load_and_reset():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-observation",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        assert session._observe(
            kind="fixture",
            fact_text="可见事实",
            turn=1,
            scene_id="S",
        )
        view = session.run_observation_ledger
        view.append({"id": "fake"})
        assert len(session.run_observation_ledger) == 1
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p2c-observation",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.run_observation_ledger[0]["fact_text"] == "可见事实"
        resumed.reset()
        assert resumed.run_observation_ledger == []


def test_no_direct_observation_ledger_mutation_remains_in_free_stage():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    direct = re.findall(
        r"self\.run_observation_ledger(?:\s*=|\.append\(|\.extend\(|\.remove\(|\.clear\()",
        source,
    )
    assert direct == []


def test_authority_map_reports_zero_observation_production_writers():
    report = _audit_report()
    meta = report["facts"]["run_observation_ledger"]
    rows = [
        row for row in meta["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    assert meta["production_writer_count"] == 0, rows
    assert rows == [], rows


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
