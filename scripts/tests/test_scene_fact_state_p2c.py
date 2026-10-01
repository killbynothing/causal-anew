#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.scene_fact_state import SceneFactState
from runtime import free_stage_prototype as proto


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def test_assert_revoke_is_append_only_and_projection_changes():
    state = SceneFactState()
    assert state.assert_fact(
        "route_a", scene_id="S1", scene_instance_id="S1:visit:1",
        owner="player", turn=1, source_kind="player_action", source_ref="player:r1",
    )
    before = state.events()
    assert state.active_facts() == ["route_a"]
    assert state.revoke_fact(
        "route_a", scene_id="S1", scene_instance_id="S1:visit:1",
        owner="player", turn=2, source_kind="branch_replace", source_ref="player:r2",
    )
    assert state.active_facts() == []
    after = state.events()
    assert len(after) == len(before) + 1
    assert after[0] == before[0]
    assert after[0]["op"] == "assert"
    assert after[1]["op"] == "revoke"


def test_observation_dedups_per_scene_instance_but_revisit_gets_new_event():
    state = SceneFactState()
    assert state.observe_fact(
        "seen", scene_id="S1", scene_instance_id="S1:visit:1",
        owner="player", turn=1, source_kind="player_input", source_ref="input:1",
    )
    assert not state.observe_fact(
        "seen", scene_id="S1", scene_instance_id="S1:visit:1",
        owner="player", turn=2, source_kind="player_input", source_ref="input:2",
    )
    assert state.observe_fact(
        "seen", scene_id="S1", scene_instance_id="S1:visit:2",
        owner="player", turn=3, source_kind="player_input", source_ref="input:3",
    )
    rows = state.observations()
    assert len(rows) == 2
    assert rows[0]["event_id"] != rows[1]["event_id"]
    assert rows[0]["scene_instance_id"] != rows[1]["scene_instance_id"]


def test_legacy_migration_preserves_active_and_observation_without_player_action():
    state = SceneFactState.from_legacy(
        branch_progress=["a", "b"],
        scene_receipts=[{
            "scene_id": "S1", "fact_id": "a", "owner": "player",
            "turn": 4, "source_kind": "player_input", "source_input": "选A",
        }],
        current_scene_id="S1",
        current_scene_instance_id="S1:visit:1",
    )
    assert state.active_facts() == ["a", "b"]
    assert state.observations()[0]["fact_id"] == "a"
    blob = json.dumps(state.to_dict(), ensure_ascii=False)
    assert "legacy_snapshot" in blob
    assert "PlayerAction" not in blob
    assert "player_action_receipts" not in blob


def test_free_stage_branch_and_receipts_are_read_only_projections():
    source = inspect.getsource(proto.FreeStageSession)
    assert "self.branch_progress.append(" not in source
    assert "self.branch_progress.extend(" not in source
    assert "self.branch_progress =" not in source
    assert "self.scene_receipts.append(" not in source
    assert "self.scene_receipts =" not in source

    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p2c-facts",
            card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=False,
            load_existing=False,
            caller=_caller,
        )
        assert session._assert_branch_fact(
            "fixture_fact", owner="world", turn_no=1,
            source_kind="test_fixture", source_ref="test:fixture",
        )
        assert session.branch_progress == ["fixture_fact"]
        assert session._record_scene_receipt(
            "fixture_fact", owner="world", turn_no=1,
            source_kind="test_fixture", source_ref="test:fixture",
        )
        assert session.scene_receipts[0]["fact_id"] == "fixture_fact"
        assert session._revoke_branch_fact(
            "fixture_fact", owner="world", turn_no=2,
            source_kind="test_fixture", source_ref="test:revoke",
        )
        assert session.branch_progress == []
        assert [row["op"] for row in session.scene_fact_state.events()] == [
            "assert", "observe", "revoke"
        ]


def test_new_scene_fact_state_beats_stale_domain_route_ledger_on_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
        session = proto.FreeStageSession(
            session_id="p2c-domain",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._assert_branch_fact(
            "new_authority", owner="world", turn_no=1,
            source_kind="test_fixture", source_ref="test:new",
        )
        session.save()
        path = session.runtime_store.state_path
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["domain_state"]["route_ledger"] = ["stale_domain_fact"]
        raw["branch_progress"] = ["stale_legacy_fact"]
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        resumed = proto.FreeStageSession(
            session_id="p2c-domain",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.branch_progress == ["new_authority"]
        assert "stale_domain_fact" not in resumed.branch_progress
        assert "stale_legacy_fact" not in resumed.branch_progress


def test_scene_fact_state_survives_save_load_exactly():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        card = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
        session = proto.FreeStageSession(
            session_id="p2c-fact-save",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=False,
            caller=_caller,
        )
        session._record_player_branch_fact(
            "route_fixture", turn_no=1, player_input="走这边",
        )
        before = session.scene_fact_state.to_dict()
        session.save()
        resumed = proto.FreeStageSession(
            session_id="p2c-fact-save",
            card_path=card,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            autosave=True,
            load_existing=True,
            caller=_caller,
        )
        assert resumed.scene_fact_state.to_dict() == before
        assert resumed.branch_progress == ["route_fixture"]
        assert resumed.scene_receipts[0]["fact_id"] == "route_fixture"


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
