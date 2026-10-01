#!/usr/bin/env python3
from __future__ import annotations

import copy
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime import world_commit

CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _session(tmp: str, session_id: str = "p2c-facts", *, autosave: bool = False, load_existing: bool = False):
    return proto.FreeStageSession(
        session_id=session_id,
        card_path=CARD,
        state_dir=Path(tmp) / "states",
        runtime_state_path=Path(tmp) / "runtime.db",
        autosave=autosave,
        load_existing=load_existing,
        caller=_caller,
        intent_caller=None,
    )


def test_business_paths_no_longer_mutate_compat_lists_directly():
    source = inspect.getsource(proto.FreeStageSession)
    assert "self.branch_progress.append(" not in source
    assert "self.scene_receipts.append(" not in source

    branch_assigners = []
    receipt_assigners = []
    for name in dir(proto.FreeStageSession):
        value = getattr(proto.FreeStageSession, name, None)
        if not callable(value):
            continue
        try:
            body = inspect.getsource(value)
        except (OSError, TypeError):
            continue
        if "self.branch_progress =" in body:
            branch_assigners.append(name)
        if "self.scene_receipts =" in body:
            receipt_assigners.append(name)
    assert branch_assigners == ["_sync_scene_fact_projections"]
    assert receipt_assigners == ["_sync_scene_fact_projections"]


def test_player_branch_action_is_visit_scoped_and_projects_scene_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        assert session._record_player_branch_fact(
            "route_left", turn_no=1, player_input="走左边"
        ) is True
        assert session.branch_progress == ["route_left"]
        assert [row["fact_id"] for row in session.scene_receipts] == ["route_left"]
        assert len(session.player_action_receipts) == 1
        first_action_id = next(iter(session.player_action_receipts))
        assert session._current_runtime_scope().scene_instance_id in first_action_id

        session.card_history.append(str(session.card.get("scene_id")))
        assert session._record_player_branch_fact(
            "route_left", turn_no=2, player_input="还是走左边"
        ) is False
        assert len(session.player_action_receipts) == 2
        assert len(session.scene_receipts) == 2
        assert session.scene_receipts[0]["scene_instance_id"] != session.scene_receipts[1]["scene_instance_id"]


def test_revoke_keeps_history_and_projection_can_reassert():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        assert session._assert_branch_fact(
            "left", turn_no=1, owner="player", source_kind="test",
            source_refs=("test:1",),
        ) is True
        before_id = session.scene_fact_ledger["event_order"][0]
        assert session._revoke_branch_facts(
            ("left",), turn_no=2, owner="world", source_kind="exclusive",
            source_refs=("test:2",),
        ) == ("left",)
        assert "left" not in session.branch_progress
        assert session.scene_fact_ledger["events"][before_id]["operation"] == "assert"
        assert session._assert_branch_fact(
            "left", turn_no=3, owner="player", source_kind="test",
            source_refs=("test:3",),
        ) is True
        assert session.branch_progress == ["left"]
        ops = [
            session.scene_fact_ledger["events"][eid]["operation"]
            for eid in session.scene_fact_ledger["event_order"]
        ]
        assert ops == ["assert", "revoke", "assert"]


def test_legacy_save_migrates_once_and_new_save_carries_authority_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        state_dir.mkdir(parents=True, exist_ok=True)
        seed = _session(tmp, session_id="legacy", autosave=False)
        payload = seed._state_payload()
        payload.pop("scene_fact_ledger", None)
        payload["branch_progress"] = ["legacy_branch"]
        payload["scene_receipts"] = [{
            "scene_id": str(seed.card.get("scene_id")),
            "fact_id": "legacy_receipt",
            "owner": "player",
            "turn": 2,
            "source_input": "旧输入",
            "source_kind": "player_input",
            "receipt_id": "scene:legacy-fixed",
        }]
        domain = dict(payload.get("domain_state") or {})
        domain["route_ledger"] = ["legacy_branch"]
        payload["domain_state"] = domain
        (state_dir / "legacy.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        loaded = _session(tmp, session_id="legacy", autosave=True, load_existing=True)
        assert loaded.branch_progress == ["legacy_branch"]
        assert {row["fact_id"] for row in loaded.scene_receipts} == {"legacy_receipt"}
        assert loaded.scene_fact_ledger["event_order"]
        migrated = copy.deepcopy(loaded.scene_fact_ledger)
        loaded.save()

        resumed = _session(tmp, session_id="legacy", autosave=True, load_existing=True)
        assert resumed.scene_fact_ledger == migrated
        assert resumed.branch_progress == ["legacy_branch"]
        assert resumed.scene_receipts[0]["receipt_id"] == "scene:legacy-fixed"


def test_scene_fact_ids_are_ledger_projection_not_union_of_two_authorities():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        row = session._record_scene_receipt(
            "visible_fact",
            owner="player",
            turn_no=1,
            source_input="看见了",
        )
        session._assert_branch_fact(
            "route_fact",
            turn_no=1,
            owner="player",
            source_kind="test",
            source_refs=(row["receipt_id"],),
        )
        assert session._scene_fact_ids() == {"visible_fact", "route_fact"}
        assert session._scene_fact_ids() == world_commit.active_scene_fact_ids(
            session.scene_fact_ledger
        )


def test_deferred_exit_marker_is_not_written_before_world_transaction():
    source = inspect.getsource(proto.FreeStageSession._maybe_transition)
    first_finalize = source.index('self._finalize_prologue_pendant("deferred"')
    first_marker = source.index('self._assert_branch_fact(\n                    "prologue_receipt_deferred"', first_finalize)
    assert first_finalize < first_marker
    assert 'self.branch_progress.append("prologue_receipt_deferred")' not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
