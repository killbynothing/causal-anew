"""Data-driven exit selection and transition eligibility.

This service deliberately knows no scene or card identifiers. A card declares
its own intent tokens and whether an incomplete scene may force that exit; the
session orchestrator supplies exceptional hard-event facts as arguments.
"""
from __future__ import annotations

import re
from typing import Any

from runtime.name_book import normalize_public_location_aliases


EXIT_INTENT_RE = re.compile(
    r"(离开|走了|走吧|撤离|撤回|撤退|退场|下一场|去下一处|出发|去京津高速|去天津|回天津|去十六中|到十六中|路过十六中|去医院|送医|回头见|再见|回见|先走|告辞|go|leave|exit|next)",
    re.IGNORECASE,
)


def player_input_text(player_input: str | dict[str, str]) -> str:
    if isinstance(player_input, dict):
        text = str(player_input.get("speech", "") or player_input.get("action", "") or "")
    else:
        text = str(player_input or "")
    return normalize_public_location_aliases(text)


def all_must_happen_complete(card: dict[str, Any], completed: list[str]) -> bool:
    required = {str(item.get("id")) for item in card.get("must_happen", []) if item.get("id")}
    return required.issubset({str(item) for item in completed})


def stall_budget_for_card(card: dict[str, Any]) -> int:
    try:
        return max(1, int(card.get("soft_beat_budget", 4)))
    except Exception:
        return 4


def _matching_exit_intents(card: dict[str, Any], text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for raw in card.get("exits", []) or []:
        if not isinstance(raw, dict):
            continue
        tokens = raw.get("intent_tokens", [])
        if isinstance(tokens, list) and any(str(token) and str(token) in text for token in tokens):
            matches.append(raw)
    return matches


def exit_requirements_met(
    exit_spec: dict[str, Any], *, branch_progress: set[str] | None = None,
    actor_decisions: list[dict[str, Any]] | None = None,
) -> bool:
    """Check route facts that must exist before an exit can be offered.

    An exit may depend on role-owned decisions, but never supplies or guesses
    them.  This makes a hospital bridge a consequence of visible movement,
    rather than a second mechanism that silently moves the cast.
    """
    branches = set(branch_progress or set())
    needed_branches = {str(item).strip() for item in exit_spec.get("requires_branch_progress", ()) if str(item).strip()}
    if not needed_branches.issubset(branches):
        return False
    outcomes = exit_spec.get("requires_autonomous_outcomes", {})
    if not isinstance(outcomes, dict):
        return not outcomes
    actual = {
        str(item.get("autonomous_decision_id", "")): str(item.get("outcome", ""))
        for item in actor_decisions or [] if isinstance(item, dict)
    }
    if not all(actual.get(str(decision_id)) == str(outcome) for decision_id, outcome in outcomes.items()):
        return False
    legacy = exit_spec.get("requires_actor_decisions", {})
    if not isinstance(legacy, dict):
        return not legacy
    latest_by_actor: dict[str, str] = {}
    for item in actor_decisions or []:
        if isinstance(item, dict):
            latest_by_actor[str(item.get("actor_cons", ""))] = str(item.get("outcome", ""))
    return all(
        latest_by_actor.get(str(actor_cons)) in {str(value) for value in allowed}
        for actor_cons, allowed in legacy.items() if isinstance(allowed, (list, tuple, set))
    )


def should_trigger_exit(
    player_input: str | dict[str, str], completed: list[str], card: dict[str, Any], stall: int = 0,
    *, hard_phone_ids: set[str] | None = None, hospital_bound: bool = False, hospital_follow: bool = False,
) -> tuple[bool, str]:
    if not card.get("exits"):
        return (False, "none")
    mh_complete = all_must_happen_complete(card, completed)
    text = player_input_text(player_input)
    intent_exits = _matching_exit_intents(card, text)
    has_intent = bool(EXIT_INTENT_RE.search(text)) or bool(intent_exits)
    if not mh_complete and any(not bool(spec.get("allow_forced_exit_before_must", True)) for spec in intent_exits):
        has_intent = False
    phone_ids = set(hard_phone_ids or set())
    phone_done = (not phone_ids) or phone_ids.issubset({str(item) for item in completed})
    if hospital_bound and phone_ids and not phone_done:
        return (False, "none")
    if hospital_bound and phone_ids and phone_done:
        return (True, "normal") if hospital_follow else (False, "none")
    # A beat budget may make NPCs finish their own business or surface a new
    # opportunity, but it cannot silently decide that the player walked away.
    # Cards may opt into an explicitly audited non-player transfer (for a
    # physical emergency, never ordinary pacing) with allow_stall_exit.
    allow_stall_exit = any(bool(spec.get("allow_stall_exit", False)) for spec in card.get("exits", ()) if isinstance(spec, dict))
    if mh_complete and (has_intent or (allow_stall_exit and stall >= stall_budget_for_card(card))):
        return (True, "normal")
    if not mh_complete and (has_intent or (allow_stall_exit and stall >= stall_budget_for_card(card))):
        return (True, "forced")
    return (False, "none")


def choose_exit_spec(
    exits: list[dict[str, Any]], player_input: str | dict[str, str], active_exit_state: str = "converged",
) -> dict[str, Any]:
    if not exits:
        return {}
    if len(exits) == 1:
        return dict(exits[0])
    text = player_input_text(player_input)
    mapped = {"intervene": "intervened", "watch": "watched"}.get(str(active_exit_state or "").strip())
    if mapped:
        for spec in exits:
            if str(spec.get("exit_state", "")).strip() == mapped:
                return dict(spec)
    for spec in exits:
        tokens = spec.get("intent_tokens", [])
        if isinstance(tokens, list) and any(str(token) and str(token) in text for token in tokens):
            return dict(spec)
    invited_tokens = ("一起", "同行", "跟你们", "跟你一起", "跟着你们", "跟你走", "走吧", "一起走")
    goodbye_tokens = ("道别", "告辞", "回头见", "先走", "再见", "回见")
    invited = any(token in text for token in invited_tokens)
    goodbye = any(token in text for token in goodbye_tokens)
    for spec in exits:
        state = str(spec.get("exit_state", "")).strip()
        if state == "converged" and goodbye and not invited:
            return dict(spec)
        if state == "invited" and invited:
            return dict(spec)
    return dict(exits[0])
