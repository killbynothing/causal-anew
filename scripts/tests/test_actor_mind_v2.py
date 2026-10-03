#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.actor_mind import (
    ActorMindState,
    ReflectProposalState,
    TurnWorkingContextState,
    apply_event_receipt,
    build_actor_mind,
    observer_safe_summary,
    observer_state_projection,
)
from runtime.causal_protocol import observation_from_packet, resolve_actor_decision


def _receipt(actor_cons: str = "C.test.W1", *, turn: int = 1, outcome: str = "wait"):
    observation = observation_from_packet(
        {
            "actor_cons": actor_cons,
            "scene": "S1",
            "observable_dialogue": ["hello"],
            "private_perceptions": [],
            "source_trace": [{"fixture": True}],
        },
        turn=turn,
    )
    return resolve_actor_decision(
        observation,
        {
            "actor_cons": actor_cons,
            "outcome": outcome,
            "decision_id": f"d:{actor_cons}:{turn}:{outcome}",
        },
    ).to_dict()


def _audit_report():
    path = ROOT / "scripts" / "audit_runtime_authority.py"
    spec = importlib.util.spec_from_file_location("p3a_authority_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(False)


def test_seed_is_structured_and_does_not_copy_private_prose_to_observer():
    mind = build_actor_mind(
        "C.test.W1",
        {
            "inner_state": {
                "want_now": "把话说明白",
                "stance_to_player": "克制",
                "unsaid": "fixture secret",
            },
            "boundaries": {"hard": ["不要越界"]},
        },
        persona_core_hash="fixture-hash",
    )
    assert mind["motivational_state"]["active_goals"] == ["把话说明白"]
    summary = observer_safe_summary(mind)
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "fixture secret" not in serialized
    assert "把话说明白" not in serialized
    assert summary["persona_core_hash"] == "fixture-hash"


def test_event_receipt_is_idempotent_and_actor_scoped():
    mind = build_actor_mind("C.test.W1", {"inner_state": {"want_now": "观察"}})
    receipt = _receipt()
    updated, changed = apply_event_receipt(mind, receipt, actor_cons="C.test.W1")
    assert changed is True
    again, changed_again = apply_event_receipt(updated, receipt, actor_cons="C.test.W1")
    assert changed_again is False
    assert again == updated
    assert updated["public_state"]["last_receipt_id"] == receipt["receipt_id"]


def test_observer_shape_marks_working_context_as_projection():
    mind = build_actor_mind("C.test.W1", {"inner_state": {"want_now": "观察"}})
    projected = observer_state_projection(
        mind,
        working_context={
            "attention_target": "player",
            "pending_concerns": ["x"],
            "secret_internal_field": "must not leak",
        },
        decide={"top_concern": "x", "participation_mode": "speak"},
    )
    assert projected["authority"] == "actor_mind"
    assert projected["working_context"]["attention_target"] == "player"
    assert "secret_internal_field" not in projected["working_context"]


def test_actor_mind_state_is_copy_safe_and_receipt_owned():
    state = ActorMindState.empty()
    state.ensure(
        "C.test.W1",
        {"inner_state": {"want_now": "观察", "stance_to_player": "克制"}},
        persona_core_hash="fixture-hash",
    )
    visible = state.minds
    visible["C.test.W1"]["motivational_state"]["active_goals"].append("FAKE")
    assert state.get("C.test.W1")["motivational_state"]["active_goals"] == ["观察"]

    receipt = _receipt()
    assert state.apply_receipt("C.test.W1", receipt) is True
    assert state.apply_receipt("C.test.W1", receipt) is False
    assert state.get("C.test.W1")["public_state"]["last_receipt_id"] == receipt["receipt_id"]


def test_legacy_opening_projection_migrates_into_actor_mind_compat():
    state = ActorMindState.empty()
    state.absorb_legacy_opening_projection(
        {
            "C.test.W1": {
                "trust": 44,
                "intimacy": 21,
                "alert": 33,
                "state": "probing",
                "violations": 1,
            }
        },
        {
            "C.test.W1": {
                "to_player": {
                    "closeness": 0.4,
                    "wariness": 0.5,
                    "label": "legacy",
                    "stage": "S1",
                }
            }
        },
    )
    state.ensure("C.test.W1", {"inner_state": {"want_now": "观察"}})
    assert state.opening_fsm_map()["C.test.W1"]["trust"] == 44
    assert state.opening_rel_map()["C.test.W1"]["to_player"]["closeness"] == 0.4

    view = state.opening_rel_map()
    view["C.test.W1"]["to_player"]["closeness"] = 999
    assert state.opening_rel_map()["C.test.W1"]["to_player"]["closeness"] == 0.4


def test_opening_legacy_heuristics_preserve_existing_numbers_inside_mind():
    state = ActorMindState.empty()
    state.ensure("C.test.W1", {"inner_state": {"want_now": "观察"}})
    state.ensure_opening_compat(
        "C.test.W1",
        fsm_seed={
            "trust": 50,
            "intimacy": 25,
            "alert": 25,
            "state": "open",
            "violations": 0,
        },
        rel_seed={
            "to_player": {
                "closeness": 0.2,
                "wariness": 0.3,
                "label": "fixture",
                "stage": "S0",
            }
        },
    )
    assert state.apply_opening_player_signal(
        "C.test.W1",
        player_speech="谢谢，一起走吧",
        player_action="",
    )
    fsm = state.opening_fsm_map()["C.test.W1"]
    rel = state.opening_rel_map()["C.test.W1"]["to_player"]
    assert (fsm["trust"], fsm["intimacy"], fsm["alert"], fsm["state"]) == (53, 27, 23, "open")
    assert rel["closeness"] == 0.23
    assert rel["wariness"] == 0.28


def test_working_context_and_reflect_cache_are_defensive_projections():
    working = TurnWorkingContextState.empty()
    working.set_context(
        "C.test.W1",
        {"pending_concerns": ["a"], "attention_target": "player"},
    )
    view = working.contexts
    view["C.test.W1"]["pending_concerns"].append("FAKE")
    assert working.get("C.test.W1")["pending_concerns"] == ["a"]

    reflect = ReflectProposalState.empty()
    reflect.set("C.test.W1", {"thought": "proposal", "evidence": ["r1"]})
    proposal = reflect.proposals
    proposal["C.test.W1"]["evidence"].append("FAKE")
    assert reflect.get("C.test.W1")["evidence"] == ["r1"]


def test_current_p3a_authority_map_is_machine_visible():
    report = _audit_report()
    names = (
        "private_inner_states",
        "prior_reflect_by_cons",
        "actor_minds",
        "fsm_by_cons",
        "rel_state_by_cons",
    )
    snapshot = {
        name: {
            "production_writer_count": report["facts"][name]["production_writer_count"],
            "unknown_alias_count": report["facts"][name]["unknown_alias_count"],
            "target_owner": report["facts"][name]["target_owner"],
        }
        for name in names
    }
    print("P3A_AUTHORITY_MAP=" + json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    details = {
        name: [
            {
                "path": row["path"],
                "symbol": row["symbol"],
                "line": row["line"],
                "write_kind": row["write_kind"],
                "classification": row["classification"],
            }
            for row in report["facts"][name]["writers"]
            if row["classification"] in {"production", "production_tooling", "unknown_alias"}
        ]
        for name in names
    }
    print("P3A_WRITERS=" + json.dumps(details, ensure_ascii=False, sort_keys=True))
    assert all(name in report["facts"] for name in names)
    for name in names:
        assert snapshot[name]["production_writer_count"] == 0, (name, details[name])
        assert snapshot[name]["unknown_alias_count"] == 0, (name, details[name])
        assert details[name] == [], (name, details[name])
    assert snapshot["actor_minds"]["target_owner"] == "ActorMindReducer"
    assert snapshot["private_inner_states"]["target_owner"] == "TurnWorkingContext"
    assert snapshot["prior_reflect_by_cons"]["target_owner"] == "ReflectProposalCache"


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
