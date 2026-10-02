#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.scene_contract_branch_reducer import SceneContractBranchReducer
from runtime.scene_state import SceneState
from runtime.scene_contracts import register_branch_progress, resolve_active_exit_state


def _binding():
    return {
        "covered": True,
        "node_id": "N1",
        "contract": {
            "path_set": [{"id": "A"}, {"id": "B"}],
            "combine_threshold": 2,
            "exit_states": [{"id": "branched_ready", "branch_gate": "N1"}],
        },
    }


def _report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_scene_contract_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_reducer_is_copy_safe_and_adds_valid_paths_only():
    reducer = SceneContractBranchReducer({"N1": ["A"]})
    leaked = reducer.snapshot()
    leaked["N1"].append("B")
    assert reducer.snapshot() == {"N1": ["A"]}
    assert reducer.add_paths("N1", ["A", "B", "NO"], valid_paths={"A", "B"}) == ["B"]
    assert reducer.snapshot() == {"N1": ["A", "B"]}


def test_scene_state_old_branch_key_migrates_to_new_key_on_save():
    with tempfile.TemporaryDirectory() as tmp:
        old = {
            "scene_id": "S1",
            "run_no": 1,
            "branch_progress": {"N1": ["A"]},
        }
        path = Path(tmp) / "state_1_S1.json"
        path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        with patch.object(SceneState, "get_path", return_value=path),              patch.object(SceneState, "load_all_committed", return_value=[]),              patch.object(SceneState, "load_all_introduced", return_value={}):
            state = SceneState.load(1, "S1")
            assert state.contract_branch_progress == {"N1": ["A"]}
            assert state.branch_progress == {"N1": ["A"]}
            leaked = state.branch_progress
            leaked["N1"].append("B")
            assert state.contract_branch_progress == {"N1": ["A"]}
            state.save()
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["contract_branch_progress"] == {"N1": ["A"]}
        assert "branch_progress" not in saved


def test_contract_helpers_use_new_reducer_and_exit_state():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state_1_S1.json"
        with patch.object(SceneState, "get_path", return_value=path):
            state = SceneState(1, "S1")
            assert register_branch_progress(state, _binding(), ["A"]) == ["A"]
            assert resolve_active_exit_state(state, _binding()) is None
            assert register_branch_progress(state, _binding(), ["A", "B"]) == ["B"]
            exit_state = resolve_active_exit_state(state, _binding())
            assert exit_state["id"] == "branched_ready"
            assert exit_state["activated_paths"] == ["A", "B"]


def test_authority_map_separates_free_stage_and_legacy_contract_fact():
    report = _report()
    branch = [
        row for row in report["facts"]["branch_progress"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    contract = [
        row for row in report["facts"]["contract_branch_progress"]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]
    assert {row["symbol"] for row in branch} == {
        "WorldFactReducer._write_branch_progress"
    }
    assert {row["symbol"] for row in contract} == {
        "SceneContractBranchReducer._write_contract_branch_progress"
    }


def test_legacy_scene_sources_no_longer_write_overloaded_branch_progress():
    for rel in ("runtime/scene_state.py", "runtime/scene_contracts.py", "web/scene_api.py"):
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert ".branch_progress =" not in source
    readonly = (ROOT / "scripts" / "test_world_truth_readonly_runtime.py").read_text(encoding="utf-8")
    assert "session.branch_progress.append" not in readonly


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
