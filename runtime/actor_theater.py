"""N4's no-player actor theater.

This is a deliberately small harness, not a second director.  It wakes one
role per beat, gives that role only public stage facts plus its own ActorMind,
resolves a proposed action through N2, and forwards the resulting public event
to named observers as their own receipts.  It is therefore suitable both for
deterministic fixtures and for a caller backed by a real role model.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from runtime.actor_mind import apply_event_receipt, build_actor_mind, observer_safe_summary
from runtime.causal_protocol import observation_from_packet, resolve_actor_decision


ActorCaller = Callable[[dict[str, Any]], Mapping[str, Any]]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _text(value)
        if item and item not in result:
            result.append(item)
    return result


@dataclass(frozen=True)
class TheaterSpec:
    """Public scene frame plus role-owned persona projections.

    The harness accepts existing persona projections.  Synthetic projections
    are allowed only for mechanism fixtures; selecting canon character pairs
    and judging their performance remains a human N4 acceptance decision.
    """

    scene_id: str
    environment: Mapping[str, Any]
    actors: Mapping[str, Mapping[str, Any]]
    unresolved_question: str


class ActorTheater:
    """Replayable actor-to-actor causal loop with no player input."""

    def __init__(self, spec: TheaterSpec):
        self.spec = spec
        self.actor_order = tuple(_unique(spec.actors.keys()))
        if len(self.actor_order) < 2:
            raise ValueError("actor theater requires at least two actors")
        if not _text(spec.scene_id):
            raise ValueError("actor theater requires a scene_id")
        self.actor_minds = {
            actor_cons: build_actor_mind(
                actor_cons,
                spec.actors.get(actor_cons),
                persona_core_hash=f"theater-fixture:{actor_cons}",
            )
            for actor_cons in self.actor_order
        }
        self._pending_events: dict[str, list[dict[str, Any]]] = {actor: [] for actor in self.actor_order}
        self._last_actor = ""
        self._beats: list[dict[str, Any]] = []
        self._silence_beats = 0
        self._relationship_effect_count = 0
        self._consecutive_zero_relationship_beats = 0

    def _next_actor(self) -> str:
        """Prioritize an actual observer, then avoid a one-person monologue."""
        pending = [actor for actor in self.actor_order if self._pending_events[actor]]
        candidates = pending or list(self.actor_order)
        for actor in candidates:
            if actor != self._last_actor:
                return actor
        return candidates[0]

    def _packet_for(self, actor_cons: str) -> dict[str, Any]:
        observed = copy.deepcopy(self._pending_events[actor_cons])
        self._pending_events[actor_cons] = []
        return {
            "actor_cons": actor_cons,
            "scene": self.spec.scene_id,
            "environment": copy.deepcopy(dict(self.spec.environment)),
            "unresolved_question": _text(self.spec.unresolved_question),
            "self_state": {"actor_mind": copy.deepcopy(self.actor_minds[actor_cons])},
            "observed_events": observed,
            "other_actors": [
                {"cons": other, "present": True}
                for other in self.actor_order
                if other != actor_cons
            ],
        }

    def _validated_decision(self, actor_cons: str, raw: Mapping[str, Any], beat_no: int) -> dict[str, Any]:
        action_kind = _text(raw.get("action_kind")) or "silent_observe"
        outcome = _text(raw.get("outcome")) or "observe"
        visible_action = _text(raw.get("visible_action")) or action_kind
        recipients = [
            recipient for recipient in _unique(raw.get("recipients", ()) if isinstance(raw.get("recipients"), Sequence) and not isinstance(raw.get("recipients"), str) else ())
            if recipient in self.actor_minds and recipient != actor_cons
        ]
        effects = [
            dict(effect) for effect in (raw.get("relationship_effects", ()) or ())
            if isinstance(effect, Mapping)
        ]
        return {
            "actor_cons": actor_cons,
            "action_kind": action_kind,
            "outcome": outcome,
            "visible_action": visible_action,
            "recipients": recipients,
            "relationship_effects": effects,
            "decision_id": f"theater:{self.spec.scene_id}:{beat_no}:{actor_cons}",
        }

    def _observer_receipt(self, receipt: Mapping[str, Any], recipient: str, beat_no: int) -> dict[str, Any]:
        observed = copy.deepcopy(dict(receipt))
        observed["receipt_id"] = f"{receipt['receipt_id']}:observed_by:{recipient}"
        observed["observation"] = observation_from_packet(
            {
                "actor_cons": recipient,
                "scene": self.spec.scene_id,
                "observable_dialogue": [receipt["event"]["outcome"]],
                "private_perceptions": [],
                "source_trace": [{"event_id": receipt["event"]["event_id"]}],
            },
            turn=beat_no,
        ).to_dict()
        return observed

    def _queue_public_event(self, decision: Mapping[str, Any], receipt: Mapping[str, Any], beat_no: int) -> list[str]:
        receipt_ids: list[str] = []
        for recipient in decision["recipients"]:
            observed_receipt = self._observer_receipt(receipt, recipient, beat_no)
            updated, applied = apply_event_receipt(
                self.actor_minds[recipient], observed_receipt, actor_cons=recipient,
            )
            if not applied:
                continue
            self.actor_minds[recipient] = updated
            receipt_ids.append(_text(observed_receipt["receipt_id"]))
            self._pending_events[recipient].append({
                "event_id": _text(receipt["event"]["event_id"]),
                "actor_cons": _text(decision["actor_cons"]),
                "action_kind": _text(decision["action_kind"]),
                "outcome": _text(decision["outcome"]),
                "visible_action": _text(decision["visible_action"]),
                "turn": beat_no,
            })
        return receipt_ids

    def run(self, caller: ActorCaller, *, max_beats: int) -> dict[str, Any]:
        """Run at most ``max_beats`` calls; the caller may choose silence."""
        for beat_no in range(max(0, int(max_beats))):
            actor_cons = self._next_actor()
            packet = self._packet_for(actor_cons)
            raw = caller(copy.deepcopy(packet))
            if not isinstance(raw, Mapping):
                raw = {}
            decision = self._validated_decision(actor_cons, raw, beat_no)
            observation = observation_from_packet(
                {
                    "actor_cons": actor_cons,
                    "scene": self.spec.scene_id,
                    "observable_dialogue": packet["observed_events"],
                    "private_perceptions": [],
                    "source_trace": [{"environment": True}],
                },
                turn=beat_no,
            )
            receipt = resolve_actor_decision(observation, decision).to_dict()
            updated, applied = apply_event_receipt(
                self.actor_minds[actor_cons], receipt, actor_cons=actor_cons,
                relationship_effects=decision["relationship_effects"],
            )
            if applied:
                self.actor_minds[actor_cons] = updated
            recipient_receipt_ids = self._queue_public_event(decision, receipt, beat_no)
            if decision["action_kind"] == "silent_observe":
                self._silence_beats += 1
            relationship_effects = len(decision["relationship_effects"]) if applied else 0
            self._relationship_effect_count += relationship_effects
            self._consecutive_zero_relationship_beats = (
                self._consecutive_zero_relationship_beats + 1 if not relationship_effects else 0
            )
            self._beats.append({
                "beat": beat_no,
                "actor_cons": actor_cons,
                "receipt_id": receipt["receipt_id"],
                "recipient_receipt_ids": recipient_receipt_ids,
                "action_kind": decision["action_kind"],
                "outcome": decision["outcome"],
            })
            self._last_actor = actor_cons
        return {
            "beats": copy.deepcopy(self._beats),
            "metrics": {
                "model_calls": len(self._beats),
                "silence_beats": self._silence_beats,
                "relationship_effect_count": self._relationship_effect_count,
                "consecutive_zero_relationship_beats": self._consecutive_zero_relationship_beats,
            },
            "observer_summary": {
                "scene_id": self.spec.scene_id,
                "beat_count": len(self._beats),
                "actors": {actor: observer_safe_summary(mind) for actor, mind in self.actor_minds.items()},
            },
        }
