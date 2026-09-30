"""P2c BeatState authority.

BeatState owns completion events. FreeStageSession.completed remains a
compatibility projection while scene lifecycle/load adapters are migrated.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from runtime.causal_protocol import RuntimeScope, canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"
BEAT_EVENT_SCHEMA = "free_stage.beat_event.v1"

P2C_BEAT_ADAPTER_DEBT = (
    "legacy_load",
    "reset",
    "scene_enter",
    "flashback_restore",
    "completed_by_card_projection",
)


class BeatConflict(ValueError):
    pass


@dataclass(frozen=True)
class BeatCommitResult:
    event: dict[str, Any]
    committed: bool


def _text(value: Any) -> str:
    return str(value or "").strip()


def scene_key(scope: RuntimeScope) -> str:
    return scope.scene_instance_id


def _new_scene_state(scope: RuntimeScope, scene_id: str) -> dict[str, Any]:
    return {
        "schema_version": BEAT_STATE_SCHEMA,
        "scope": scope.to_dict(),
        "scene_id": _text(scene_id),
        "events": {},
        "completed_order": [],
    }


def normalize_states(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, value in dict(raw or {}).items():
        if not isinstance(value, Mapping):
            continue
        state = copy.deepcopy(dict(value))
        if state.get("schema_version") != BEAT_STATE_SCHEMA:
            continue
        if not isinstance(state.get("events"), dict):
            continue
        if not isinstance(state.get("completed_order"), list):
            continue
        out[str(key)] = state
    return out


def make_event_id(
    scope: RuntimeScope,
    *,
    beat_id: str,
    turn: int,
    source_kind: str,
    evidence_refs: Sequence[str],
) -> str:
    digest = canonical_payload_hash(
        {
            "scope": scope.to_dict(),
            "beat_id": _text(beat_id),
            "turn": int(turn),
            "source_kind": _text(source_kind),
            "evidence_refs": [str(x) for x in evidence_refs],
        }
    )
    return f"beat:{digest}"


def commit_beat(
    states: MutableMapping[str, dict[str, Any]],
    *,
    scope: RuntimeScope,
    scene_id: str,
    beat_id: str,
    turn: int,
    source_kind: str,
    evidence_refs: Sequence[str],
    event_id: str = "",
) -> BeatCommitResult:
    beat = _text(beat_id)
    kind = _text(source_kind)
    refs = tuple(_text(x) for x in evidence_refs if _text(x))
    if scope.run < 1:
        raise ValueError("beat commit requires run>=1")
    if not beat or not kind:
        raise ValueError("beat commit requires beat_id/source_kind")
    if int(turn) < 0:
        raise ValueError("beat commit turn must be >=0")
    if not refs:
        raise ValueError("beat commit requires evidence/source refs")

    key = scene_key(scope)
    state = states.get(key)
    if state is None:
        state = _new_scene_state(scope, scene_id)
        states[key] = state
    elif state.get("schema_version") != BEAT_STATE_SCHEMA:
        raise BeatConflict(f"invalid beat state schema for {key}")
    elif dict(state.get("scope") or {}) != scope.to_dict():
        raise BeatConflict(f"beat state scope mismatch for {key}")

    eid = _text(event_id) or make_event_id(
        scope,
        beat_id=beat,
        turn=int(turn),
        source_kind=kind,
        evidence_refs=refs,
    )
    event = {
        "schema_version": BEAT_EVENT_SCHEMA,
        "event_id": eid,
        "beat_id": beat,
        "turn": int(turn),
        "source_kind": kind,
        "evidence_refs": list(refs),
        "scope": scope.to_dict(),
    }

    events = state.setdefault("events", {})
    existing = events.get(eid)
    if existing is not None:
        if canonical_payload_hash(existing) != canonical_payload_hash(event):
            raise BeatConflict(f"beat event id reused with different payload: {eid}")
        return BeatCommitResult(event=copy.deepcopy(existing), committed=False)

    events[eid] = event
    order = state.setdefault("completed_order", [])
    if beat not in order:
        order.append(beat)
    return BeatCommitResult(event=copy.deepcopy(event), committed=True)


def completed_for_scope(
    states: Mapping[str, Mapping[str, Any]],
    scope: RuntimeScope,
) -> list[str]:
    state = states.get(scene_key(scope))
    if not isinstance(state, Mapping):
        return []
    return [str(x) for x in (state.get("completed_order") or []) if str(x).strip()]


def migrate_legacy_completed(
    states: MutableMapping[str, dict[str, Any]],
    *,
    scope: RuntimeScope,
    scene_id: str,
    completed: Sequence[str],
    source_ref: str,
) -> list[str]:
    """One-way adapter. It never invents a player action or visible evidence."""
    for index, beat in enumerate(completed):
        beat_id = _text(beat)
        if not beat_id:
            continue
        commit_beat(
            states,
            scope=scope,
            scene_id=scene_id,
            beat_id=beat_id,
            turn=0,
            source_kind="legacy_snapshot",
            evidence_refs=(source_ref,),
            event_id=(
                "beat:legacy:"
                + canonical_payload_hash(
                    {
                        "scope": scope.to_dict(),
                        "beat_id": beat_id,
                        "index": index,
                        "source_ref": source_ref,
                    }
                )
            ),
        )
    return completed_for_scope(states, scope)
