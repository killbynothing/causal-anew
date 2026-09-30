"""P1a single authority for exit decisions.

This module decides only whether the current scene continues, waits for a
confirmation/menu, transitions to one concrete target, or ends the run.
It never mutates session/world/beat state and never performs persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime import transition_service


@dataclass(frozen=True)
class ExitRequest:
    card: Mapping[str, Any]
    completed: tuple[str, ...]
    player_input: str | Mapping[str, str]
    stall: int = 0
    active_exit_state: str = "converged"
    branch_progress: frozenset[str] = frozenset()
    actor_decisions: tuple[Mapping[str, Any], ...] = ()
    selected_exit_spec: Mapping[str, Any] | None = None
    semantic_exit_spec: Mapping[str, Any] | None = None
    confirmed_exit_spec: Mapping[str, Any] | None = None
    pending_confirmation: bool = False
    confirmation_cancelled: bool = False
    force_transition: bool = False
    force_reason: str = ""
    standalone_end: bool = False
    exit_menu: bool = False
    flashback_target_ref: str | None = None
    pending_entry_target_ref: str | None = None
    explicit_auto_end: bool = False
    explicit_auto_end_reason: str = ""


@dataclass(frozen=True)
class ExitDecision:
    action: str  # continue | await_confirmation | show_menu | transition | end_run
    mode: str = "none"  # none | normal | forced
    reason: str = ""
    exit_spec: dict[str, Any] | None = None
    target_kind: str | None = None
    target_ref: str | None = None
    confirmation_action: str = "clear"  # clear | set | keep
    prospective_branch_facts: tuple[str, ...] = ()

    @property
    def authorized(self) -> bool:
        return self.action in {"transition", "end_run"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "mode": self.mode,
            "reason": self.reason,
            "exit_spec": dict(self.exit_spec) if self.exit_spec else None,
            "target_kind": self.target_kind,
            "target_ref": self.target_ref,
            "confirmation_action": self.confirmation_action,
            "prospective_branch_facts": list(self.prospective_branch_facts),
        }


def _public_input_text(player_input: str | Mapping[str, str]) -> str:
    return transition_service.player_input_text(
        dict(player_input) if isinstance(player_input, Mapping) else player_input
    )


def _candidate_spec(req: ExitRequest) -> tuple[dict[str, Any], str]:
    for spec, source in (
        (req.confirmed_exit_spec, "confirmed"),
        (req.semantic_exit_spec, "semantic"),
        (req.selected_exit_spec, "selected"),
    ):
        if isinstance(spec, Mapping):
            return dict(spec), source
    exits = [dict(item) for item in req.card.get("exits", ()) if isinstance(item, Mapping)]
    if not exits:
        return {}, "none"
    return (
        transition_service.choose_exit_spec(
            exits,
            dict(req.player_input) if isinstance(req.player_input, Mapping) else req.player_input,
            req.active_exit_state,
        ),
        "chosen",
    )


def _target_for(
    req: ExitRequest,
    exit_spec: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    if req.flashback_target_ref:
        return ("flashback_return", req.flashback_target_ref)
    if bool(exit_spec.get("target_pending_entry")):
        if req.pending_entry_target_ref:
            return ("pending_entry", req.pending_entry_target_ref)
        return (None, None)
    target = str(exit_spec.get("target_card", "") or "").strip()
    if target:
        return ("card", target)
    return (None, None)


def decide_exit(req: ExitRequest) -> ExitDecision:
    """Resolve one exit decision without mutating runtime state."""
    card = dict(req.card)
    completed = [str(x) for x in req.completed]
    all_complete = transition_service.all_must_happen_complete(card, completed)
    exits = [dict(item) for item in card.get("exits", ()) if isinstance(item, Mapping)]
    text = _public_input_text(req.player_input)
    matched_exit_specs = [
        spec
        for spec in exits
        if isinstance(spec.get("intent_tokens", ()), (list, tuple))
        and any(str(token) and str(token) in text for token in spec.get("intent_tokens", ()))
    ]
    declared_intent = bool(matched_exit_specs)
    explicit_intent = transition_service.has_global_exit_intent(text) or declared_intent

    prospective: tuple[str, ...] = ()
    if isinstance(req.semantic_exit_spec, Mapping):
        receipt = str(req.semantic_exit_spec.get("semantic_receipt", "") or "").strip()
        if receipt:
            prospective = (receipt,)

    # A pending confirmation must preserve the originally audited target.
    if req.pending_confirmation:
        if req.confirmation_cancelled:
            return ExitDecision(
                action="continue",
                reason="confirmation_cancelled",
                confirmation_action="clear",
            )
        if not isinstance(req.confirmed_exit_spec, Mapping):
            return ExitDecision(
                action="continue",
                reason="confirmation_target_missing",
                confirmation_action="clear",
            )
        should_exit, mode = True, "forced"
        source = "confirmed"
        candidate = dict(req.confirmed_exit_spec)
    else:
        candidate, source = _candidate_spec(req)
        if req.flashback_target_ref:
            should_exit, mode = True, "normal"
            source = "flashback_return"
        elif req.force_transition:
            should_exit, mode = True, "normal"
            source = req.force_reason or "forced_ready"
        elif isinstance(req.semantic_exit_spec, Mapping):
            should_exit, mode = True, "normal"
        elif isinstance(req.selected_exit_spec, Mapping):
            should_exit, mode = True, "normal"
        else:
            should_exit, mode = transition_service.should_trigger_exit(
                dict(req.player_input) if isinstance(req.player_input, Mapping) else req.player_input,
                completed,
                card,
                req.stall,
            )

    # A card may explicitly opt into auto-end. Mere MH completion is never enough.
    if (
        not should_exit
        and req.explicit_auto_end
        and all_complete
    ):
        return ExitDecision(
            action="end_run",
            mode="normal",
            reason=req.explicit_auto_end_reason or "explicit_auto_end",
            confirmation_action="clear",
        )

    if not should_exit:
        return ExitDecision(
            action="continue",
            reason="no_exit_signal",
            confirmation_action="clear",
        )

    # Requirements are checked against committed facts plus this semantic
    # selection's prospective receipt. The receipt is not committed unless the
    # decision is authorized.
    branches = set(req.branch_progress)
    branches.update(prospective)
    if candidate and not transition_service.exit_requirements_met(
        candidate,
        branch_progress=branches,
        actor_decisions=[dict(x) for x in req.actor_decisions],
    ):
        return ExitDecision(
            action="continue",
            mode="none",
            reason="exit_requirements_unmet",
            exit_spec=candidate,
            confirmation_action="clear",
            prospective_branch_facts=prospective,
        )

    menu_needs_choice = bool(
        req.exit_menu
        and len(exits) > 1
        and req.selected_exit_spec is None
        and req.semantic_exit_spec is None
        and req.confirmed_exit_spec is None
        and not req.flashback_target_ref
        and not matched_exit_specs
    )
    if menu_needs_choice:
        return ExitDecision(
            action="show_menu",
            mode=mode,
            reason="exit_menu_requires_player_choice",
            confirmation_action="clear",
            prospective_branch_facts=prospective,
        )

    # Incomplete-scene player exits preserve the legacy one-beat confirmation,
    # and the exact audited target is frozen for the next beat.
    if mode == "forced" and not req.pending_confirmation and explicit_intent:
        return ExitDecision(
            action="await_confirmation",
            mode="forced",
            reason=f"await_confirmation:{source}",
            exit_spec=candidate or None,
            confirmation_action="set",
            prospective_branch_facts=prospective,
        )

    if req.standalone_end:
        return ExitDecision(
            action="end_run",
            mode=mode,
            reason="standalone_scene_exit",
            exit_spec=candidate or None,
            confirmation_action="clear",
            prospective_branch_facts=prospective,
        )

    target_kind, target_ref = _target_for(req, candidate)
    if not target_ref:
        return ExitDecision(
            action="continue",
            mode="none",
            reason="authorized_exit_missing_target",
            exit_spec=candidate or None,
            confirmation_action="clear",
            prospective_branch_facts=prospective,
        )

    return ExitDecision(
        action="transition",
        mode=mode,
        reason=f"authorized:{source}",
        exit_spec=candidate or None,
        target_kind=target_kind,
        target_ref=target_ref,
        confirmation_action="clear",
        prospective_branch_facts=prospective,
    )
