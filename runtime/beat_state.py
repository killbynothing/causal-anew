"""P2c authoritative BeatState and BeatReducer.

BeatState owns satisfaction of must-happen beats. completed and
completed_by_card are compatibility projections only. Evidence records never
invent predecessor actions; legacy data uses an explicit legacy source and
unknown ids remain unresolved.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"


class BeatStateError(ValueError):
    pass


class BeatEvidenceConflict(BeatStateError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: Sequence[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = _text(value)
        if item and item not in out:
            out.append(item)
    return out


def make_scene_instance_id(scene_id: str, visit: int) -> str:
    sid = _text(scene_id)
    if not sid or int(visit) < 1:
        raise BeatStateError("scene instance requires scene_id and visit>=1")
    return f"{sid}:visit:{int(visit)}"


def _new_scene(scene_id: str, instance_id: str, required_ids: Sequence[Any]) -> dict[str, Any]:
    return {
        "scene_id": _text(scene_id),
        "scene_instance_id": _text(instance_id),
        "required_ids": _unique(required_ids),
        "completion_order": [],
        "satisfied": {},
        "evidence": {},
        "legacy_unresolved": [],
    }


def new_state(*, scene_id: str, scene_instance_id: str, required_ids: Sequence[Any]) -> dict[str, Any]:
    scene = _new_scene(scene_id, scene_instance_id, required_ids)
    out = {
        "schema_version": BEAT_STATE_SCHEMA,
        "active_scene_instance_id": scene_instance_id,
        "scene_order": [scene_instance_id],
        "scenes": {scene_instance_id: scene},
    }
    validate_state(out)
    return out


def validate_state(raw: Mapping[str, Any]) -> None:
    if raw.get("schema_version") != BEAT_STATE_SCHEMA:
        raise BeatStateError("unsupported beat state schema")
    active = _text(raw.get("active_scene_instance_id"))
    scenes = raw.get("scenes")
    order = raw.get("scene_order")
    if not active or not isinstance(scenes, Mapping) or active not in scenes:
        raise BeatStateError("beat state requires active scene")
    if not isinstance(order, list) or any(_text(item) not in scenes for item in order):
        raise BeatStateError("invalid beat scene order")
    for instance_id, scene_raw in scenes.items():
        if not isinstance(scene_raw, Mapping):
            raise BeatStateError("beat scene must be an object")
        if _text(scene_raw.get("scene_instance_id")) != _text(instance_id):
            raise BeatStateError("beat scene instance mismatch")
        required = _unique(scene_raw.get("required_ids") or ())
        completion = _unique(scene_raw.get("completion_order") or ())
        satisfied = scene_raw.get("satisfied")
        evidence = scene_raw.get("evidence")
        unresolved = scene_raw.get("legacy_unresolved")
        if not isinstance(satisfied, Mapping) or not isinstance(evidence, Mapping):
            raise BeatStateError("beat scene requires satisfied/evidence maps")
        if not isinstance(unresolved, list):
            raise BeatStateError("legacy_unresolved must be a list")
        if any(beat not in required for beat in completion):
            raise BeatStateError("completed beat is not declared by current scene")
        if set(completion) != {str(x) for x in satisfied.keys()}:
            raise BeatStateError("completion_order and satisfied map differ")
        for beat, row in satisfied.items():
            if not isinstance(row, Mapping) or _text(row.get("beat_id")) != _text(beat):
                raise BeatStateError("invalid satisfied beat row")
            evidence_ids = row.get("evidence_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                raise BeatStateError("satisfied beat requires evidence")
            if any(_text(eid) not in evidence for eid in evidence_ids):
                raise BeatStateError("satisfied beat references missing evidence")


def load_state(raw: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(raw))
    validate_state(out)
    return out


def active_scene(state: Mapping[str, Any]) -> dict[str, Any]:
    validate_state(state)
    instance = _text(state.get("active_scene_instance_id"))
    return copy.deepcopy(dict(state["scenes"][instance]))


def active_completed(state: Mapping[str, Any]) -> list[str]:
    return list(active_scene(state).get("completion_order") or [])


def completed_by_scene(state: Mapping[str, Any]) -> dict[str, list[str]]:
    validate_state(state)
    latest: dict[str, list[str]] = {}
    scenes = state["scenes"]
    for instance_id in state["scene_order"]:
        scene = scenes[instance_id]
        latest[_text(scene.get("scene_id"))] = list(scene.get("completion_order") or [])
    return latest


def evidence_id_for(
    *,
    scene_instance_id: str,
    source_kind: str,
    turn: int,
    beat_ids: Sequence[Any],
    source_refs: Sequence[Any],
) -> str:
    payload = {
        "scene_instance_id": _text(scene_instance_id),
        "source_kind": _text(source_kind),
        "turn": int(turn),
        "beat_ids": _unique(beat_ids),
        "source_refs": _unique(source_refs),
    }
    return f"beat:{canonical_payload_hash(payload)}"


def satisfy_beats(
    state: Mapping[str, Any],
    *,
    beat_ids: Sequence[Any],
    evidence_id: str,
    source_kind: str,
    source_refs: Sequence[Any],
    turn: int,
) -> tuple[dict[str, Any], list[str]]:
    out = load_state(state)
    instance = _text(out["active_scene_instance_id"])
    scene = out["scenes"][instance]
    beats = _unique(beat_ids)
    refs = _unique(source_refs)
    source = _text(source_kind)
    eid = _text(evidence_id)
    if not beats:
        return out, []
    if not source or not eid or not refs:
        raise BeatStateError("beat satisfaction requires evidence id/source/source_refs")
    required = set(scene.get("required_ids") or [])
    unknown = [beat for beat in beats if beat not in required]
    if unknown:
        raise BeatStateError(f"beat ids are not declared by active scene: {unknown}")

    evidence_row = {
        "evidence_id": eid,
        "scene_instance_id": instance,
        "beat_ids": beats,
        "source_kind": source,
        "source_refs": refs,
        "turn": int(turn),
    }
    existing_evidence = scene["evidence"].get(eid)
    if existing_evidence is not None and existing_evidence != evidence_row:
        raise BeatEvidenceConflict(f"beat evidence id reused with different payload: {eid}")
    if existing_evidence is None:
        scene["evidence"][eid] = evidence_row

    newly: list[str] = []
    for beat in beats:
        if beat in scene["satisfied"]:
            continue
        scene["satisfied"][beat] = {
            "beat_id": beat,
            "evidence_ids": [eid],
            "first_turn": int(turn),
            "source_kind": source,
        }
        scene["completion_order"].append(beat)
        newly.append(beat)
    validate_state(out)
    return out, newly


def activate_scene(
    state: Mapping[str, Any],
    *,
    scene_id: str,
    scene_instance_id: str,
    required_ids: Sequence[Any],
    restore_completed: Sequence[Any] = (),
    restore_source_kind: str = "scene_restore",
    restore_source_refs: Sequence[Any] = (),
    turn: int = 0,
) -> dict[str, Any]:
    out = load_state(state)
    instance = _text(scene_instance_id)
    sid = _text(scene_id)
    if instance in out["scenes"]:
        scene = out["scenes"][instance]
        if _text(scene.get("scene_id")) != sid:
            raise BeatStateError("scene instance reused for different scene")
        if _unique(scene.get("required_ids") or ()) != _unique(required_ids):
            raise BeatStateError("scene instance required beat set changed")
    else:
        out["scenes"][instance] = _new_scene(sid, instance, required_ids)
        out["scene_order"].append(instance)
    out["active_scene_instance_id"] = instance

    restored = _unique(restore_completed)
    if restored:
        refs = _unique(restore_source_refs) or [f"restore:{instance}"]
        eid = evidence_id_for(
            scene_instance_id=instance,
            source_kind=restore_source_kind,
            turn=turn,
            beat_ids=restored,
            source_refs=refs,
        )
        out, _ = satisfy_beats(
            out,
            beat_ids=restored,
            evidence_id=eid,
            source_kind=restore_source_kind,
            source_refs=refs,
            turn=turn,
        )
    validate_state(out)
    return out


def migrate_legacy(
    *,
    scene_id: str,
    scene_instance_id: str,
    required_ids: Sequence[Any],
    completed: Sequence[Any],
    completed_by_card: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    state = new_state(
        scene_id=scene_id,
        scene_instance_id=scene_instance_id,
        required_ids=required_ids,
    )
    historical = dict(completed_by_card or {})
    for old_scene_id, old_completed in historical.items():
        sid = _text(old_scene_id)
        if not sid or sid == _text(scene_id):
            continue
        beats = _unique(old_completed or ())
        legacy_instance = f"{sid}:legacy:1"
        state = activate_scene(
            state,
            scene_id=sid,
            scene_instance_id=legacy_instance,
            required_ids=beats,
        )
        if beats:
            eid = evidence_id_for(
                scene_instance_id=legacy_instance,
                source_kind="legacy_session_v1",
                turn=0,
                beat_ids=beats,
                source_refs=(f"legacy:completed_by_card:{sid}",),
            )
            state, _ = satisfy_beats(
                state,
                beat_ids=beats,
                evidence_id=eid,
                source_kind="legacy_session_v1",
                source_refs=(f"legacy:completed_by_card:{sid}",),
                turn=0,
            )

    state["active_scene_instance_id"] = scene_instance_id
    current = state["scenes"][scene_instance_id]
    required = set(current["required_ids"])
    known = [beat for beat in _unique(completed) if beat in required]
    current["legacy_unresolved"] = [beat for beat in _unique(completed) if beat not in required]
    if known:
        eid = evidence_id_for(
            scene_instance_id=scene_instance_id,
            source_kind="legacy_session_v1",
            turn=0,
            beat_ids=known,
            source_refs=("legacy:completed",),
        )
        state, _ = satisfy_beats(
            state,
            beat_ids=known,
            evidence_id=eid,
            source_kind="legacy_session_v1",
            source_refs=("legacy:completed",),
            turn=0,
        )
    validate_state(state)
    return state
