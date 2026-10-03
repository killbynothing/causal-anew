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

from runtime.npc_fsm import NpcFSM


SCHEMA_VERSION = "free_stage.actor_mind.v2"
RELATION_FACETS = ("trust", "intimacy", "alert", "cooperation")
RESPONSE_KINDS = ("accept", "refuse", "defer", "offer_alternative", "ask_evidence", "set_boundary")
LEGACY_OPENING_COMPAT_KEY = "legacy_opening_compat"


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
    working = (
        source.get("scene_working_memory")
        if isinstance(source.get("scene_working_memory"), Mapping)
        else {}
    )
    authored_goals = _unique_text(working.get("goals", ()) or ())
    authored_commitments = _unique_text(working.get("commitments", ()) or ())
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
            "active_goals": authored_goals or ([goal] if goal else []),
            "conflicting_motives": [],
            "commitments": authored_commitments,
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


def observer_state_projection(
    mind: Mapping[str, Any] | None,
    *,
    working_context: Mapping[str, Any] | None = None,
    decide: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Single observatory shape: ActorMind is authority, turn context is a projection.

    The legacy/private working context remains useful for explaining the current
    beat, but it is explicitly subordinate and must never look like a second
    persistent mind.
    """
    working = dict(working_context or {})
    decision = dict(decide or {})
    keep_working = {
        key: copy.deepcopy(working[key])
        for key in (
            "attention_target", "observation_status", "observation",
            "response_intent", "inhibition", "visible_decision",
            "top_concern", "pending_concerns", "updated_at_turn",
        )
        if key in working
    }
    keep_decide = {
        key: copy.deepcopy(decision[key])
        for key in (
            "top_concern_id", "top_concern", "band",
            "participation_mode", "intention",
        )
        if key in decision
    }
    return {
        "authority": "actor_mind",
        "persistent": observer_safe_summary(mind),
        "working_context": keep_working,
        "decide": keep_decide,
    }


def _valid_receipt(
    receipt: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    if not isinstance(receipt, Mapping):
        return None
    if _text(receipt.get("schema_version")) != "free_stage.causal_receipt.v1":
        return None
    receipt_id = _text(receipt.get("receipt_id"))
    observation = receipt.get("observation") if isinstance(receipt.get("observation"), Mapping) else {}
    proposal = receipt.get("proposal") if isinstance(receipt.get("proposal"), Mapping) else {}
    event = receipt.get("event") if isinstance(receipt.get("event"), Mapping) else {}
    if (
        not receipt_id
        or not _text(observation.get("observation_id"))
        or not _text(observation.get("actor_cons"))
        or not _text(proposal.get("proposal_id"))
        or not _text(event.get("event_id"))
    ):
        return None
    if _text(event.get("proposal_id")) != _text(proposal.get("proposal_id")):
        return None
    if _text(proposal.get("observation_id")) != _text(observation.get("observation_id")):
        return None
    return receipt_id, dict(observation), dict(proposal), dict(event)


def _scope_matches(
    receipt: Mapping[str, Any] | None,
    expected_scope: Mapping[str, Any] | Any | None,
) -> bool:
    if expected_scope is None:
        return True
    if not isinstance(receipt, Mapping):
        return False
    raw_scope = receipt.get("scope")
    if not isinstance(raw_scope, Mapping):
        return False
    if hasattr(expected_scope, "to_dict"):
        expected = dict(expected_scope.to_dict())
    elif isinstance(expected_scope, Mapping):
        expected = dict(expected_scope)
    else:
        return False
    keys = ("worldline", "run", "ch_anchor", "session_id", "scene_instance_id")
    return all(raw_scope.get(key) == expected.get(key) for key in keys)


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
    expected_scope: Mapping[str, Any] | Any | None = None,
) -> tuple[dict[str, Any], bool]:
    """Apply one resolver receipt once. Invalid/missing receipts are no-ops."""
    current = copy.deepcopy(dict(mind or {}))
    if not _scope_matches(receipt, expected_scope):
        return current, False
    valid = _valid_receipt(receipt)
    if valid is None:
        return current, False
    receipt_id, observation, proposal, event = valid
    own_cons = _text(actor_cons or current.get("actor_cons"))
    if not own_cons or _text(observation.get("actor_cons")) != own_cons:
        return current, False
    appraisal = current.get("appraisal_state") if isinstance(current.get("appraisal_state"), Mapping) else {}
    seen = {_text(item) for item in appraisal.get("receipt_ids", ()) or ()}
    if receipt_id in seen:
        return current, False

    receipt_actor = _text(proposal.get("actor_cons"))
    if not receipt_actor:
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


def build_turn_working_context(
    mind: Mapping[str, Any] | None,
    persona_inner: Mapping[str, Any] | None,
    *,
    observed_player: Mapping[str, Any] | None = None,
    turn: int = 0,
    response_slot: str = "",
    visible_decision: str = "",
    current_ephemeral: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild disposable turn context from authoritative Mind + current visible input.

    No prior free-form working state is treated as psychological authority.  The
    only values carried from an existing turn context are whitelisted ephemeral
    fields produced during the same turn (currently concern routing).
    """
    seed = copy.deepcopy(dict(persona_inner or {}))
    mental = dict(mind or {})
    motivation = (
        mental.get("motivational_state")
        if isinstance(mental.get("motivational_state"), Mapping)
        else {}
    )
    expression = (
        mental.get("expression_policy")
        if isinstance(mental.get("expression_policy"), Mapping)
        else {}
    )
    appraisal = (
        mental.get("appraisal_state")
        if isinstance(mental.get("appraisal_state"), Mapping)
        else {}
    )
    observed = {
        str(key): str(value)
        for key, value in dict(observed_player or {}).items()
        if str(key).strip() and str(value).strip()
    }
    active_goals = _unique_text(motivation.get("active_goals", ()) or ())
    base_goal = active_goals[0] if active_goals else _text(seed.get("want_now"))
    if not base_goal:
        base_goal = "维持当前现场目标"

    out = seed
    out["version"] = max(0, int(turn))
    out["updated_at_turn"] = max(0, int(turn))
    out["status"] = "fresh"
    out["want_now"] = base_goal
    out["active_goals"] = active_goals or [base_goal]
    out["authority_source"] = "actor_mind+visible_scene"
    out["last_mind_receipt_id"] = _text(
        (mental.get("public_state") or {}).get("last_receipt_id")
        if isinstance(mental.get("public_state"), Mapping)
        else ""
    )
    if observed:
        out["attention_target"] = "player"
        out["observation_status"] = "player_signal_received"
        out["basis"] = [f"player:{field}" for field in observed]
        out["observation"] = [
            f"{field}:{value[:80]}" for field, value in observed.items()
        ]
    else:
        out["attention_target"] = "scene"
        out["observation_status"] = "no_new_player_signal"
        out["basis"] = ["scene_tick:no_player_signal"]
        out["observation"] = ["scene:no_new_player_signal"]

    receipt_impact = _text(appraisal.get("last_goal_impact"))
    if observed:
        out["appraisal"] = (
            "玩家已进入自己的可感知范围，需要按当前关系与目标作出反应。"
        )
    elif receipt_impact == "observed_other":
        out["appraisal"] = "已登记可见事件，继续按当前目标处理现场。"
    else:
        out["appraisal"] = "没有新的玩家信号，继续处理眼前人物与既定目标。"

    slot = _text(response_slot)
    if slot == "primary":
        out["response_intent"] = "直接承接玩家；可以回答、拒答或明确延后。"
        out["inhibition"] = "不替其他角色作答，不另起第二个问题。"
    elif slot == "secondary":
        out["response_intent"] = "只做短促附和、保护、纠正或打圆场。"
        out["inhibition"] = "不抢主回应，不另起话题。"
    else:
        out["response_intent"] = "保持沉默并继续观察。"
        out["inhibition"] = "没有响应槽，不为争取戏份开口。"
    out["visible_decision"] = _text(visible_decision) or "本拍没有公开发言"

    current = dict(current_ephemeral or {})
    for key in ("pending_concerns", "top_concern", "top_concern_id"):
        if key in current:
            out[key] = copy.deepcopy(current[key])
    stance = _text(expression.get("current_public_stance")) or _text(
        expression.get("default_public_stance")
    )
    if stance:
        out["stance_to_player"] = stance
    return out


class TurnWorkingContextState:
    """Mutable owner for per-turn/per-scene working context, not persistent psychology."""

    def __init__(self, contexts: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._contexts: dict[str, dict[str, Any]] = {
            _text(cons): copy.deepcopy(dict(state))
            for cons, state in dict(contexts or {}).items()
            if _text(cons) and isinstance(state, Mapping)
        }

    @classmethod
    def empty(cls) -> "TurnWorkingContextState":
        return cls()

    @classmethod
    def from_snapshot(cls, raw: Any) -> "TurnWorkingContextState":
        if raw is None:
            return cls.empty()
        if not isinstance(raw, Mapping):
            raise ValueError("private_inner_states snapshot must be a mapping")
        return cls(raw)

    @property
    def contexts(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._contexts)

    def get(self, actor_cons: str) -> dict[str, Any] | None:
        row = self._contexts.get(_text(actor_cons))
        return copy.deepcopy(row) if isinstance(row, dict) else None

    def set_context(self, actor_cons: str, state: Mapping[str, Any]) -> None:
        cons = _text(actor_cons)
        if not cons:
            raise ValueError("working context requires actor_cons")
        self._contexts[cons] = copy.deepcopy(dict(state))

    def patch(self, actor_cons: str, values: Mapping[str, Any]) -> dict[str, Any]:
        cons = _text(actor_cons)
        if not cons:
            raise ValueError("working context patch requires actor_cons")
        row = copy.deepcopy(self._contexts.get(cons, {}))
        row.update(copy.deepcopy(dict(values)))
        self._contexts[cons] = row
        return copy.deepcopy(row)

    def replace(self, contexts: Mapping[str, Mapping[str, Any]] | None) -> None:
        self._contexts = {
            _text(cons): copy.deepcopy(dict(state))
            for cons, state in dict(contexts or {}).items()
            if _text(cons) and isinstance(state, Mapping)
        }

    def reset(self) -> None:
        self._contexts = {}


class ReflectProposalState:
    """One-step Reflect proposal cache; never a persistent psychological owner."""

    def __init__(self, proposals: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._proposals: dict[str, dict[str, Any]] = {
            _text(cons): copy.deepcopy(dict(row))
            for cons, row in dict(proposals or {}).items()
            if _text(cons) and isinstance(row, Mapping)
        }

    @classmethod
    def empty(cls) -> "ReflectProposalState":
        return cls()

    @classmethod
    def from_snapshot(cls, raw: Any) -> "ReflectProposalState":
        if raw is None:
            return cls.empty()
        if not isinstance(raw, Mapping):
            raise ValueError("prior_reflect_by_cons snapshot must be a mapping")
        return cls(raw)

    @property
    def proposals(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._proposals)

    def get(self, actor_cons: str) -> dict[str, Any] | None:
        row = self._proposals.get(_text(actor_cons))
        return copy.deepcopy(row) if isinstance(row, dict) else None

    def set(self, actor_cons: str, proposal: Mapping[str, Any]) -> None:
        cons = _text(actor_cons)
        if not cons:
            raise ValueError("reflect proposal requires actor_cons")
        self._proposals[cons] = copy.deepcopy(dict(proposal))

    def reset(self) -> None:
        self._proposals = {}


class ActorMindState:
    """Single mutable owner for persisted ActorMind snapshots.

    Callers receive defensive copies.  Seeding is allowed only from the existing
    persona projection; subsequent persistent updates must enter through a
    validated receipt reducer.
    """

    def __init__(
        self,
        minds: Mapping[str, Any] | None = None,
        *,
        legacy_audit: Mapping[str, Any] | None = None,
    ) -> None:
        self._minds: dict[str, dict[str, Any]] = {}
        self._legacy_audit: dict[str, dict[str, Any]] = {
            _text(cons): copy.deepcopy(dict(item))
            for cons, item in dict(legacy_audit or {}).items()
            if _text(cons) and isinstance(item, Mapping)
        }
        self._legacy_opening_pending: dict[str, dict[str, Any]] = {}
        for raw_cons, raw_mind in dict(minds or {}).items():
            cons = _text(raw_cons)
            if not cons:
                continue
            reason_codes: list[str] = []
            if not isinstance(raw_mind, Mapping):
                reason_codes.append("mind_not_mapping")
                mind: dict[str, Any] = {}
            else:
                mind = copy.deepcopy(dict(raw_mind))
                if _text(mind.get("schema_version")) != SCHEMA_VERSION:
                    reason_codes.append("unsupported_schema")
                if _text(mind.get("actor_cons")) != cons:
                    reason_codes.append("actor_cons_mismatch")
                profile = (
                    mind.get("stable_profile")
                    if isinstance(mind.get("stable_profile"), Mapping)
                    else {}
                )
                source_refs = _unique_text(profile.get("source_refs", ()) or ())
                if not source_refs:
                    reason_codes.append("missing_source_refs")
            if reason_codes:
                self._legacy_audit[cons] = {
                    "raw": copy.deepcopy(raw_mind),
                    "reason_codes": reason_codes,
                    "recovery": "reseed_from_current_persona_projection",
                }
                continue
            self._minds[cons] = mind

    @classmethod
    def empty(cls) -> "ActorMindState":
        return cls()

    @classmethod
    def from_snapshot(
        cls,
        raw: Any,
        *,
        legacy_audit: Mapping[str, Any] | None = None,
    ) -> "ActorMindState":
        if raw is None:
            return cls({}, legacy_audit=legacy_audit)
        if not isinstance(raw, Mapping):
            raise ValueError("actor_minds snapshot must be a mapping")
        return cls(raw, legacy_audit=legacy_audit)

    @property
    def minds(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._minds)

    @property
    def legacy_audit(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._legacy_audit)

    @property
    def migration_report(self) -> list[dict[str, Any]]:
        return [
            {
                "actor_cons": cons,
                "status": "legacy_unresolved",
                "reason_codes": list(item.get("reason_codes") or []),
                "recovery": _text(item.get("recovery"))
                or "reseed_from_current_persona_projection",
            }
            for cons, item in sorted(self._legacy_audit.items())
        ]

    def get(self, actor_cons: str) -> dict[str, Any] | None:
        mind = self._minds.get(_text(actor_cons))
        return copy.deepcopy(mind) if isinstance(mind, dict) else None

    def ensure(
        self,
        actor_cons: str,
        persona: Mapping[str, Any] | None,
        *,
        persona_core_hash: str = "",
    ) -> dict[str, Any]:
        cons = _text(actor_cons)
        if not cons:
            raise ValueError("ActorMindState.ensure requires actor_cons")
        existing = self._minds.get(cons)
        if isinstance(existing, dict) and existing.get("schema_version") == SCHEMA_VERSION:
            self._apply_pending_opening(cons)
            return copy.deepcopy(self._minds[cons])
        seeded = build_actor_mind(cons, persona, persona_core_hash=persona_core_hash)
        self._minds[cons] = copy.deepcopy(seeded)
        self._apply_pending_opening(cons)
        return copy.deepcopy(self._minds[cons])

    def absorb_legacy_opening_projection(
        self,
        fsm_by_cons: Mapping[str, Mapping[str, Any]] | None,
        rel_by_cons: Mapping[str, Mapping[str, Any]] | None,
    ) -> None:
        """Migrate old opening FSM/Rel snapshots without granting them new authority."""
        fsm_src = dict(fsm_by_cons or {})
        rel_src = dict(rel_by_cons or {})
        for cons in sorted(set(fsm_src) | set(rel_src)):
            key = _text(cons)
            if not key:
                continue
            pending = self._legacy_opening_pending.setdefault(key, {})
            if isinstance(fsm_src.get(cons), Mapping):
                pending["fsm"] = copy.deepcopy(dict(fsm_src[cons]))
            if isinstance(rel_src.get(cons), Mapping):
                pending["rel_state"] = copy.deepcopy(dict(rel_src[cons]))
            self._apply_pending_opening(key)

    def _apply_pending_opening(self, actor_cons: str) -> None:
        cons = _text(actor_cons)
        mind = self._minds.get(cons)
        pending = self._legacy_opening_pending.get(cons)
        if not isinstance(mind, dict) or not isinstance(pending, dict):
            return
        compat = copy.deepcopy(
            mind.get(LEGACY_OPENING_COMPAT_KEY)
            if isinstance(mind.get(LEGACY_OPENING_COMPAT_KEY), Mapping)
            else {}
        )
        if "fsm" not in compat and isinstance(pending.get("fsm"), Mapping):
            compat["fsm"] = copy.deepcopy(dict(pending["fsm"]))
        if "rel_state" not in compat and isinstance(pending.get("rel_state"), Mapping):
            compat["rel_state"] = copy.deepcopy(dict(pending["rel_state"]))
        if compat:
            compat.setdefault("source_kind", "legacy_opening_compat")
            mind[LEGACY_OPENING_COMPAT_KEY] = compat
            self._minds[cons] = mind
        self._legacy_opening_pending.pop(cons, None)

    def ensure_opening_compat(
        self,
        actor_cons: str,
        *,
        fsm_seed: Mapping[str, Any],
        rel_seed: Mapping[str, Any],
    ) -> None:
        cons = _text(actor_cons)
        mind = self._minds.get(cons)
        if not isinstance(mind, dict):
            raise ValueError("opening compatibility requires an existing ActorMind")
        self._apply_pending_opening(cons)
        mind = self._minds[cons]
        compat = copy.deepcopy(
            mind.get(LEGACY_OPENING_COMPAT_KEY)
            if isinstance(mind.get(LEGACY_OPENING_COMPAT_KEY), Mapping)
            else {}
        )
        compat.setdefault("fsm", copy.deepcopy(dict(fsm_seed)))
        compat.setdefault("rel_state", copy.deepcopy(dict(rel_seed)))
        compat.setdefault("source_kind", "legacy_opening_compat")
        mind[LEGACY_OPENING_COMPAT_KEY] = compat
        self._minds[cons] = mind

    def opening_fsm_map(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cons, mind in self._minds.items():
            compat = mind.get(LEGACY_OPENING_COMPAT_KEY)
            if isinstance(compat, Mapping) and isinstance(compat.get("fsm"), Mapping):
                out[cons] = copy.deepcopy(dict(compat["fsm"]))
        for cons, pending in self._legacy_opening_pending.items():
            if cons not in out and isinstance(pending.get("fsm"), Mapping):
                out[cons] = copy.deepcopy(dict(pending["fsm"]))
        return out

    def opening_rel_map(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cons, mind in self._minds.items():
            compat = mind.get(LEGACY_OPENING_COMPAT_KEY)
            if isinstance(compat, Mapping) and isinstance(compat.get("rel_state"), Mapping):
                out[cons] = copy.deepcopy(dict(compat["rel_state"]))
        for cons, pending in self._legacy_opening_pending.items():
            if cons not in out and isinstance(pending.get("rel_state"), Mapping):
                out[cons] = copy.deepcopy(dict(pending["rel_state"]))
        return out

    def apply_opening_player_signal(
        self,
        actor_cons: str,
        *,
        player_speech: str = "",
        player_action: str = "",
        hostile_hint: bool = False,
    ) -> bool:
        """Preserve the old opening heuristics inside ActorMind as legacy compat.

        These numeric rules remain engineering compatibility, not canon/persona facts.
        """
        cons = _text(actor_cons)
        mind = self._minds.get(cons)
        if not isinstance(mind, dict):
            return False
        compat = copy.deepcopy(
            mind.get(LEGACY_OPENING_COMPAT_KEY)
            if isinstance(mind.get(LEGACY_OPENING_COMPAT_KEY), Mapping)
            else {}
        )
        fsm_row = copy.deepcopy(compat.get("fsm") if isinstance(compat.get("fsm"), Mapping) else {})
        rel_row = copy.deepcopy(
            compat.get("rel_state") if isinstance(compat.get("rel_state"), Mapping) else {}
        )
        if not fsm_row and not rel_row:
            return False

        text = f"{player_speech} {player_action}"
        if fsm_row:
            fsm = NpcFSM(
                trust=int(fsm_row.get("trust", 50) or 50),
                intimacy=int(fsm_row.get("intimacy", 25) or 25),
                alert=int(fsm_row.get("alert", 25) or 25),
                state=_text(fsm_row.get("state")) or "open",
            )
            fsm.violations = int(fsm_row.get("violations") or 0)
            d_trust = d_int = d_alert = 0
            violation = False
            if hostile_hint or any(tok in text for tok in ("滚开", "去死", "骗子", "报警", "骗子")):
                d_trust, d_alert, violation = -8, 12, True
            elif any(tok in text for tok in ("谢谢", "拜托", "相信", "朋友", "挂坠", "接过")):
                d_trust, d_int, d_alert = 3, 2, -2
            elif text.strip():
                d_trust, d_int = 1, 1
            fsm.apply(
                d_trust=d_trust,
                d_int=d_int,
                d_alert=d_alert,
                violation=violation,
            )
            compat["fsm"] = fsm.as_dict()

        if rel_row:
            tp = copy.deepcopy(
                rel_row.get("to_player")
                if isinstance(rel_row.get("to_player"), Mapping)
                else {}
            )
            closeness = float(tp.get("closeness") or 0.2)
            wariness = float(tp.get("wariness") or 0.3)
            if any(tok in text for tok in ("谢谢", "帮忙", "一起", "朋友", "挂坠")):
                closeness = min(1.0, closeness + 0.03)
                wariness = max(0.0, wariness - 0.02)
            elif any(tok in text for tok in ("滚", "骗子", "别碰", "走开")):
                closeness = max(0.0, closeness - 0.05)
                wariness = min(1.0, wariness + 0.08)
            tp["closeness"] = round(closeness, 3)
            tp["wariness"] = round(wariness, 3)
            rel_row["to_player"] = tp
            compat["rel_state"] = rel_row

        compat["source_kind"] = "legacy_opening_compat"
        mind[LEGACY_OPENING_COMPAT_KEY] = compat
        self._minds[cons] = mind
        return True

    def apply_scene_receipt(
        self,
        actor_cons: str,
        receipt: Mapping[str, Any] | None,
        persona: Mapping[str, Any] | None,
        *,
        expected_scope: Mapping[str, Any] | Any | None = None,
    ) -> bool:
        """Apply scene lifecycle receipt and source-bound scene goal projection.

        Existing commitments survive scene changes.  New commitments may only
        come from the target persona's already-authored scene working memory.
        """
        cons = _text(actor_cons)
        if not self.apply_receipt(cons, receipt, expected_scope=expected_scope):
            return False
        current = self._minds.get(cons)
        if not isinstance(current, dict):
            return False
        source = dict(persona or {})
        inner = source.get("inner_state") if isinstance(source.get("inner_state"), Mapping) else {}
        working = (
            source.get("scene_working_memory")
            if isinstance(source.get("scene_working_memory"), Mapping)
            else {}
        )
        goals = _unique_text(working.get("goals", ()) or ())
        fallback_goal = _text(inner.get("want_now"))
        authored_commitments = _unique_text(working.get("commitments", ()) or ())
        motivation = (
            current.get("motivational_state")
            if isinstance(current.get("motivational_state"), Mapping)
            else {}
        )
        current["motivational_state"] = {
            "active_goals": goals or ([fallback_goal] if fallback_goal else []),
            "conflicting_motives": _unique_text(
                motivation.get("conflicting_motives", ()) or ()
            ),
            "commitments": _unique_text(
                [
                    *(motivation.get("commitments", ()) or ()),
                    *authored_commitments,
                ]
            ),
            "last_choice": _text(motivation.get("last_choice")),
        }
        self._minds[cons] = copy.deepcopy(current)
        return True

    def apply_receipt(
        self,
        actor_cons: str,
        receipt: Mapping[str, Any] | None,
        *,
        relationship_effects: Sequence[Mapping[str, Any]] | None = None,
        expected_scope: Mapping[str, Any] | Any | None = None,
    ) -> bool:
        cons = _text(actor_cons)
        current = self._minds.get(cons)
        if not isinstance(current, dict):
            return False
        updated, changed = apply_event_receipt(
            current,
            receipt,
            actor_cons=cons,
            relationship_effects=relationship_effects,
            expected_scope=expected_scope,
        )
        if changed:
            self._minds[cons] = copy.deepcopy(updated)
        return changed

    def reset(self) -> None:
        self._minds = {}
        self._legacy_opening_pending = {}


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
