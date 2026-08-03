"""N5 director port contracts.

These pure functions give the four responsibilities separate inputs and
outputs.  They are intentionally not four model calls: Stage and Voice may be
quiet, Resolver is deterministic, and Dramaturgy creates only an opportunity.
"""
from __future__ import annotations

from typing import Any, Mapping

from runtime.causal_protocol import (
    ObservationFrame,
    observation_from_packet,
    resolve_actor_decision,
)
from runtime.director_intent import DirectorMove, validate_director_move


_PRIVATE_MARKERS = ("private", "mind", "inner", "secret", "thought", "director_private")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _public_mapping(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy only public scalar/list facts, rejecting private-looking keys."""
    result: dict[str, Any] = {}
    for key, value in dict(raw or {}).items():
        normalized = _text(key).lower()
        if not normalized or any(marker in normalized for marker in _PRIVATE_MARKERS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
    return result


def build_stage_frame(public_world: Mapping[str, Any] | None) -> dict[str, Any]:
    """Stage sees public environment only and can choose not to intervene."""
    facts = _public_mapping(public_world)
    change = _text(facts.get("environment_change") or facts.get("public_event"))
    return {
        "port": "Stage",
        "mode": "environment_opportunity" if change else "quiet",
        "public_facts": facts,
    }


def resolve_public_action(
    public_observation: Mapping[str, Any] | ObservationFrame,
    actor_decision: Mapping[str, Any],
    *,
    turn: int | None = None,
    scene_effects: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolver alone converts an actor-owned decision into a world receipt.

    Production may pass a full actor packet or an already-built ObservationFrame.
    Receipts never store prompt bodies; ObservationFrame only carries counts.
    """
    if isinstance(public_observation, ObservationFrame):
        observation = public_observation
    else:
        if turn is None:
            raise ValueError("turn is required when resolving from a packet mapping")
        observation = observation_from_packet(public_observation, turn=int(turn))
    return resolve_actor_decision(
        observation,
        actor_decision,
        scene_effects=scene_effects,
    ).to_dict()


def build_dramaturgy_opportunity(move: Mapping[str, Any]) -> dict[str, Any]:
    """Dramaturgy may foreground a legal opportunity, never choose its result."""
    raw = dict(move)
    validate_director_move(raw)
    return DirectorMove(
        kind=_text(raw.get("kind")),
        affordance_id=_text(raw.get("affordance_id")),
        intent_id=_text(raw.get("intent_id")),
        visible_reason=_text(raw.get("visible_reason")),
        actor_target=_text(raw.get("actor_target")),
    ).to_dict()


def render_director_voice(public_stage: Mapping[str, Any] | None) -> dict[str, Any]:
    """Voice turns public facts into display text; it does not write world state."""
    facts = _public_mapping(public_stage)
    fragments = [_text(facts.get(key)) for key in ("where", "environment_change", "public_event")]
    return {"port": "Voice", "text": "；".join(fragment for fragment in fragments if fragment)}
