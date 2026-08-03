"""Actor-owned decisions caused by world conditions, never by player intent.

The director may expose a role to an already observable situation (a ringing
phone, an invitation, a closing shop).  This module compiles the resulting
choice request but deliberately contains no outcome policy: the addressed
consciousness must answer it from its own actor packet.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from runtime.director_intent import validate_actor_decision


_ALLOWED_OUTCOMES = {
    "accept", "conditional", "refuse", "alternative", "defer", "evade", "leave",
}


def next_autonomous_decision(
    card: Mapping[str, Any], *, completed: Iterable[str], recorded: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Return the first reachable, unresolved actor-owned decision point.

    Card declarations name only an observable situation and an actor.  They
    must not carry a preferred outcome, probability, or director-authored
    consequence.  Consequences are resolved later by normal route rules.
    """
    done_beats = {str(item) for item in completed}
    branch_set = {str(item) for item in card.get("_runtime_branch_progress", ())}
    resolved = {
        str(item.get("autonomous_decision_id", ""))
        for item in recorded if isinstance(item, Mapping)
        and str(item.get("autonomous_decision_id", ""))
    }
    present = {str(item) for item in card.get("present", ())}
    for raw in card.get("autonomous_decisions", ()):
        if not isinstance(raw, Mapping):
            continue
        decision_id = str(raw.get("decision_id", "")).strip()
        actor_cons = str(raw.get("actor_cons", "")).strip()
        situation = str(raw.get("situation", "")).strip()
        after = {str(item).strip() for item in raw.get("after_must_happen", ()) if str(item).strip()}
        requires_branch = {str(item).strip() for item in raw.get("requires_branch_progress", ()) if str(item).strip()}
        outcomes = tuple(str(item).strip() for item in raw.get("valid_outcomes", ()) if str(item).strip())
        if not decision_id or not actor_cons or not situation:
            raise ValueError("autonomous decision requires id, actor_cons, and observable situation")
        # A resolved leave decision is expected to remove its actor from the
        # scene.  Skip it before validating current presence, otherwise the
        # next scan mistakes a completed receipt for an invalid new request.
        if decision_id in resolved:
            continue
        if actor_cons not in present:
            raise ValueError(f"autonomous decision actor is not present: {actor_cons}")
        if not outcomes or not set(outcomes).issubset(_ALLOWED_OUTCOMES):
            raise ValueError(f"autonomous decision {decision_id} has unsupported outcomes")
        if any(key in raw for key in ("preferred_outcome", "probability", "director_outcome")):
            raise ValueError(f"autonomous decision {decision_id} lets director choose an outcome")
        raw_scene_effects = raw.get("outcome_scene_effects", {})
        if raw_scene_effects and not isinstance(raw_scene_effects, Mapping):
            raise ValueError(f"autonomous decision {decision_id} has malformed scene effects")
        for outcome, effect in dict(raw_scene_effects).items():
            if str(outcome) not in outcomes or not isinstance(effect, Mapping):
                raise ValueError(f"autonomous decision {decision_id} has malformed outcome scene effect")
            # A card may record the physical consequence of the actor's own
            # selected departure.  It cannot use this hook to move somebody
            # else, choose a destination, or otherwise puppeteer the scene.
            if set(effect) - {"actor_leaves_scene"} or not isinstance(effect.get("actor_leaves_scene"), bool):
                raise ValueError(f"autonomous decision {decision_id} scene effect exceeds actor-owned departure")
        if not after.issubset(done_beats) or not requires_branch.issubset(branch_set):
            continue
        return {
            "decision_id": decision_id,
            "intent_id": f"autonomous:{decision_id}",
            "actor_cons": actor_cons,
            "situation": situation,
            "valid_outcomes": list(outcomes),
            "outcome_effects": {
                str(key): [str(item).strip() for item in value if str(item).strip()]
                for key, value in dict(raw.get("outcome_branch_progress", {})).items()
                if isinstance(value, (list, tuple))
            },
            "outcome_scene_effects": {
                str(key): dict(value)
                for key, value in dict(raw.get("outcome_scene_effects", {})).items()
                if isinstance(value, Mapping)
            },
            "output_contract": {
                "actor_cons": actor_cons,
                "intent_id": f"autonomous:{decision_id}",
                "outcome": "one valid_outcomes value",
                "visible_response": "observable speech or action",
                "reason_sources": "actor-owned packet paths only",
                "conditions": "list; required for conditional",
                "uncertainty": "optional actor uncertainty",
                "commitment": "optional explicit promise or alternative help",
                "revises_decision_id": "optional prior decision id",
            },
        }
    return None


def available_autonomous_decisions(
    card: Mapping[str, Any], *, completed: Iterable[str], recorded: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return all independent choices opened by the same world moment.

    Calling actors together does not merge their decisions: it only prevents a
    single rainstorm, invitation, or phone call from becoming several forced
    player turns.
    """
    remaining = [dict(item) for item in recorded if isinstance(item, Mapping)]
    out: list[dict[str, Any]] = []
    while True:
        request = next_autonomous_decision(card, completed=completed, recorded=remaining)
        if request is None:
            return tuple(out)
        out.append(request)
        remaining.append({"autonomous_decision_id": request["decision_id"]})


def validate_autonomous_decision(request: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an actor result without turning the world event into an intent."""
    decision = dict(raw)
    validate_actor_decision(decision)
    if not str(decision.get("visible_response", "")).strip():
        raise ValueError("autonomous decision requires a visible response receipt")
    expected_actor = str(request.get("actor_cons", "")).strip()
    expected_intent = f"autonomous:{str(request.get('decision_id', '')).strip()}"
    if decision.get("actor_cons") != expected_actor:
        raise ValueError("autonomous decision belongs to another actor")
    if decision.get("intent_id") != expected_intent:
        raise ValueError("autonomous decision belongs to another decision point")
    if decision.get("outcome") not in request.get("valid_outcomes", ()):
        raise ValueError("actor selected an outcome outside the autonomous decision contract")
    return {
        **decision,
        "autonomous_decision_id": str(request["decision_id"]),
        "event": "actor_autonomously_decided",
    }
