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
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT, P2A_WORLD_MIGRATED_FACTS
from runtime.world_projection import BodyObservationState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c5_authority_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_owner_views_are_copy_only():
    owner = BodyObservationState(
        body_frames={"B.x": {"holding": "I.PHONE"}},
        observation_ledger=[{"id": "obs:1", "kind": "x"}],
    )
    frames = owner.body_frames_view()
    ledger = owner.observation_ledger_view()
    frames["B.x"]["holding"] = None
    ledger.clear()
    assert owner.body_frames_view()["B.x"]["holding"] == "I.PHONE"
    assert len(owner.observation_ledger_view()) == 1


def test_owner_observation_append_replace_and_body_settle():
    owner = BodyObservationState()
    owner.replace_observation_ledger([{"id": "legacy", "kind": "legacy"}])
    owner.append_observation(
        kind="entrust",
        fact_text="托付已公开",
        turn=2,
        scene_id="S1",
        session_id="s",
        run_id=1,
    )
    rows = owner.observation_ledger_view()
    assert rows[0]["id"] == "legacy"
    assert len(rows) == 2
    card = {
        "scene_id": "OTHER",
        "present": ["C.akito.WMAIN"],
        "persona_cards": {
            "C.akito.WMAIN": {
                "name": "川口秋人",
                "scene_working_memory": {"body_state": "手里拿着单反"},
            }
        },
    }
    owner.ensure_body_frames(card, proto.ensure_card_body_frames)
    issues = owner.settle_body_frames(
        card,
        [{"role": "npc", "speaker": "川口秋人", "cons": "C.akito.WMAIN",
          "text": "好了。", "stage": "他把单反放下。"}],
        settle_fn=proto.settle_body_frames_from_npc_turns,
        ensure_fn=proto.ensure_card_body_frames,
    )
    assert issues == []
    assert owner.body_frames_view()["B.akito.WMAIN"]["holding"] is None


def test_session_roundtrip_and_views_do_not_leak():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c5-roundtrip", state_dir=state_dir,
            autosave=True, load_existing=False, caller=_caller,
        )
        session._append_observation(
            kind="test", fact_text="P2c5观察", turn=1,
            scene_id=str(session.card.get("scene_id", "")),
            session_id=session.session_id, run_id=session.run_no,
        )
        leaked = session.body_frames
        body_id = next(iter(leaked))
        leaked[body_id]["holding"] = "EVIL"
        assert session.body_frames[body_id].get("holding") != "EVIL"
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c5-roundtrip", state_dir=state_dir,
            autosave=True, load_existing=True, caller=_caller,
        )
        assert resumed.run_observation_ledger[-1]["fact_text"] == "P2c5观察"
        assert resumed.body_frames == session.body_frames


def test_thought_ingest_routes_back_through_owner():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c5-thought", state_dir=Path(tmp) / "states",
            autosave=False, load_existing=False, caller=_caller,
        )
        result = session.step({"speech": "", "action": "", "thought": "我得记住这件事"})
        assert result["thought_recorded"] is True
        assert session.run_observation_ledger
        leaked = session.run_observation_ledger
        leaked.clear()
        assert session.run_observation_ledger


def test_world_projection_updates_owner_while_player_state_stays_debt():
    card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c5-pendant", card_path=card,
            state_dir=Path(tmp) / "states", autosave=False,
            load_existing=False, caller=_caller,
        )
        session._finalize_prologue_pendant("accepted", turn_no=2)
        tx = session._world_transaction("ryuya_pendant_disposition")
        assert "古铜色金属挂坠项链" in session.player_state.get("body_props", [])
        assert session.body_frames["B.ryuya.WMAIN"]["holding"] is None
        assert session.run_observation_ledger[-1]["world_receipt_id"] == tx["receipt"]["receipt_id"]
        assert set(P2A_WORLD_MIGRATION_DEBT) == {"world_cursor"}
        assert {
            "body_frames", "run_observation_ledger", "player_state"
        } <= set(P2A_WORLD_MIGRATED_FACTS)


def test_authority_map_zeroes_body_and_observation_writers_and_aliases():
    report = _audit()
    for fact in ("body_frames", "run_observation_ledger"):
        meta = report["facts"][fact]
        rows = [
            row for row in meta["writers"]
            if row["classification"] in {"production", "production_tooling", "unknown_alias"}
        ]
        assert rows == [], (fact, rows)
        assert meta["production_writer_count"] == 0
        assert meta["unknown_alias_count"] == 0


def test_free_stage_has_no_direct_body_or_observation_assignment():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.body_frames =" not in source
    assert "self.run_observation_ledger =" not in source
    assert "_ledger_append(" not in source
    assert "def _append_observation(" in source
    assert "def _settle_body_frames(" in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
