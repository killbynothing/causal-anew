"""Deterministic contract for the director's intent-to-opportunity layer.

The director may arrange a playable opportunity, never an actor's choice or a
player's physical action.  This module is deliberately Session-free and
scene-id-free so it can be used by any frame without adding another special
case to the orchestration layer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping


Feasibility = Literal[
    "private", "do_now", "negotiate_now", "prepare", "route", "defer", "blocked"
]

_FEASIBILITIES = {"private", "do_now", "negotiate_now", "prepare", "route", "defer", "blocked"}
_AFFORDANCE_MODES = {"do_now", "negotiate_now", "prepare", "route", "defer"}
_DIRECTOR_MOVE_KINDS = {"foreground", "bridge", "wait", "counteroffer"}
_ACTOR_OUTCOMES = {
    "accept", "conditional", "refuse", "alternative", "defer", "evade", "leave"
}
_FORBIDDEN_DIRECTOR_KEYS = {
    "actor_decision", "decision", "accepted", "accept", "refuse", "refused", "outcome",
}


def public_modalities(player_input: str | Mapping[str, Any] | None) -> dict[str, str]:
    """Return only speech/action; private thought is never an external act."""
    if isinstance(player_input, Mapping):
        return {
            "speech": str(player_input.get("speech", "") or "").strip(),
            "action": str(player_input.get("action", "") or "").strip(),
        }
    return {"speech": str(player_input or "").strip(), "action": ""}


@dataclass(frozen=True)
class IntentProposal:
    """A semantic reading produced upstream; this layer only enforces its bounds."""

    intent_id: str
    goal_key: str
    goal_text: str
    target: str = ""
    requires_actor_consent: bool = False
    tags: tuple[str, ...] = ()
    expiry_clock: str = ""

    def __post_init__(self) -> None:
        for name in ("intent_id", "goal_key", "goal_text"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"IntentProposal.{name} must not be blank")


@dataclass(frozen=True)
class IntentThread:
    intent_id: str
    goal_key: str
    goal_text: str
    target: str
    observable: bool
    status: Feasibility
    turn: int
    expiry_clock: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Affordance:
    """A source-bound opportunity, not a promised outcome."""

    affordance_id: str
    intent_keys: tuple[str, ...]
    mode: Feasibility
    source: str
    location: str
    available: bool = True
    pending_human: bool = False
    requires_actor_consent: bool = False
    score: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.affordance_id.strip() or not self.source.strip() or not self.location.strip():
            raise ValueError("Affordance id/source/location must not be blank")
        if self.mode not in _AFFORDANCE_MODES:
            raise ValueError(f"Affordance.mode is not playable: {self.mode}")
        if not self.intent_keys:
            raise ValueError("Affordance.intent_keys must not be empty")


@dataclass(frozen=True)
class DirectorMove:
    kind: str
    affordance_id: str
    intent_id: str
    visible_reason: str
    actor_target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeasibilityResult:
    status: Feasibility
    intent: IntentThread
    candidates: tuple[Affordance, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "intent": self.intent.to_dict(),
            "candidates": [asdict(item) for item in self.candidates],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ActorDecision:
    """An actor-owned response; director-private reasoning is prohibited."""

    actor_cons: str
    intent_id: str
    outcome: str
    visible_response: str
    reason_sources: tuple[str, ...]
    conditions: tuple[str, ...] = ()
    uncertainty: str = ""
    commitment: str = ""
    revises_decision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EphemeralStorylet:
    """A run-local attempt assembled from an approved affordance.

    It records constraints and exits, not authored canon facts.  Persistence is
    handled as append-only events by ``runtime.runtime_state``.
    """

    storylet_id: str
    intent_id: str
    source_affordance_id: str
    entry_conditions: tuple[str, ...]
    invariants: tuple[str, ...]
    exit_keys: tuple[str, ...]
    expiry_clock: str = ""

    def __post_init__(self) -> None:
        for name in ("storylet_id", "intent_id", "source_affordance_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"EphemeralStorylet.{name} must not be blank")
        if not self.invariants:
            raise ValueError("EphemeralStorylet must carry at least one invariant")
        if not self.exit_keys:
            raise ValueError("EphemeralStorylet must carry at least one exit")

    def created_payload(self) -> dict[str, Any]:
        return asdict(self)


def open_intent_thread(
    proposal: IntentProposal,
    player_input: str | Mapping[str, Any] | None,
    *,
    turn: int,
) -> IntentThread:
    """Make an intent auditable without converting thought into action."""
    modalities = public_modalities(player_input)
    observable = bool(modalities["speech"] or modalities["action"])
    return IntentThread(
        intent_id=proposal.intent_id,
        goal_key=proposal.goal_key,
        goal_text=proposal.goal_text,
        target=proposal.target,
        observable=observable,
        status="defer" if observable else "private",
        turn=max(0, int(turn)),
        expiry_clock=proposal.expiry_clock,
        tags=tuple(str(tag).strip() for tag in proposal.tags if str(tag).strip()),
    )


def classify_feasibility(intent: IntentThread, affordances: Iterable[Affordance]) -> FeasibilityResult:
    """Apply deterministic availability/policy gates before any director prose."""
    if not intent.observable:
        return FeasibilityResult("private", intent, reason="private thought is not a public attempt")
    candidates = tuple(
        sorted(
            (
                item for item in affordances
                if item.available and not item.pending_human and intent.goal_key in item.intent_keys
            ),
            key=lambda item: (-item.score, item.affordance_id),
        )
    )
    if not candidates:
        return FeasibilityResult("blocked", intent, reason="no approved, reachable affordance")
    selected = candidates[0]
    status: Feasibility = "negotiate_now" if (
        intent.target or selected.requires_actor_consent
    ) and (selected.requires_actor_consent or selected.mode == "negotiate_now") else selected.mode
    updated = IntentThread(**{**intent.to_dict(), "status": status})
    return FeasibilityResult(status, updated, candidates=candidates, reason=selected.reason)


def validate_director_move(move: DirectorMove | Mapping[str, Any]) -> None:
    raw = move.to_dict() if isinstance(move, DirectorMove) else dict(move)
    kind = str(raw.get("kind", "")).strip()
    if kind not in _DIRECTOR_MOVE_KINDS:
        raise ValueError(f"unsupported director move: {kind}")
    if not str(raw.get("affordance_id", "")).strip() or not str(raw.get("intent_id", "")).strip():
        raise ValueError("director move must identify its affordance and intent")
    forbidden = _FORBIDDEN_DIRECTOR_KEYS.intersection(raw)
    if forbidden:
        raise ValueError("director move may not decide actor outcome: " + ", ".join(sorted(forbidden)))


def validate_actor_decision(decision: ActorDecision | Mapping[str, Any]) -> None:
    """Check provenance, not whether the character pleased the player."""
    raw = decision.to_dict() if isinstance(decision, ActorDecision) else dict(decision)
    if not str(raw.get("actor_cons", "")).strip() or not str(raw.get("intent_id", "")).strip():
        raise ValueError("actor decision must name its actor and intent")
    outcome = str(raw.get("outcome", "")).strip()
    if outcome not in _ACTOR_OUTCOMES:
        raise ValueError(f"unsupported actor outcome: {outcome}")
    sources = tuple(str(item).strip() for item in raw.get("reason_sources", ()) if str(item).strip())
    if not sources:
        raise ValueError("actor decision must cite actor-owned sources")
    if any(source.startswith(("director_private", "director.")) for source in sources):
        raise ValueError("actor decision may not cite director-private knowledge")
    if outcome == "conditional" and not tuple(str(item).strip() for item in raw.get("conditions", ()) if str(item).strip()):
        raise ValueError("conditional actor decision must state a condition")
    if outcome == "alternative" and not str(raw.get("commitment", "") or "").strip():
        raise ValueError("alternative actor decision must state the offered commitment")


def commit_actor_decision(result: FeasibilityResult, decision: ActorDecision) -> ActorDecision:
    """Bind a decision to the open negotiation without selecting its outcome."""
    validate_actor_decision(decision)
    if result.status != "negotiate_now":
        raise ValueError("actor decisions only commit against negotiate_now intents")
    if decision.intent_id != result.intent.intent_id:
        raise ValueError("actor decision belongs to another intent")
    if result.intent.target and decision.actor_cons != result.intent.target:
        raise ValueError("actor decision belongs to another actor")
    return decision


def plan_director_moves(result: FeasibilityResult) -> tuple[DirectorMove, ...]:
    """Return at most one opportunity move; never fabricate a success result."""
    if result.status in {"private", "blocked"} or not result.candidates:
        return ()
    selected = result.candidates[0]
    kind = "foreground" if result.status in {"do_now", "negotiate_now"} else "bridge"
    move = DirectorMove(
        kind=kind,
        affordance_id=selected.affordance_id,
        intent_id=result.intent.intent_id,
        visible_reason=selected.reason or "世界给出一次可尝试的机会。",
        actor_target=result.intent.target if result.status == "negotiate_now" else "",
    )
    validate_director_move(move)
    return (move,)
