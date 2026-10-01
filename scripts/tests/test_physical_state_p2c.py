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
from runtime.physical_state import DEFAULT_PLAYER_STATE, PhysicalState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_physical_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_physical_state_copy_safe_revision_and_sources():
    state = PhysicalState.empty()
    player = state.player_state
    player["injury"] = "MUTATED"
    assert state.player_state["injury"] == DEFAULT_PLAYER_STATE["injury"]

    frames = {"B.x": {"holding": "I.A", "hands": "holding:I.A"}}
    assert state.replace_body_frames(frames, source_kind="fixture", source_ref="r1")
    frames["B.x"]["holding"] = None
    assert state.body_frames["B.x"]["holding"] == "I.A"
    assert state.revision == 1
    assert state.last_source == {"kind": "fixture", "ref": "r1"}

    assert state.increment_elapsed(2, source_kind="turn_clock", source_ref="turn:1") == 2
    assert state.decrease_convergence(10, source_kind="oob", source_ref="turn:1") == 90
    assert state.player_state["elapsed_minutes"] == 2
    assert state.player_state["convergence_rate"] == 90


def test_snapshot_roundtrip_and_legacy_migration():
    state = PhysicalState.empty()
    state.patch_player(
        {"injury": "测试伤势", "elapsed_minutes": 8},
        source_kind="fixture",
        source_ref="x",
    )
    state.replace_body_frames(
        {"B.x": {"holding": None, "hands": "free"}},
        source_kind="fixture",
        source_ref="y",
    )
    restored = PhysicalState.from_snapshot(state.to_dict())
    assert restored.player_state == state.player_state
    assert restored.body_frames == state.body_frames
    assert restored.revision == state.revision
    assert restored.last_source == state.last_source

    legacy = PhysicalState.from_snapshot(
        None,
        legacy_player_state={"injury": "旧伤"},
        legacy_body_frames={"B.legacy": {"holding": "I.OLD"}},
    )
    assert legacy.player_state["injury"] == "旧伤"
    assert legacy.player_state["convergence_rate"] == 100
    assert legacy.body_frames["B.legacy"]["holding"] == "I.OLD"
    assert legacy.last_source["kind"] == "legacy_snapshot"


def test_session_views_are_copy_safe_and_save_load_keeps_physical_envelope():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-physical",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        player = session.player_state
        player["injury"] = "FAKE"
        frames = session.body_frames
        if frames:
            first = next(iter(frames))
            frames[first]["holding"] = "FAKE"
        assert session.player_state["injury"] != "FAKE"

        session.physical_state.patch_player(
            {"injury": "真实测试伤势"},
            source_kind="fixture",
            source_ref="receipt:test",
        )
        session.save()
        raw = json.loads((state_dir / "p2c-physical.json").read_text(encoding="utf-8"))
        assert raw["physical_state"]["schema_version"] == "free_stage.physical_state.v1"
        assert raw["player_state"]["injury"] == "真实测试伤势"

        resumed = proto.FreeStageSession(
            session_id="p2c-physical",
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.player_state["injury"] == "真实测试伤势"
        assert resumed.physical_state.last_source


def test_pendant_world_projection_stamps_world_receipt_source():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-pendant-physical",
            card_path=card,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        session._finalize_prologue_pendant("accepted", turn_no=2)
        tx = session._world_transaction("ryuya_pendant_disposition")
        receipt_id = tx["receipt"]["receipt_id"]
        assert receipt_id.startswith("world:")
        assert session.physical_state.last_source == {
            "kind": "world_commit",
            "ref": receipt_id,
        }
        assert "古铜色金属挂坠项链" in session.player_state.get("body_props", [])


def test_no_direct_physical_mutation_remains_in_free_stage_source():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    forbidden = (
        "self.player_state =",
        'self.player_state["',
        "self.player_state.setdefault(",
        "self.player_state.update(",
        "self.body_frames =",
    )
    for token in forbidden:
        assert token not in source, token
    assert "self.physical_state.patch_player(" in source
    assert "self.physical_state.replace_body_frames(" in source
    assert "self.physical_state.replace_all(" in source


def test_authority_map_reports_zero_physical_production_and_unknown_writers():
    report = _audit_report()
    for fact in ("player_state", "body_frames"):
        meta = report["facts"][fact]
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
