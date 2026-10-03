# -*- coding: utf-8 -*-
"""P4 actor-owned participation intent and content-blind floor arbitration.

The actor deliberates from its own Mind + currently observable public signal.
Floor arbitration consumes only metadata needed to allocate conversational
opportunity. It never receives goal text, must-happen ids, director instructions,
or private player thought.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

INTENT_SCHEMA = "free_stage.participation_intent.v1"
GRANT_SCHEMA = "free_stage.floor_grant.v1"
PARTICIPATION_MODES = frozenset({"speak", "backchannel", "side", "action", "pass"})
FLOOR_MODES = frozenset({"speak"})
COMPANION_MODES = frozenset({"backchannel", "side"})
ACTION_MODES = frozenset({"action"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _public_signal(raw: Mapping[str, Any] | None) -> dict[str, str]:
    source = dict(raw or {})
    out: dict[str, str] = {}
    for key in ("speech", "action"):
        value = _text(source.get(key))
        if value:
            out[key] = value
    return out


def _mind_counts(mind: Mapping[str, Any] | None) -> tuple[int, int, str]:
    state = dict(mind or {})
    motivation = (
        state.get("motivational_state")
        if isinstance(state.get("motivational_state"), Mapping)
        else {}
    )
    appraisal = (
        state.get("appraisal_state")
        if isinstance(state.get("appraisal_state"), Mapping)
        else {}
    )
    goals = [
        _text(item) for item in (motivation.get("active_goals") or ())
        if _text(item)
    ]
    commitments = [
        _text(item) for item in (motivation.get("commitments") or ())
        if _text(item)
    ]
    return len(goals), len(commitments), _text(appraisal.get("last_event_kind"))


def _style(value: str) -> str:
    raw = _text(value) or "mixed"
    if raw in {"speak", "speak_preferred"}:
        return "speak"
    if raw == "backchannel_preferred":
        return "backchannel_preferred"
    return "mixed"


@dataclass(frozen=True)
class ParticipationIntent:
    actor_cons: str
    mode: str
    urgency: float
    lane: str
    addressee: str = ""
    public_obligation: bool = False
    obligation_kind: str = ""
    obligation_evidence: str = ""
    reason_codes: tuple[str, ...] = ()
    llm_calls: int = 0

    def __post_init__(self) -> None:
        if not _text(self.actor_cons):
            raise ValueError("participation intent requires actor_cons")
        if self.mode not in PARTICIPATION_MODES:
            raise ValueError(f"unsupported participation mode: {self.mode}")
        if self.lane not in {"floor", "companion", "stage", "none"}:
            raise ValueError(f"unsupported participation lane: {self.lane}")
        if not 0.0 <= float(self.urgency) <= 1.0:
            raise ValueError("participation urgency must be within [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": INTENT_SCHEMA,
            "actor_cons": self.actor_cons,
            "mode": self.mode,
            "urgency": round(float(self.urgency), 3),
            "lane": self.lane,
            "addressee": self.addressee,
            "public_obligation": bool(self.public_obligation),
            "obligation_kind": self.obligation_kind,
            "obligation_evidence": self.obligation_evidence,
            "reason_codes": list(self.reason_codes),
            "llm_calls": int(self.llm_calls),
        }


@dataclass(frozen=True)
class FloorGrant:
    actor_cons: str
    mode: str
    lane: str
    order: int
    response_slot: str
    urgency: float
    public_obligation: bool = False
    obligation_kind: str = ""
    addressee: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GRANT_SCHEMA,
            "actor_cons": self.actor_cons,
            "mode": self.mode,
            "lane": self.lane,
            "order": int(self.order),
            "response_slot": self.response_slot,
            "urgency": round(float(self.urgency), 3),
            "public_obligation": bool(self.public_obligation),
            "obligation_kind": self.obligation_kind,
            "addressee": self.addressee,
        }


def deliberate_participation(
    actor_cons: str,
    mind: Mapping[str, Any] | None,
    visible_input: Mapping[str, Any] | None,
    *,
    participation_style: str = "mixed",
    conversation_obligation: Mapping[str, Any] | None = None,
    recent_public_actor: str = "",
) -> ParticipationIntent:
    """Build one zero-LLM actor intent without exposing private content to Floor."""
    cons = _text(actor_cons)
    if not cons:
        raise ValueError("actor deliberation requires actor_cons")

    public = _public_signal(visible_input)
    has_public = bool(public)
    obligation = dict(conversation_obligation or {})
    obligation_target = _text(obligation.get("target_cons"))
    owns_obligation = bool(
        obligation_target
        and obligation_target == cons
        and _text(obligation.get("kind")) not in {"", "unowned"}
    )
    goals_n, commitments_n, last_event_kind = _mind_counts(mind)
    style = _style(participation_style)
    reasons: list[str] = []

    if owns_obligation:
        # An adjacency obligation creates response eligibility, not an answer.
        mode = "speak"
        urgency = 1.0
        lane = "floor"
        reasons.append("public_obligation")
    elif has_public:
        if style == "backchannel_preferred":
            mode = "backchannel"
            urgency = 0.38
            lane = "companion"
            reasons.append("public_signal_backchannel")
        elif style == "mixed" and commitments_n == 0:
            mode = "backchannel"
            urgency = 0.44
            lane = "companion"
            reasons.append("public_signal_mixed")
        else:
            mode = "speak"
            urgency = 0.58
            lane = "floor"
            reasons.append("public_signal")
    elif commitments_n > 0:
        # Existing persistent commitments may make an actor volunteer on an idle
        # beat, but Floor receives only urgency, never commitment text.
        mode = "speak"
        urgency = 0.34
        lane = "floor"
        reasons.append("persistent_commitment")
    elif recent_public_actor and recent_public_actor != cons and style == "mixed":
        mode = "side"
        urgency = 0.24
        lane = "companion"
        reasons.append("companion_continuation")
    else:
        mode = "pass"
        urgency = 0.0
        lane = "none"
        reasons.append("no_actor_owned_reason")

    if mode == "speak" and goals_n > 0 and not owns_obligation:
        urgency = min(1.0, urgency + 0.06)
        reasons.append("active_goal_present")
    if mode == "speak" and commitments_n > 0 and not owns_obligation:
        urgency = min(1.0, urgency + 0.08)
    if last_event_kind == "actor_public_enactment" and mode == "speak" and not owns_obligation:
        urgency = max(0.0, urgency - 0.08)
        reasons.append("heard_actor_enactment")

    return ParticipationIntent(
        actor_cons=cons,
        mode=mode,
        urgency=round(urgency, 3),
        lane=lane,
        addressee="player" if has_public or owns_obligation else "",
        public_obligation=owns_obligation,
        obligation_kind=_text(obligation.get("kind")) if owns_obligation else "",
        obligation_evidence=_text(obligation.get("evidence")) if owns_obligation else "",
        reason_codes=tuple(reasons),
        llm_calls=0,
    )


def floor_view(intent: ParticipationIntent | Mapping[str, Any]) -> dict[str, Any]:
    """Content-blind projection consumed by Floor."""
    row = intent.to_dict() if isinstance(intent, ParticipationIntent) else dict(intent)
    return {
        "actor_cons": _text(row.get("actor_cons")),
        "mode": _text(row.get("mode")),
        "urgency": float(row.get("urgency") or 0.0),
        "lane": _text(row.get("lane")),
        "addressee": _text(row.get("addressee")),
        "public_obligation": bool(row.get("public_obligation", False)),
        "obligation_kind": _text(row.get("obligation_kind")),
    }


def arbitrate_floor(
    intents: Sequence[ParticipationIntent | Mapping[str, Any]],
    *,
    recent_occupancy: Mapping[str, int] | None = None,
    max_floor: int = 1,
    max_companion: int = 2,
    max_stage: int = 1,
) -> list[FloorGrant]:
    """Allocate opportunities using metadata only.

    Ranking uses public obligation, actor-declared urgency and fairness. No goal
    text, MH ids, prompt snippets or private thought are accepted by this API.
    """
    occupancy = {
        _text(cons): max(0, int(count or 0))
        for cons, count in dict(recent_occupancy or {}).items()
        if _text(cons)
    }
    rows = [floor_view(item) for item in intents]
    rows = [row for row in rows if row["actor_cons"] and row["mode"] != "pass"]

    def fairness_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        penalty = min(0.12 * occupancy.get(_text(row.get("actor_cons")), 0), 0.48)
        effective = float(row.get("urgency") or 0.0) - penalty
        return (
            -int(bool(row.get("public_obligation"))),
            -round(effective, 3),
            occupancy.get(_text(row.get("actor_cons")), 0),
            _text(row.get("actor_cons")),
        )

    floor_rows = sorted(
        [row for row in rows if row.get("mode") in FLOOR_MODES and row.get("lane") == "floor"],
        key=fairness_key,
    )[: max(0, int(max_floor))]
    companion_rows = sorted(
        [row for row in rows if row.get("mode") in COMPANION_MODES and row.get("lane") == "companion"],
        key=fairness_key,
    )[: max(0, int(max_companion))]
    stage_rows = sorted(
        [row for row in rows if row.get("mode") in ACTION_MODES and row.get("lane") == "stage"],
        key=fairness_key,
    )[: max(0, int(max_stage))]

    grants: list[FloorGrant] = []
    for index, row in enumerate(floor_rows):
        grants.append(
            FloorGrant(
                actor_cons=row["actor_cons"],
                mode="speak",
                lane="floor",
                order=index,
                response_slot="primary" if index == 0 else "secondary",
                urgency=float(row["urgency"]),
                public_obligation=bool(row["public_obligation"]),
                obligation_kind=_text(row.get("obligation_kind")),
                addressee=_text(row.get("addressee")),
            )
        )
    for index, row in enumerate(companion_rows):
        grants.append(
            FloorGrant(
                actor_cons=row["actor_cons"],
                mode=row["mode"],
                lane="companion",
                order=len(floor_rows) + index,
                response_slot=row["mode"],
                urgency=float(row["urgency"]),
                public_obligation=bool(row["public_obligation"]),
                obligation_kind=_text(row.get("obligation_kind")),
                addressee=_text(row.get("addressee")),
            )
        )
    for index, row in enumerate(stage_rows):
        grants.append(
            FloorGrant(
                actor_cons=row["actor_cons"],
                mode="action",
                lane="stage",
                order=len(floor_rows) + len(companion_rows) + index,
                response_slot="stage_only",
                urgency=float(row["urgency"]),
                public_obligation=bool(row["public_obligation"]),
                obligation_kind=_text(row.get("obligation_kind")),
                addressee=_text(row.get("addressee")),
            )
        )
    return grants


def grant_map(grants: Sequence[FloorGrant | Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in grants:
        row = item.to_dict() if isinstance(item, FloorGrant) else dict(item)
        cons = _text(row.get("actor_cons"))
        if cons:
            out[cons] = row
    return out
