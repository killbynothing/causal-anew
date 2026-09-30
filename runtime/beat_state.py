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
    "flashback_restore",
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


def seed_completed(
    states: MutableMapping[str, dict[str, Any]],
    *,
    scope: RuntimeScope,
    scene_id: str,
    completed: Sequence[str],
    source_kind: str,
    source_ref: str,
) -> list[str]:
    """Explicit adapter seed. Never invents player action or visible evidence."""
    kind = _text(source_kind)
    ref = _text(source_ref)
    if not kind or not ref:
        raise ValueError("beat adapter seed requires source_kind/source_ref")
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
            source_kind=kind,
            evidence_refs=(ref,),
            event_id=(
                "beat:seed:"
                + canonical_payload_hash(
                    {
                        "scope": scope.to_dict(),
                        "beat_id": beat_id,
                        "index": index,
                        "source_kind": kind,
                        "source_ref": ref,
                    }
                )
            ),
        )
    return completed_for_scope(states, scope)


def migrate_legacy_completed(
    states: MutableMapping[str, dict[str, Any]],
    *,
    scope: RuntimeScope,
    scene_id: str,
    completed: Sequence[str],
    source_ref: str,
) -> list[str]:
    return seed_completed(
        states,
        scope=scope,
        scene_id=scene_id,
        completed=completed,
        source_kind="legacy_snapshot",
        source_ref=source_ref,
    )


def _scope_visit_rank(scope_raw: Mapping[str, Any] | None) -> tuple[int, str]:
    raw = dict(scope_raw or {})
    instance = _text(raw.get("scene_instance_id"))
    if ":visit:" in instance:
        tail = instance.rsplit(":visit:", 1)[-1]
        try:
            return (2, f"{int(tail):012d}")
        except ValueError:
            return (2, tail)
    if ":legacy:" in instance:
        return (0, instance)
    return (1, instance)


def project_completed_by_scene(
    states: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Latest scene instance wins; legacy synthetic scopes rank below real visits."""
    chosen: dict[str, tuple[tuple[int, str], list[str]]] = {}
    for state in states.values():
        if not isinstance(state, Mapping):
            continue
        scene_id = _text(state.get("scene_id"))
        if not scene_id:
            continue
        completed = [
            str(x) for x in (state.get("completed_order") or [])
            if str(x).strip()
        ]
        rank = _scope_visit_rank(state.get("scope") if isinstance(state.get("scope"), Mapping) else {})
        previous = chosen.get(scene_id)
        if previous is None or rank >= previous[0]:
            chosen[scene_id] = (rank, completed)
    return {scene_id: list(value[1]) for scene_id, value in chosen.items()}


def migrate_legacy_completed_by_card(
    states: MutableMapping[str, dict[str, Any]],
    *,
    worldline: str,
    run: int,
    session_id: str,
    completed_by_card: Mapping[str, Sequence[str]],
) -> None:
    """Preserve historical per-scene progress from pre-BeatState snapshots."""
    for scene_id, completed in completed_by_card.items():
        sid = _text(scene_id)
        if not sid:
            continue
        scope = RuntimeScope(
            worldline=_text(worldline) or "WMAIN",
            run=int(run),
            ch_anchor=0,
            session_id=_text(session_id),
            scene_instance_id=(
                f"{sid}:legacy:"
                + canonical_payload_hash(
                    {"session_id": session_id, "scene_id": sid}
                )[:12]
            ),
        )
        seed_completed(
            states,
            scope=scope,
            scene_id=sid,
            completed=completed,
            source_kind="legacy_completed_by_card",
            source_ref=f"legacy-completed-by-card:{sid}",
        )
