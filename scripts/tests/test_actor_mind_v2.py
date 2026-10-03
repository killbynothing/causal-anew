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


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
