"""N2's small, replayable observation -> proposal -> event -> receipt protocol.

These records carry identifiers and safe summaries, never hidden prompt text or
chain-of-thought.  A proposal is explicitly not a world fact; only resolver
output may create an event receipt.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ObservationFrame:
    observation_id: str
    actor_cons: str
    scene_id: str
    turn: int
    public_dialogue_count: int
    private_perception_count: int
    source_trace_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    observation_id: str
    actor_cons: str
    action_kind: str
    requested_outcome: str
    turn: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldEvent:
    event_id: str
    proposal_id: str
    event_kind: str
    outcome: str
    scene_effects: tuple[str, ...]
    turn: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "proposal_id": self.proposal_id,
            "event_kind": self.event_kind,
            "outcome": self.outcome,
            "scene_effects": list(self.scene_effects),
            "turn": self.turn,
        }


@dataclass(frozen=True)
class EventReceipt:
    receipt_id: str
    observation: ObservationFrame
    proposal: ActionProposal
    event: WorldEvent

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "free_stage.causal_receipt.v1",
            "receipt_id": self.receipt_id,
            "observation": self.observation.to_dict(),
            "proposal": self.proposal.to_dict(),
            "event": self.event.to_dict(),
        }


def observation_from_packet(packet: Mapping[str, Any], *, turn: int) -> ObservationFrame:
    actor_cons = str(packet.get("actor_cons", "") or "").strip()
    scene_id = str(packet.get("scene", "") or "").strip()
    if not actor_cons or not scene_id:
        raise ValueError("observation requires actor_cons and scene")
    return ObservationFrame(
        observation_id=f"obs:{scene_id}:{turn}:{actor_cons}",
        actor_cons=actor_cons,
        scene_id=scene_id,
        turn=max(0, int(turn)),
        public_dialogue_count=len(packet.get("observable_dialogue", ()) or ()),
        private_perception_count=len(packet.get("private_perceptions", ()) or ()),
        source_trace_count=len(packet.get("source_trace", ()) or ()),
    )


def resolve_actor_decision(
    observation: ObservationFrame,
    decision: Mapping[str, Any],
    *,
    scene_effects: Mapping[str, Any] | None = None,
) -> EventReceipt:
    """Turn an actor's validated decision into a resolver-owned event receipt."""
    actor_cons = str(decision.get("actor_cons", "") or "").strip()
    outcome = str(decision.get("outcome", "") or "").strip()
    decision_id = str(decision.get("decision_id", "") or "").strip()
    if actor_cons != observation.actor_cons or not outcome or not decision_id:
        raise ValueError("decision does not belong to the observation or lacks a stable id")
    effects = tuple(sorted(str(key) for key, value in dict(scene_effects or {}).items() if bool(value)))
    proposal = ActionProposal(
        proposal_id=f"proposal:{decision_id}", observation_id=observation.observation_id,
        actor_cons=actor_cons, action_kind="actor_owned_decision", requested_outcome=outcome,
        turn=observation.turn,
    )
    event = WorldEvent(
        event_id=f"event:{decision_id}", proposal_id=proposal.proposal_id,
        event_kind="actor_autonomous_choice", outcome=outcome, scene_effects=effects,
        turn=observation.turn,
    )
    return EventReceipt(
        receipt_id=f"receipt:{decision_id}", observation=observation, proposal=proposal, event=event,
    )
