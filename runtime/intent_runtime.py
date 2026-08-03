"""Generic binding between card-authored opportunities and actor-owned choices.

The semantic interpreter can recognize novel wording, but it may select only an
opportunity advertised by the current card.  This module contains no story,
scene, or character identifiers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from runtime.director_intent import (
    Affordance,
    EphemeralStorylet,
    FeasibilityResult,
    IntentProposal,
    DirectorMove,
    classify_feasibility,
    open_intent_thread,
    plan_director_moves,
    public_modalities,
)


EXIT_AFFORDANCE_PREFIX = "__exit__:"


@dataclass(frozen=True)
class AdvertisedAffordance:
    affordance: Affordance
    goal_key: str
    description: str
    target_cons: str
    storylet: Mapping[str, Any]


@dataclass(frozen=True)
class IntentResolution:
    feasibility: FeasibilityResult
    director_moves: tuple[DirectorMove, ...]
    storylet: EphemeralStorylet
    advertised: AdvertisedAffordance
    confidence: float = 0.0

    def debug_payload(self) -> dict[str, Any]:
        return {
            "feasibility": self.feasibility.to_dict(),
            "director_moves": [item.to_dict() for item in self.director_moves],
            "storylet": self.storylet.created_payload(),
            "confidence": self.confidence,
        }


def _clean_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def advertised_affordances(
    card: Mapping[str, Any], *, completed: Iterable[str], branch_progress: Iterable[str] = ()
) -> tuple[AdvertisedAffordance, ...]:
    """Compile declarative card opportunities and deterministic world gates."""
    completed_set = {str(item) for item in completed}
    branch_set = {str(item) for item in branch_progress}
    present = {str(item) for item in card.get("present", ())}
    result: list[AdvertisedAffordance] = []
    for raw in card.get("intent_affordances", ()):
        if not isinstance(raw, Mapping):
            continue
        affordance_id = str(raw.get("affordance_id", "")).strip()
        goal_key = str(raw.get("goal_key", "")).strip()
        description = str(raw.get("description", "")).strip()
        target = str(raw.get("target_cons", "")).strip()
        source = str(raw.get("source", "")).strip()
        mode = str(raw.get("mode", "negotiate_now")).strip()
        after = set(_clean_tuple(raw.get("after_must_happen", ())))
        before = set(_clean_tuple(raw.get("before_must_happen", ())))
        required_branch = set(_clean_tuple(raw.get("requires_branch_progress", ())))
        # `$ambient:<profile>` names an environmental role, not a pre-existing
        # canonical consciousness. It is materialized only after this public
        # affordance is semantically selected.
        target_can_hear = not target or target in present or target.startswith("$ambient:")
        available = after.issubset(completed_set) and not bool(before.intersection(completed_set))
        available = available and required_branch.issubset(branch_set)
        available = available and target_can_hear
        item = Affordance(
            affordance_id=affordance_id,
            intent_keys=(goal_key,),
            mode=mode,
            source=source,
            location=str(card.get("physical_frame_id") or card.get("scene_id") or "current_frame"),
            available=available,
            pending_human=bool(raw.get("pending_human", False)),
            requires_actor_consent=bool(raw.get("requires_actor_consent", bool(target))),
            score=int(raw.get("score", 0) or 0),
            reason=str(raw.get("visible_reason", "") or "").strip(),
        )
        result.append(AdvertisedAffordance(item, goal_key, description, target, dict(raw.get("storylet", {}))))
    return tuple(result)


def with_semantic_exit_affordances(
    card: Mapping[str, Any], *, completed: Iterable[str], branch_progress: Iterable[str] = (),
) -> dict[str, Any]:
    """Expose currently reachable card exits to the semantic interpreter.

    An exit is a player-owned movement opportunity, not a director command.
    The interpreter may recognize natural wording, but can select only an exit
    authored by this card.  The session still validates all route receipts
    before moving anyone.
    """
    compiled = dict(card)
    authored = [dict(item) for item in card.get("intent_affordances", ()) if isinstance(item, Mapping)]
    required_beats = [str(item.get("id")) for item in card.get("must_happen", ()) if isinstance(item, Mapping) and item.get("id")]
    for index, raw_exit in enumerate(card.get("exits", ())):
        if not isinstance(raw_exit, Mapping) or not str(raw_exit.get("target_card", "")).strip():
            continue
        destination = str(raw_exit.get("target_card", "")).rsplit("/", 1)[-1]
        receipt = str(raw_exit.get("semantic_receipt", "")).strip()
        required_branches = [str(item) for item in raw_exit.get("requires_branch_progress", ()) if str(item)]
        if receipt:
            # This receipt is precisely what the semantic match is being asked
            # to establish; all other route receipts remain hard prerequisites.
            required_branches = [item for item in required_branches if item != receipt]
        authored.append({
            "affordance_id": f"{EXIT_AFFORDANCE_PREFIX}{index}",
            "goal_key": f"player_exit:{index}",
            "description": (
                "玩家离开当前场并前往该卡已经提供的下一处："
                f"{destination}。适用情形：{str(raw_exit.get('trigger', '')).strip()}"
            ),
            "target_cons": "",
            "mode": "do_now",
            "source": "card.exits",
            "requires_actor_consent": False,
            "after_must_happen": required_beats,
            "requires_branch_progress": required_branches,
            "storylet": {
                "entry_conditions": ["observable_player_movement_commitment"],
                "invariants": ["director_does_not_invent_player_movement", "route_requirements_still_apply"],
                "exit_keys": ["committed"],
            },
        })
    compiled["intent_affordances"] = authored
    return compiled


def semantic_exit_index(resolution: IntentResolution | None) -> int | None:
    """Return an interpreter-selected exit index, never a guessed route."""
    if resolution is None:
        return None
    raw = str(resolution.advertised.affordance.affordance_id or "")
    if not raw.startswith(EXIT_AFFORDANCE_PREFIX):
        return None
    try:
        return int(raw.removeprefix(EXIT_AFFORDANCE_PREFIX))
    except ValueError:
        return None


def build_intent_interpretation_request(
    card: Mapping[str, Any],
    player_input: str | Mapping[str, Any] | None,
    *,
    completed: Iterable[str],
    branch_progress: Iterable[str] = (),
    turn: int,
    scope_id: str = "",
) -> dict[str, Any] | None:
    """Expose semantic descriptions, never keyword tables or private thought."""
    public = public_modalities(player_input)
    if not public["speech"] and not public["action"]:
        return None
    advertised = advertised_affordances(card, completed=completed, branch_progress=branch_progress)
    available = [item for item in advertised if item.affordance.available and not item.affordance.pending_human]
    if not available:
        return None
    return {
        "task": "match_observable_player_intent_to_current_opportunity",
        "turn": max(0, int(turn)),
        "scope_id": str(scope_id or "").strip(),
        "player_observable": public,
        "available_affordances": [
            {
                "affordance_id": item.affordance.affordance_id,
                "goal_key": item.goal_key,
                "description": item.description,
                "target_cons": item.target_cons,
                "requires_actor_consent": item.affordance.requires_actor_consent,
            }
            for item in available
        ],
        "output_contract": {
            "matched_affordance_id": "one advertised id or null",
            "goal_text": "short semantic paraphrase of what the player is attempting",
            "confidence": "number from 0 to 1",
        },
        "rules": [
            "Match the full semantic meaning of the observable attempt.",
            "Do not invent an opportunity.",
            "A match opens an attempt; it never means the target agreed.",
        ],
    }


def resolve_interpretation(
    request: Mapping[str, Any] | None,
    interpretation: Mapping[str, Any] | None,
) -> IntentResolution | None:
    """Validate a semantic match and compile a replayable opportunity attempt."""
    if request is None or not isinstance(interpretation, Mapping):
        return None
    matched_id = str(interpretation.get("matched_affordance_id", "") or "").strip()
    if not matched_id:
        return None
    advertised_rows = {
        str(item.get("affordance_id", "")): item
        for item in request.get("available_affordances", ())
        if isinstance(item, Mapping)
    }
    if matched_id not in advertised_rows:
        raise ValueError(f"interpreted affordance is not advertised: {matched_id}")
    row = advertised_rows[matched_id]
    turn = max(0, int(request.get("turn", 0) or 0))
    scope = str(request.get("scope_id", "") or "").strip()
    identity_prefix = f"{scope}:" if scope else ""
    intent_id = f"intent:{identity_prefix}{turn}:{matched_id}"
    target = str(row.get("target_cons", "") or "").strip()
    proposal = IntentProposal(
        intent_id=intent_id,
        goal_key=str(row.get("goal_key", "")).strip(),
        goal_text=str(interpretation.get("goal_text", "") or row.get("description", "")).strip(),
        target=target,
        requires_actor_consent=bool(row.get("requires_actor_consent", bool(target))),
    )
    intent = open_intent_thread(proposal, request.get("player_observable", {}), turn=turn)
    raw_storylet: Mapping[str, Any] = {}
    source_affordance: AdvertisedAffordance | None = None
    # The request intentionally exposes only public matching data.  The caller
    # attaches its compiled card affordance below when using ``bind_resolution``.
    affordance = Affordance(
        affordance_id=matched_id,
        intent_keys=(proposal.goal_key,),
        mode="negotiate_now" if proposal.requires_actor_consent else "do_now",
        source="card.intent_affordances",
        location="current_frame",
        requires_actor_consent=proposal.requires_actor_consent,
        reason="玩家的公开言行与当前可尝试机会相符。",
    )
    source_affordance = AdvertisedAffordance(
        affordance, proposal.goal_key, str(row.get("description", "")), target, raw_storylet
    )
    feasibility = classify_feasibility(intent, (affordance,))
    default_exits = ("accept", "conditional", "refuse", "alternative", "defer")
    storylet = EphemeralStorylet(
        storylet_id=f"storylet:{identity_prefix}{turn}:{matched_id}",
        intent_id=intent_id,
        source_affordance_id=matched_id,
        entry_conditions=("player_request_is_observable",) + (("target_can_hear",) if target else ()),
        invariants=("director_does_not_choose_actor_outcome", "run_local_append_only"),
        exit_keys=default_exits,
    )
    try:
        confidence = min(1.0, max(0.0, float(interpretation.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return IntentResolution(feasibility, plan_director_moves(feasibility), storylet, source_affordance, confidence)


def bind_resolution(
    card: Mapping[str, Any], *, completed: Iterable[str], resolution: IntentResolution,
    branch_progress: Iterable[str] = (),
) -> IntentResolution:
    """Restore non-public storylet constraints after semantic matching."""
    advertised = {
        item.affordance.affordance_id: item
        for item in advertised_affordances(card, completed=completed, branch_progress=branch_progress)
    }
    item = advertised.get(resolution.advertised.affordance.affordance_id)
    if item is None or not item.affordance.available or item.affordance.pending_human:
        raise ValueError("matched opportunity is no longer reachable")
    spec = item.storylet
    entries = _clean_tuple(spec.get("entry_conditions")) or resolution.storylet.entry_conditions
    invariants = _clean_tuple(spec.get("invariants")) or resolution.storylet.invariants
    exits = _clean_tuple(spec.get("exit_keys")) or resolution.storylet.exit_keys
    storylet = EphemeralStorylet(
        storylet_id=resolution.storylet.storylet_id,
        intent_id=resolution.storylet.intent_id,
        source_affordance_id=resolution.storylet.source_affordance_id,
        entry_conditions=entries,
        invariants=invariants,
        exit_keys=exits,
        expiry_clock=str(spec.get("expiry_clock", "") or ""),
    )
    feasibility = classify_feasibility(resolution.feasibility.intent, (item.affordance,))
    return IntentResolution(
        feasibility, plan_director_moves(feasibility), storylet, item, resolution.confidence
    )


def decision_request_for_actor(
    resolution: IntentResolution, actor_cons: str
) -> dict[str, Any] | None:
    """Deliver a choice to exactly one actor without smuggling in an answer."""
    target = resolution.feasibility.intent.target
    if not target or str(actor_cons) != target or resolution.feasibility.status != "negotiate_now":
        return None
    return {
        "intent_id": resolution.feasibility.intent.intent_id,
        "goal_text": resolution.feasibility.intent.goal_text,
        "player_observable_attempt": True,
        "valid_outcomes": list(resolution.storylet.exit_keys),
        "rules": [
            "Decide only from facts in your own actor packet.",
            "Relationship and current goals are reasons to weigh, not numeric gates.",
            "You may accept, condition, refuse, offer an alternative, defer, or later revise.",
            "State only what you visibly say or do; do not reveal hidden reasoning.",
        ],
        "output_contract": {
            "actor_cons": target,
            "intent_id": resolution.feasibility.intent.intent_id,
            "outcome": "one valid_outcomes value",
            "visible_response": "observable speech/action",
            "reason_sources": "actor-owned packet paths only",
            "conditions": "list; required for conditional",
            "uncertainty": "optional actor uncertainty",
            "commitment": "optional explicit promise or alternative help",
            "revises_decision_id": "optional prior decision id",
        },
    }


def ensure_decision_target_in_speaker_plan(
    speaker_plan: Mapping[str, Any], resolution: IntentResolution
) -> dict[str, Any]:
    """Give the addressed actor a response slot without altering its choice."""
    result = {key: value for key, value in speaker_plan.items()}
    result["speakers"] = [dict(item) for item in speaker_plan.get("speakers", ())]
    result["stage_actors"] = [dict(item) for item in speaker_plan.get("stage_actors", ())]
    target = resolution.feasibility.intent.target
    if not target or resolution.feasibility.status != "negotiate_now":
        return result
    existing = next((item for item in result["speakers"] if item.get("cons") == target), None)
    if existing is None:
        result["stage_actors"] = [item for item in result["stage_actors"] if item.get("cons") != target]
        result["speakers"].insert(0, {
            "cons": target,
            "name": target,
            "bid": 0.0,
            "reason": "observable_intent_target",
            "bid_reasons": ["observable_intent_target"],
            "relation_stage": "actor_owned",
            "response_slot": "primary",
            "social_instruction": "respond_to_observable_request_from_own_position",
        })
    else:
        existing["response_slot"] = "primary"
        existing["social_instruction"] = "respond_to_observable_request_from_own_position"
    for index, item in enumerate(result["speakers"]):
        if item.get("cons") != target and index > 0 and item.get("response_slot") == "primary":
            item["response_slot"] = "secondary"
    result["direct_addressee"] = target
    result["conversation_contract"] = {
        "kind": "observable_intent_request",
        "target_cons": target,
        "evidence": resolution.feasibility.intent.intent_id,
    }
    return result


def retarget_resolution(resolution: IntentResolution, target_cons: str) -> IntentResolution:
    """Bind a run-local body after a card selected an ambient role.

    The card still owns reachability and the actor still owns its decision;
    this only substitutes the newly observed consciousness for a role marker.
    """
    target = str(target_cons or "").strip()
    if not target:
        raise ValueError("retargeted intent must name a consciousness")
    intent = resolution.feasibility.intent
    rebound = type(intent)(**{**intent.to_dict(), "target": target})
    feasibility = classify_feasibility(rebound, resolution.feasibility.candidates)
    return IntentResolution(
        feasibility, plan_director_moves(feasibility), resolution.storylet,
        resolution.advertised, resolution.confidence,
    )
