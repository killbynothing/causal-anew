"""N3's persistent, receipt-driven ActorMind v2.

The model never writes this state directly.  A role starts from the existing
persona projection (itself sourced from the canon pipeline), then a reducer
updates structured appraisal, motivation and relationships only after a
resolver-owned N2 EventReceipt exists.  This deliberately stores no free-text
chain of thought.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "free_stage.actor_mind.v2"
RELATION_FACETS = ("trust", "intimacy", "alert", "cooperation")
RESPONSE_KINDS = ("accept", "refuse", "defer", "offer_alternative", "ask_evidence", "set_boundary")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique_text(values: Sequence[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = _text(value)
        if item and item not in out:
            out.append(item)
    return out


def _append_once(values: Sequence[Any], value: str) -> list[str]:
    return _unique_text([*values, value])


def build_actor_mind(
    actor_cons: str,
    persona: Mapping[str, Any] | None,
    *,
    persona_core_hash: str = "",
) -> dict[str, Any]:
    """Build an actor-owned state from already-projected persona material.

    No new biography, values or hidden intention is invented here.  The card
    provides the immediate scene seed; the persona-core hash makes the stable
    source auditable without copying its prose into receipts or observer data.
    """
    source = dict(persona or {})
    inner = source.get("inner_state") if isinstance(source.get("inner_state"), Mapping) else {}
    boundaries = source.get("boundaries") if isinstance(source.get("boundaries"), Mapping) else {}
    stance = _text(inner.get("stance_to_player"))
    goal = _text(inner.get("want_now"))
    hard_boundaries = _unique_text(boundaries.get("hard", ()) if isinstance(boundaries, Mapping) else ())
    return {
        "schema_version": SCHEMA_VERSION,
        "actor_cons": _text(actor_cons),
        "stable_profile": {
            "persona_core_hash": _text(persona_core_hash),
            "source_refs": ["persona_core", "persona.inner_state", "persona.boundaries"],
            "hard_boundary_count": len(hard_boundaries),
        },
        "appraisal_state": {
            "receipt_ids": [],
            "last_event_kind": "",
            "last_goal_impact": "none",
            "last_risk_signal": "none",
            "uncertainty_codes": [],
        },
        "motivational_state": {
            "active_goals": [goal] if goal else [],
            "conflicting_motives": [],
            "commitments": [],
            "last_choice": "",
        },
        "expression_policy": {
            "default_public_stance": stance,
            "current_public_stance": stance,
            # The existence of an unsaid seed is useful to the role itself,
            # but its body never leaves the actor-owned state.
            "private_seed_present": bool(_text(inner.get("unsaid")) or _text(inner.get("knot"))),
            "current_mask_mode": "unresolved",
        },
        "relationships": {},
        "public_state": {
            "last_receipt_id": "",
            "last_action_kind": "",
            "last_outcome": "",
        },
    }


def observer_safe_summary(mind: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return observatory metadata, never private seed, goals or relations."""
    state = dict(mind or {})
    appraisal = state.get("appraisal_state") if isinstance(state.get("appraisal_state"), Mapping) else {}
    motivations = state.get("motivational_state") if isinstance(state.get("motivational_state"), Mapping) else {}
    profile = state.get("stable_profile") if isinstance(state.get("stable_profile"), Mapping) else {}
    public = state.get("public_state") if isinstance(state.get("public_state"), Mapping) else {}
    return {
        "schema_version": _text(state.get("schema_version")),
        "actor_cons": _text(state.get("actor_cons")),
        "persona_core_hash": _text(profile.get("persona_core_hash")),
        "receipt_count": len(appraisal.get("receipt_ids", ()) or ()),
        "goal_count": len(motivations.get("active_goals", ()) or ()),
        "last_receipt_id": _text(public.get("last_receipt_id")),
        "last_action_kind": _text(public.get("last_action_kind")),
    }


def _valid_receipt(receipt: Mapping[str, Any] | None) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    if not isinstance(receipt, Mapping):
        return None
    if _text(receipt.get("schema_version")) != "free_stage.causal_receipt.v1":
        return None
    receipt_id = _text(receipt.get("receipt_id"))
    proposal = receipt.get("proposal") if isinstance(receipt.get("proposal"), Mapping) else {}
    event = receipt.get("event") if isinstance(receipt.get("event"), Mapping) else {}
    if not receipt_id or not _text(proposal.get("proposal_id")) or not _text(event.get("event_id")):
        return None
    if _text(event.get("proposal_id")) != _text(proposal.get("proposal_id")):
        return None
    return receipt_id, dict(proposal), dict(event)


def _goal_impact(event: Mapping[str, Any], actor_cons: str, receipt_actor: str) -> str:
    outcome = _text(event.get("outcome"))
    effects = {_text(item) for item in event.get("scene_effects", ()) or ()}
    if actor_cons != receipt_actor:
        return "observed_other"
    if "actor_leaves_scene" in effects:
        return "transition_committed"
    if outcome == "defer":
        return "deferred"
    if outcome:
        return "choice_committed"
    return "none"


def _risk_signal(event: Mapping[str, Any]) -> str:
    effects = {_text(item) for item in event.get("scene_effects", ()) or ()}
    if "actor_leaves_scene" in effects:
        return "location_changed"
    if effects:
        return "world_effect"
    return "none"


def _normalized_effects(
    effects: Sequence[Mapping[str, Any]] | None,
    *,
    receipt_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in effects or ():
        if not isinstance(raw, Mapping):
            continue
        target = _text(raw.get("target_cons"))
        facet = _text(raw.get("facet"))
        reason = _text(raw.get("reason_code"))
        try:
            delta = int(raw.get("delta", 0))
        except (TypeError, ValueError):
            continue
        if not target or facet not in RELATION_FACETS or not reason or not delta or abs(delta) > 3:
            continue
        normalized.append({
            "target_cons": target, "facet": facet, "delta": delta,
            "reason_code": reason, "receipt_id": receipt_id,
        })
    return normalized


def apply_event_receipt(
    mind: Mapping[str, Any] | None,
    receipt: Mapping[str, Any] | None,
    *,
    actor_cons: str | None = None,
    relationship_effects: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Apply one resolver receipt once. Invalid/missing receipts are no-ops."""
    current = copy.deepcopy(dict(mind or {}))
    valid = _valid_receipt(receipt)
    if valid is None:
        return current, False
    receipt_id, proposal, event = valid
    appraisal = current.get("appraisal_state") if isinstance(current.get("appraisal_state"), Mapping) else {}
    seen = {_text(item) for item in appraisal.get("receipt_ids", ()) or ()}
    if receipt_id in seen:
        return current, False

    own_cons = _text(actor_cons or current.get("actor_cons"))
    receipt_actor = _text(proposal.get("actor_cons"))
    if not own_cons or not receipt_actor:
        return current, False
    current.setdefault("schema_version", SCHEMA_VERSION)
    current.setdefault("actor_cons", own_cons)
    current["appraisal_state"] = {
        "receipt_ids": _append_once(appraisal.get("receipt_ids", ()) or (), receipt_id),
        "last_event_kind": _text(event.get("event_kind")),
        "last_goal_impact": _goal_impact(event, own_cons, receipt_actor),
        "last_risk_signal": _risk_signal(event),
        "uncertainty_codes": [],
    }
    motivation = current.get("motivational_state") if isinstance(current.get("motivational_state"), Mapping) else {}
    current["motivational_state"] = {
        "active_goals": _unique_text(motivation.get("active_goals", ()) or ()),
        "conflicting_motives": _unique_text(motivation.get("conflicting_motives", ()) or ()),
        "commitments": _unique_text(motivation.get("commitments", ()) or ()),
        "last_choice": _text(event.get("outcome")) if own_cons == receipt_actor else "",
    }
    public = current.get("public_state") if isinstance(current.get("public_state"), Mapping) else {}
    current["public_state"] = {
        "last_receipt_id": receipt_id,
        "last_action_kind": _text(proposal.get("action_kind")),
        "last_outcome": _text(event.get("outcome")),
    }
    expression = current.get("expression_policy") if isinstance(current.get("expression_policy"), Mapping) else {}
    current["expression_policy"] = {
        "default_public_stance": _text(expression.get("default_public_stance")),
        "current_public_stance": _text(expression.get("current_public_stance")),
        "private_seed_present": bool(expression.get("private_seed_present", False)),
        "current_mask_mode": _text(expression.get("current_mask_mode")) or "unresolved",
    }
    relations = copy.deepcopy(current.get("relationships") if isinstance(current.get("relationships"), Mapping) else {})
    for effect in _normalized_effects(relationship_effects, receipt_id=receipt_id):
        edge = dict(relations.get(effect["target_cons"], {}))
        edge.setdefault("evidence_receipt_ids", [])
        for facet in RELATION_FACETS:
            edge.setdefault(facet, 0)
        edge[effect["facet"]] = int(edge[effect["facet"]]) + effect["delta"]
        edge["evidence_receipt_ids"] = _append_once(edge["evidence_receipt_ids"], receipt_id)
        edge["last_reason_code"] = effect["reason_code"]
        relations[effect["target_cons"]] = edge
    current["relationships"] = relations
    return current, True


def assess_appeal(mind: Mapping[str, Any] | None, appeal: Mapping[str, Any] | None) -> dict[str, Any]:
    """Describe actor-specific considerations without inventing a persuasion score.

    This is an input to role deliberation, never an automatic accept/reject.
    """
    raw = dict(appeal or {})
    evidence_ids = _unique_text(raw.get("evidence_ids", ()) if isinstance(raw.get("evidence_ids"), Sequence) and not isinstance(raw.get("evidence_ids"), str) else ())
    respects_boundaries = bool(raw.get("respects_boundaries", False))
    commitment_conflict = bool(raw.get("conflicts_with_commitment", False))
    requested_cost = _text(raw.get("requested_cost")) or "unknown"
    considerations = []
    if not respects_boundaries:
        considerations.append("boundary_conflict")
        responses = ["refuse", "set_boundary"]
    elif commitment_conflict:
        considerations.append("commitment_conflict")
        responses = ["defer", "offer_alternative"]
        if not evidence_ids:
            responses.append("ask_evidence")
    else:
        if evidence_ids:
            considerations.append("source_bearing_evidence")
        else:
            considerations.append("evidence_missing")
        if requested_cost in {"high", "unknown"} and not evidence_ids:
            responses = ["ask_evidence", "defer", "offer_alternative"]
        else:
            responses = ["accept", "refuse", "defer", "offer_alternative"]
    return {
        "actor_cons": _text((mind or {}).get("actor_cons")),
        "evidence_ids": evidence_ids,
        "requested_cost": requested_cost,
        "considerations": considerations,
        "recommended_response_kinds": [item for item in responses if item in RESPONSE_KINDS],
    }
