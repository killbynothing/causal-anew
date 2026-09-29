#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.causal_protocol import observation_from_packet, resolve_actor_decision


def test_legacy_n2_protocol_stays_backward_compatible():
    packet = {
        "actor_cons": "C.ryuya.W1",
        "scene": "OPENING_RYUYA_PROLOGUE_001",
        "observable_dialogue": [{"speaker": "玩家", "text": "说吧"}],
        "private_perceptions": [{"kind": "goal"}],
        "source_trace": [{"source": "fixture"}],
    }
    obs = observation_from_packet(packet, turn=3)
    receipt = resolve_actor_decision(
        obs,
        {
            "actor_cons": "C.ryuya.W1",
            "outcome": "wait",
            "decision_id": "fixture-decision-1",
        },
        scene_effects={"stays_present": True, "ignored": False},
    )
    data = receipt.to_dict()
    assert data["schema_version"] == "free_stage.causal_receipt.v1"
    assert data["receipt_id"] == "receipt:fixture-decision-1"
    assert data["event"]["scene_effects"] == ["stays_present"]
    assert data["observation"]["turn"] == 3


def test_legacy_protocol_rejects_cross_actor_decision():
    packet = {"actor_cons": "C.ryuya.W1", "scene": "S1"}
    obs = observation_from_packet(packet, turn=1)
    try:
        resolve_actor_decision(
            obs,
            {"actor_cons": "C.other", "outcome": "x", "decision_id": "d1"},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("cross-actor decision must be rejected")


if __name__ == "__main__":
    test_legacy_n2_protocol_stays_backward_compatible()
    test_legacy_protocol_rejects_cross_actor_decision()
    print("PASS test_causal_protocol")
