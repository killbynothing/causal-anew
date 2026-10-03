#!/usr/bin/env python3
from __future__ import annotations

import ast
import inspect
import json
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.actor_mind import ActorMindState, build_turn_working_context
from runtime.causal_protocol import RuntimeScope, resolve_observed_event
from runtime import free_stage_prototype as proto

C16_CARD = ROOT / "runtime" / "free_stage_card_16zhong_gate.json"
RYUYA_CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


def _caller(**kwargs):
    return json.dumps({"turns": [], "mh_progress": [], "director_note": ""}, ensure_ascii=False)


def _session(tmp: str, *, card_path: Path = C16_CARD, session_id: str = "p3b-mind") -> proto.FreeStageSession:
    return proto.FreeStageSession(
        session_id=session_id,
        card_path=card_path,
        state_dir=Path(tmp) / "states",
        runtime_state_path=Path(tmp) / "runtime.db",
        autosave=False,
        load_existing=False,
        caller=_caller,
    )


def _lifecycle_kinds(fn) -> list[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "_record_scene_lifecycle_mind_receipts":
            continue
        for kw in node.keywords:
            if kw.arg == "event_kind" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                out.append(kw.value.value)
    return out


def test_receipt_is_bound_to_one_receiving_consciousness():
    state = ActorMindState.empty()
    state.ensure("C.a.W1", {"inner_state": {"want_now": "观察"}})
    state.ensure("C.b.W1", {"inner_state": {"want_now": "观察"}})
    receipt = resolve_observed_event(
        recipient_cons="C.a.W1",
        scene_id="S1",
        turn=1,
        source_actor="C.b.W1",
        source_ref="fixture:b:1",
        event_kind="actor_public_enactment",
        outcome="spoke",
    ).to_dict()

    assert state.apply_receipt("C.a.W1", receipt) is True
    assert state.get("C.a.W1")["appraisal_state"]["last_goal_impact"] == "observed_other"
    before_b = state.get("C.b.W1")
    assert state.apply_receipt("C.b.W1", receipt) is False
    assert state.get("C.b.W1") == before_b


def test_mind_receipt_scope_separates_run_worldline_and_replay():
    base_args = dict(
        recipient_cons="C.a.W1",
        scene_id="S1",
        turn=1,
        source_actor="player",
        source_ref="player:signal:1",
        event_kind="player_public_signal",
        outcome="speech",
    )
    scope_run1 = RuntimeScope(
        worldline="WMAIN", run=1, ch_anchor=1,
        session_id="s1", scene_instance_id="S1:visit:1",
    )
    scope_run2 = RuntimeScope(
        worldline="WMAIN", run=2, ch_anchor=1,
        session_id="s1", scene_instance_id="S1:visit:1",
    )
    scope_alt = RuntimeScope(
        worldline="WALT", run=1, ch_anchor=1,
        session_id="s1", scene_instance_id="S1:visit:1",
    )
    r1 = resolve_observed_event(**base_args, scope=scope_run1).to_dict()
    r2 = resolve_observed_event(**base_args, scope=scope_run2).to_dict()
    r3 = resolve_observed_event(**base_args, scope=scope_alt).to_dict()
    assert len({r1["receipt_id"], r2["receipt_id"], r3["receipt_id"]}) == 3
    assert r1["scope"]["run"] == 1
    assert r3["scope"]["worldline"] == "WALT"

    matching = ActorMindState.empty()
    matching.ensure("C.a.W1", {"inner_state": {"want_now": "观察"}})
    assert matching.apply_receipt("C.a.W1", r1, expected_scope=scope_run1) is True

    mismatched = ActorMindState.empty()
    mismatched.ensure("C.a.W1", {"inner_state": {"want_now": "观察"}})
    before = mismatched.get("C.a.W1")
    assert mismatched.apply_receipt("C.a.W1", r1, expected_scope=scope_run2) is False
    assert mismatched.get("C.a.W1") == before


def test_untrusted_legacy_mind_is_quarantined_and_reseeded_without_data_loss():
    raw = {
        "C.a.W1": {
            "schema_version": "free_stage.actor_mind.v2",
            "actor_cons": "C.other.W1",
            "stable_profile": {"source_refs": []},
            "motivational_state": {
                "active_goals": ["FAKE LEGACY GOAL"],
                "commitments": ["FAKE LEGACY COMMITMENT"],
            },
        }
    }
    state = ActorMindState.from_snapshot(raw)
    assert state.get("C.a.W1") is None
    report = state.migration_report
    assert report == [
        {
            "actor_cons": "C.a.W1",
            "status": "legacy_unresolved",
            "reason_codes": ["actor_cons_mismatch", "missing_source_refs"],
            "recovery": "reseed_from_current_persona_projection",
        }
    ]
    audit = state.legacy_audit
    assert audit["C.a.W1"]["raw"]["motivational_state"]["commitments"] == [
        "FAKE LEGACY COMMITMENT"
    ]

    seeded = state.ensure(
        "C.a.W1",
        {
            "inner_state": {"want_now": "当前有来源目标"},
            "scene_working_memory": {"commitments": ["当前有来源承诺"]},
        },
        persona_core_hash="current-persona",
    )
    assert seeded["motivational_state"]["active_goals"] == ["当前有来源目标"]
    assert seeded["motivational_state"]["commitments"] == ["当前有来源承诺"]
    assert "FAKE" not in json.dumps(seeded, ensure_ascii=False)

    resumed = ActorMindState.from_snapshot(
        state.minds,
        legacy_audit=state.legacy_audit,
    )
    assert resumed.legacy_audit == state.legacy_audit
    assert resumed.migration_report == state.migration_report


def test_working_context_rebuild_ignores_freeform_cache_as_authority():
    state = ActorMindState.empty()
    mind = state.ensure(
        "C.a.W1",
        {
            "inner_state": {"want_now": "看清现场", "stance_to_player": "谨慎"},
            "scene_working_memory": {"goals": ["先看清现场"]},
        },
    )
    rebuilt = build_turn_working_context(
        mind,
        {"want_now": "看清现场", "stance_to_player": "谨慎"},
        observed_player={"speech": "你好"},
        turn=3,
        current_ephemeral={
            "want_now": "FAKE CACHE GOAL",
            "active_goals": ["FAKE"],
            "pending_concerns": ["current-turn-only"],
        },
    )
    assert rebuilt["want_now"] == "先看清现场"
    assert rebuilt["active_goals"] == ["先看清现场"]
    assert rebuilt["pending_concerns"] == ["current-turn-only"]
    assert "FAKE" not in json.dumps(rebuilt, ensure_ascii=False)


def test_scene_receipt_updates_scene_goal_but_preserves_commitments():
    state = ActorMindState.empty()
    state.ensure(
        "C.a.W1",
        {
            "inner_state": {"want_now": "旧目标"},
            "scene_working_memory": {
                "goals": ["旧场目标"],
                "commitments": ["已经答应的事"],
            },
        },
    )
    receipt = resolve_observed_event(
        recipient_cons="C.a.W1",
        scene_id="S2",
        turn=5,
        source_actor="world",
        source_ref="scene:S2:visit:1:enter",
        event_kind="scene_enter",
        outcome="S2",
        scene_effects=("scene_enter",),
        public_dialogue_count=0,
    ).to_dict()
    assert state.apply_scene_receipt(
        "C.a.W1",
        receipt,
        {
            "inner_state": {"want_now": "新目标"},
            "scene_working_memory": {
                "goals": ["新场目标"],
                "commitments": ["新场已有承诺"],
            },
        },
    )
    motivation = state.get("C.a.W1")["motivational_state"]
    assert motivation["active_goals"] == ["新场目标"]
    assert motivation["commitments"] == ["已经答应的事", "新场已有承诺"]


def test_silent_working_rebuild_does_not_mutate_persistent_mind():
    state = ActorMindState.empty()
    state.ensure(
        "C.a.W1",
        {
            "inner_state": {"want_now": "继续观察"},
            "scene_working_memory": {"commitments": ["记住承诺"]},
        },
    )
    before = state.get("C.a.W1")
    for turn in (2, 3):
        build_turn_working_context(
            state.get("C.a.W1"),
            {"want_now": "继续观察"},
            observed_player={},
            turn=turn,
        )
    assert state.get("C.a.W1") == before


def test_c16_subtle_watch_only_updates_actor_who_can_observe_it():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        assert all(
            session.actor_minds[cons]["appraisal_state"]["last_event_kind"] == "scene_enter"
            for cons in ("C.zhangchen.WMAIN", "C.banbo.WMAIN", "C.yuxuan.WMAIN")
        )
        ids = session._record_player_visible_mind_receipts(
            session.card,
            {"speech": "", "action": "我站在旁边观察，不动"},
            1,
        )
        assert len(ids) == 1
        assert session.actor_minds["C.zhangchen.WMAIN"]["appraisal_state"]["last_event_kind"] == "player_public_signal"
        assert session.actor_minds["C.banbo.WMAIN"]["appraisal_state"]["last_event_kind"] == "scene_enter"
        assert session.actor_minds["C.yuxuan.WMAIN"]["appraisal_state"]["last_event_kind"] == "scene_enter"


def test_private_player_thought_never_creates_actor_mind_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        before = {
            cons: len(mind["appraisal_state"]["receipt_ids"])
            for cons, mind in session.actor_minds.items()
        }
        ids = session._record_player_visible_mind_receipts(
            session.card,
            {"speech": "", "action": "", "thought": "这句只在我心里"},
            1,
        )
        after = {
            cons: len(mind["appraisal_state"]["receipt_ids"])
            for cons, mind in session.actor_minds.items()
        }
        assert ids == []
        assert after == before


def test_opening_relationship_compat_updates_only_after_first_visible_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp, card_path=RYUYA_CARD, session_id="p3b-ryuya")
        session._ensure_opening_mind_projections(session.card, ["C.ryuya.W1"])
        before = session.rel_state_by_cons["C.ryuya.W1"]["to_player"]["closeness"]
        ids1 = session._record_player_visible_mind_receipts(
            session.card,
            {"speech": "谢谢你。", "action": "", "thought": ""},
            1,
        )
        after1 = session.rel_state_by_cons["C.ryuya.W1"]["to_player"]["closeness"]
        ids2 = session._record_player_visible_mind_receipts(
            session.card,
            {"speech": "谢谢你。", "action": "", "thought": ""},
            1,
        )
        after2 = session.rel_state_by_cons["C.ryuya.W1"]["to_player"]["closeness"]
        assert ids1 and ids2 == ids1
        assert after1 == round(before + 0.03, 3)
        assert after2 == after1
        assert session.actor_minds["C.ryuya.W1"]["appraisal_state"]["last_event_kind"] == "player_public_signal"


def test_production_wires_player_actor_and_scene_receipts():
    step_source = inspect.getsource(proto.FreeStageSession.step)
    assert "_record_player_visible_mind_receipts(" in step_source
    assert "_rebuild_turn_working_contexts(" in step_source
    assert "_record_public_actor_mind_receipts(" in step_source

    assert set(_lifecycle_kinds(proto.FreeStageSession._maybe_transition)) >= {"scene_leave", "scene_enter"}
    assert set(_lifecycle_kinds(proto.FreeStageSession.skip_scene)) >= {"scene_leave", "scene_enter"}
    assert set(_lifecycle_kinds(proto.FreeStageSession._maybe_enter_ryuya_flashback)) >= {"scene_leave", "scene_enter"}


def test_public_actor_enactment_updates_self_and_visible_observers():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        ids = session._record_public_actor_mind_receipts(
            session.card,
            [{"role": "npc", "speaker": "张尘", "text": "我先等等。", "turn": 1}],
            1,
        )
        assert ids
        own = session.actor_minds["C.zhangchen.WMAIN"]["appraisal_state"]
        observer = session.actor_minds["C.banbo.WMAIN"]["appraisal_state"]
        assert own["last_event_kind"] == "actor_public_enactment"
        assert own["last_goal_impact"] == "choice_committed"
        assert observer["last_event_kind"] == "actor_public_enactment"
        assert observer["last_goal_impact"] == "observed_other"


def test_session_rebuild_overwrites_tampered_working_cache():
    with tempfile.TemporaryDirectory() as tmp:
        session = _session(tmp)
        session.working_context_state.set_context(
            "C.zhangchen.WMAIN",
            {
                "want_now": "FAKE CACHE GOAL",
                "active_goals": ["FAKE"],
                "updated_at_turn": 0,
            },
        )
        session._rebuild_turn_working_contexts(
            session.card,
            {"speech": "", "action": "我站在旁边观察，不动"},
            1,
            {"speakers": []},
        )
        rebuilt = session.private_inner_states["C.zhangchen.WMAIN"]
        assert rebuilt["want_now"] != "FAKE CACHE GOAL"
        assert "FAKE" not in rebuilt["active_goals"]
        assert rebuilt["authority_source"] == "actor_mind+visible_scene"


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
