#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime.run_observation_ledger import ObservationLedger


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_owner_append_is_idempotent_and_copy_only():
    ledger = ObservationLedger()
    assert ledger.append(
        kind="entrust", fact_text="托付已说出", turn=1, scene_id="S1",
        session_id="s", run_id=1,
    ) is True
    assert ledger.append(
        kind="entrust", fact_text="托付已说出", turn=1, scene_id="S1",
        session_id="s", run_id=1,
    ) is False
    rows = ledger.rows()
    rows[0]["fact_text"] = "FAKE"
    assert ledger.rows()[0]["fact_text"] == "托付已说出"


def test_merge_pure_projection_rows_is_idempotent():
    ledger = ObservationLedger()
    rows = [{
        "id": "obs_x", "turn": 1, "scene_id": "S1", "fact_text": "x",
        "kind": "default", "importance0": 2, "importance": 2,
        "caused_by": [], "session_id": "s", "run_id": 1,
    }]
    assert ledger.merge_rows(rows) == 1
    assert ledger.merge_rows(rows) == 0
    assert ledger.rows() == rows


def test_session_projection_is_read_only_and_persists():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="obs-save", state_dir=state_dir,
            autosave=True, load_existing=False, caller=_caller,
        )
        session._append_run_observation(
            kind="entrust", fact_text="托付", turn_no=1,
        )
        visible = session.run_observation_ledger
        visible.append({"id": "FAKE"})
        assert len(session.run_observation_ledger) == 1
        session.save()
        resumed = proto.FreeStageSession(
            session_id="obs-save", state_dir=state_dir,
            autosave=True, load_existing=True, caller=_caller,
        )
        assert resumed.run_observation_ledger == session.run_observation_ledger


def test_player_thought_merges_without_whole_ledger_assignment():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="obs-thought", state_dir=Path(tmp) / "states",
            autosave=False, load_existing=False, caller=_caller,
        )
        result = session.step({"speech": "", "action": "", "thought": "我记住了这件事"})
        assert result["thought_recorded"] is True
        assert session.run_observation_ledger


def test_production_has_no_direct_observation_ledger_writer():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def contains_target(node):
        if isinstance(node, ast.Attribute):
            return (
                isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr == "run_observation_ledger"
            )
        if isinstance(node, (ast.Tuple, ast.List)):
            return any(contains_target(item) for item in node.elts)
        if isinstance(node, ast.Subscript):
            return contains_target(node.value)
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            assert not any(contains_target(target) for target in node.targets)
        elif isinstance(node, ast.AnnAssign):
            assert not contains_target(node.target)
        elif isinstance(node, ast.AugAssign):
            assert not contains_target(node.target)

    assert "_observation_ledger.merge_rows(" in source
    assert "_append_run_observation(" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
