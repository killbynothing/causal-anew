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

from runtime import scene_fact_state
from runtime.free_stage_prototype import FreeStageSession

CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
AUDIT = ROOT / "scripts" / "audit_runtime_authority.py"


def _caller(**_kwargs):
    return json.dumps(
        {"turns": [], "mh_progress": [], "director_note": ""},
        ensure_ascii=False,
    )


def _report():
    spec = importlib.util.spec_from_file_location("scene_fact_p2c3_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def _production(report, fact):
    return [
        row for row in report["facts"][fact]["writers"]
        if row["classification"] in {"production", "production_tooling"}
    ]


def test_reducer_assert_replace_retract_is_append_only_and_replay_safe():
    first = scene_fact_state.reduce_scene_facts(
        branch_progress=[],
        scene_receipts=[],
        scene_id="S1",
        operation="assert",
        fact_ids=["intervene"],
        owner="player",
        turn_no=1,
        source_kind="player_branch",
        evidence_refs=["player:a1"],
    )
    assert first.branch_progress == ("intervene",)
    assert [row["operation"] for row in first.scene_receipts] == ["assert"]

    replaced = scene_fact_state.reduce_scene_facts(
        branch_progress=first.branch_progress,
        scene_receipts=first.scene_receipts,
        scene_id="S1",
        operation="replace",
        fact_ids=["watch"],
        retract_ids=["intervene"],
        owner="player",
        turn_no=2,
        source_kind="player_branch",
        evidence_refs=["player:a2"],
    )
    assert replaced.branch_progress == ("watch",)
    assert [row["operation"] for row in replaced.scene_receipts] == [
        "assert", "retract", "assert"
    ]
    active = scene_fact_state.active_fact_ids(
        replaced.branch_progress, replaced.scene_receipts
    )
    assert "watch" in active
    assert "intervene" not in active

    retracted = scene_fact_state.reduce_scene_facts(
        branch_progress=replaced.branch_progress,
        scene_receipts=replaced.scene_receipts,
        scene_id="S1",
        operation="retract",
        retract_ids=["watch"],
        owner="system",
        turn_no=3,
        source_kind="route_reset",
    )
    assert retracted.branch_progress == ()
    assert "watch" not in scene_fact_state.active_fact_ids(
        retracted.branch_progress, retracted.scene_receipts
    )
    assert len(retracted.scene_receipts) == len(replaced.scene_receipts) + 1


def test_observe_preserves_legacy_fact_semantics_without_branch_projection():
    observed = scene_fact_state.reduce_scene_facts(
        branch_progress=[],
        scene_receipts=[],
        scene_id="S1",
        operation="observe",
        fact_ids=["RP3"],
        owner="C.ryuya.W1",
        turn_no=4,
        source_kind="observed_progress",
    )
    assert observed.branch_progress == ()
    assert observed.scene_receipts[0]["operation"] == "observe"
    assert "RP3" in scene_fact_state.active_fact_ids(
        observed.branch_progress, observed.scene_receipts
    )

    retry = scene_fact_state.reduce_scene_facts(
        branch_progress=observed.branch_progress,
        scene_receipts=observed.scene_receipts,
        scene_id="S1",
        operation="observe",
        fact_ids=["RP3"],
        owner="C.ryuya.W1",
        turn_no=5,
        source_kind="observed_progress",
    )
    assert retry.scene_receipts == observed.scene_receipts
    assert retry.receipt_ids == ()


def test_legacy_receipt_without_operation_stays_readable_and_can_be_retracted():
    legacy = [{
        "scene_id": "S1",
        "fact_id": "legacy_fact",
        "owner": "player",
        "turn": 1,
        "source_input": "旧输入",
        "source_kind": "player_input",
    }]
    assert "legacy_fact" in scene_fact_state.active_fact_ids([], legacy)
    out = scene_fact_state.reduce_scene_facts(
        branch_progress=[],
        scene_receipts=legacy,
        scene_id="S1",
        operation="retract",
        retract_ids=["legacy_fact"],
        owner="system",
        turn_no=2,
        source_kind="migration_retract",
    )
    assert "legacy_fact" not in scene_fact_state.active_fact_ids(
        out.branch_progress, out.scene_receipts
    )
    assert out.scene_receipts[-1]["operation"] == "retract"


def test_session_player_branch_replace_has_player_action_and_no_receipt_churn():
    with tempfile.TemporaryDirectory() as tmp:
        session = FreeStageSession(
            session_id="scene-fact-p2c3",
            card_path=CARD,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=False,
            load_existing=False,
        )
        assert session._record_player_branch_fact(
            "intervene", turn_no=1, player_input="我过去看看"
        ) is True
        first_receipts = len(session.scene_receipts)
        assert "branch:intervene" in session.player_action_receipts

        # Same active selection is idempotent even on a later turn.
        assert session._record_player_branch_fact(
            "intervene", turn_no=2, player_input="还是过去看看"
        ) is False
        assert len(session.scene_receipts) == first_receipts

        assert session._record_player_branch_fact(
            "watch",
            turn_no=3,
            player_input="那我先看着",
            retract_ids=("intervene",),
        ) is True
        assert "watch" in session.branch_progress
        assert "intervene" not in session.branch_progress
        assert "intervene" not in session._scene_fact_ids()
        ops = [
            (row.get("fact_id"), row.get("operation"))
            for row in session.scene_receipts
            if row.get("fact_id") in {"intervene", "watch"}
        ]
        assert ops == [
            ("intervene", "assert"),
            ("intervene", "retract"),
            ("watch", "assert"),
        ]


def test_session_observe_then_retract_does_not_resurrect_old_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        session = FreeStageSession(
            session_id="scene-fact-replay",
            card_path=CARD,
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=False,
            load_existing=False,
        )
        session._record_scene_receipt(
            "temporary_fact",
            owner="world",
            turn_no=1,
            source_kind="fixture",
        )
        assert "temporary_fact" in session._scene_fact_ids()
        session._reduce_scene_facts(
            "retract",
            retract_ids=("temporary_fact",),
            owner="system",
            turn_no=2,
            source_kind="fixture_retract",
        )
        assert "temporary_fact" not in session._scene_fact_ids()


def test_scene_fact_state_survives_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        session = FreeStageSession(
            session_id="scene-fact-save",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=False,
        )
        session._record_player_branch_fact(
            "route_a", turn_no=1, player_input="走A"
        )
        session._reduce_scene_facts(
            "retract",
            retract_ids=("route_a",),
            owner="system",
            turn_no=2,
            source_kind="fixture_retract",
        )
        session._record_player_branch_fact(
            "route_b", turn_no=3, player_input="改走B"
        )
        session.save()

        resumed = FreeStageSession(
            session_id="scene-fact-save",
            card_path=CARD,
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime.db",
            caller=_caller,
            autosave=True,
            load_existing=True,
        )
        assert resumed.branch_progress == ["route_b"]
        assert resumed.scene_receipts == session.scene_receipts
        assert "route_a" not in resumed._scene_fact_ids()
        assert "route_b" in resumed._scene_fact_ids()


def test_authority_map_has_one_scene_fact_writer_and_no_alias_debt():
    report = _report()
    for fact in ("branch_progress", "scene_receipts"):
        rows = _production(report, fact)
        assert {row["symbol"] for row in rows} == {
            "FreeStageSession._reduce_scene_facts"
        }
        assert report["facts"][fact]["production_writer_count"] == 1
        assert report["facts"][fact]["unknown_alias_count"] == 0


def test_free_stage_has_no_direct_business_mutators():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "self.branch_progress.append(" not in source
    assert "self.scene_receipts.append(" not in source
    assert "apply_offscreen_lives(self.card, target_card, self.branch_progress" not in source


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
