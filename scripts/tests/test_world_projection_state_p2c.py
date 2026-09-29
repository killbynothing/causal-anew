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
from runtime.world_commit import P2A_WORLD_MIGRATION_DEBT
from runtime.world_projection import WorldProjectionState


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _audit():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p2c_projection_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_projection_state_views_are_copy_only():
    state = WorldProjectionState(
        body_frames={"B.x": {"holding": "I.PHONE"}},
        observation_ledger=[{"id": "obs1", "kind": "x"}],
    )
    frames = state.body_frames_view()
    ledger = state.observation_ledger_view()
    frames["B.x"]["holding"] = None
    ledger.clear()
    assert state.body_frames_view()["B.x"]["holding"] == "I.PHONE"
    assert len(state.observation_ledger_view()) == 1


def test_projection_state_observation_replace_and_append_are_owned():
    state = WorldProjectionState()
    state.replace_observation_ledger([{"id": "legacy", "kind": "thought"}])
    state.append_observation(
        kind="entrust",
        fact_text="托付已公开",
        turn=2,
        scene_id="S1",
        session_id="s",
        run_id=1,
    )
    rows = state.observation_ledger_view()
    assert [row["id"] for row in rows][0] == "legacy"
    assert len(rows) == 2
    state.append_observation(
        kind="entrust",
        fact_text="托付已公开",
        turn=99,
        scene_id="S1",
        session_id="s",
        run_id=1,
    )
    assert len(state.observation_ledger_view()) == 2


def test_session_body_and_observation_roundtrip_use_projection_owner():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = proto.FreeStageSession(
            session_id="p2c-projection",
            state_dir=state_dir,
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._append_observation(
            kind="test",
            fact_text="世界投影测试",
            turn=1,
            scene_id=str(session.card.get("scene_id", "")),
            session_id=session.session_id,
            run_id=session.run_no,
        )
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-projection",
            state_dir=state_dir,
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.run_observation_ledger[-1]["fact_text"] == "世界投影测试"
        before = resumed.body_frames
        assert before
        leaked = resumed.body_frames
        first = next(iter(leaked))
        leaked[first]["holding"] = "EVIL"
        assert resumed.body_frames[first].get("holding") != "EVIL"


def test_body_frame_reducer_mutates_only_owner_internal_state():
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
    state = WorldProjectionState()
    state.ensure_body_frames(card, proto.ensure_card_body_frames)
    turns = [{
        "role": "npc",
        "speaker": "川口秋人",
        "cons": "C.akito.WMAIN",
        "text": "好了。",
        "stage": "他把单反放下。",
    }]
    issues = state.settle_body_frames(
        card,
        turns,
        settle_fn=proto.settle_body_frames_from_npc_turns,
        ensure_fn=proto.ensure_card_body_frames,
    )
    assert issues == []
    frames = state.body_frames_view()
    assert frames["B.akito.WMAIN"]["holding"] is None


def test_authority_map_zeroes_projection_direct_writers_and_aliases():
    report = _audit()
    for fact in ("run_observation_ledger", "body_frames"):
        rows = [
            row for row in report["facts"][fact]["writers"]
            if row["classification"] in {"production", "production_tooling", "unknown_alias"}
        ]
        assert rows == [], (fact, rows)
    debt = set(P2A_WORLD_MIGRATION_DEBT)
    assert "run_observation_ledger" not in debt
    assert "body_frames" not in debt
    assert {"branch_progress", "player_state", "world_cursor"} <= debt


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
