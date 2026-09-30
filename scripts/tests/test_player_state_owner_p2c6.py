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
from runtime.player_state import DEFAULT_PLAYER_STATE, PlayerStateOwner
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT, P2A_WORLD_MIGRATED_FACTS


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c6_authority_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_owner_default_and_view_are_copy_safe():
    owner = PlayerStateOwner()
    assert owner.view() == DEFAULT_PLAYER_STATE
    leaked = owner.view()
    leaked["injury"] = "EVIL"
    leaked["body_props"] = ["EVIL"]
    assert owner.view()["injury"] == "正常/良好"
    assert "body_props" not in owner.view()


def test_owner_preserves_existing_runtime_semantics():
    owner = PlayerStateOwner({"elapsed_minutes": 5, "convergence_rate": 7, "custom": {"x": 1}})
    assert owner.advance_elapsed() == 7
    assert owner.reduce_convergence(10) == 0
    owner.apply_offscreen({"injury": "离线伤势", "elapsed_minutes": 999})
    state = owner.view()
    assert state["elapsed_minutes"] == 7
    assert state["injury"] == "离线伤势"
    assert state["custom"] == {"x": 1}
    owner.reset_elapsed()
    assert owner.view()["elapsed_minutes"] == 0


def test_branch_status_projection_matches_legacy_rules():
    owner = PlayerStateOwner()
    state = owner.project_branch_status(["choiceA_brace"], ended=False)
    assert state["injury"] == "肋骨骨折 (重伤残血)"
    assert state["status"] == "行动中"

    owner.reset()
    state = owner.project_branch_status(["B1_dog"], ended=True)
    assert state["injury"] == "无明显外伤"
    assert state["status"] == "已完成"


def test_session_player_state_is_copy_only_and_save_load_owned():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c6-roundtrip",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        leaked = session.player_state
        leaked["elapsed_minutes"] = 9000
        assert session.player_state["elapsed_minutes"] == 0
        session._advance_player_elapsed()
        assert session.player_state["elapsed_minutes"] == 2
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c6-roundtrip",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.player_state["elapsed_minutes"] == 2


def test_pendant_world_projection_replaces_player_state_through_owner():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c6-pendant",
            card_path=card,
            state_dir=Path(tmp) / "states",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._finalize_prologue_pendant("accepted", turn_no=2)
        assert "古铜色金属挂坠项链" in session.player_state.get("body_props", [])
        leaked = session.player_state
        leaked["body_props"].clear()
        assert "古铜色金属挂坠项链" in session.player_state.get("body_props", [])


def test_session_facades_preserve_convergence_offscreen_branch_and_reset_elapsed():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c6-facades",
            state_dir=Path(tmp) / "states",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._advance_player_elapsed()
        session._advance_player_elapsed()
        assert session.player_state["elapsed_minutes"] == 4
        session._reduce_player_convergence()
        assert session.player_state["convergence_rate"] == 90
        session._apply_offscreen_player_state({"injury": "场外伤", "elapsed_minutes": 999})
        assert session.player_state["elapsed_minutes"] == 4
        assert session.player_state["injury"] == "场外伤"
        session._project_player_branch_status(["choiceA_brace"], ended=False)
        assert session.player_state["injury"] == "肋骨骨折 (重伤残血)"
        assert session.player_state["status"] == "行动中"
        session._reset_player_elapsed()
        assert session.player_state["elapsed_minutes"] == 0


def test_authority_map_zeroes_player_state_writers_and_aliases():
    report = _audit()
    meta = report["facts"]["player_state"]
    rows = [
        row for row in meta["writers"]
        if row["classification"] in {"production", "production_tooling", "unknown_alias"}
    ]
    assert rows == [], rows
    assert meta["production_writer_count"] == 0
    assert meta["unknown_alias_count"] == 0
    assert set(P2A_WORLD_MIGRATION_DEBT) == set()
    assert {"player_state", "world_cursor"} <= set(P2A_WORLD_MIGRATED_FACTS)


def test_free_stage_has_no_direct_player_state_mutation():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = (
        "self.player_state =",
        "self.player_state[",
        "self.player_state.update(",
        "self.player_state.setdefault(",
    )
    for token in forbidden:
        assert token not in source, token
    assert "def _advance_player_elapsed(" in source
    assert "def _project_player_branch_status(" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
