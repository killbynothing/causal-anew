"""P2c-1 authoritative BeatState reducer."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from runtime import beat_evidence
from runtime.causal_protocol import ReceiptEnvelope, RuntimeScope, canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"


class BeatStateError(ValueError):
    pass


@dataclass(frozen=True)
class BeatCommitResult:
    state: dict[str, Any]
    newly_completed: tuple[str, ...]
    receipts: tuple[dict[str, Any], ...]


def make_instance_id(scene_id: str, ordinal: int) -> str:
    scene = str(scene_id or "").strip()
    if not scene or int(ordinal) < 1:
        raise BeatStateError("invalid beat scene instance")
    return f"{scene}:visit:{int(ordinal)}"


def new_state(scene_id: str, instance_id: str | None = None) -> dict[str, Any]:
    scene = str(scene_id or "").strip()
    iid = str(instance_id or make_instance_id(scene, 1))
    return {
        "schema_version": BEAT_STATE_SCHEMA,
        "current_instance_id": iid,
        "instances": {
            iid: {
                "scene_id": scene,
                "completed": [],
                "receipts": [],
                "legacy_source": None,
            }
        },
        "latest_instance_by_scene": {scene: iid},
    }


def validate(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") != BEAT_STATE_SCHEMA:
        raise BeatStateError("unsupported beat state schema")
    current = str(raw.get("current_instance_id") or "")
    instances = raw.get("instances")
    latest = raw.get("latest_instance_by_scene")
    if not current or not isinstance(instances, Mapping) or current not in instances:
        raise BeatStateError("invalid current beat instance")
    if not isinstance(latest, Mapping):
        raise BeatStateError("invalid beat scene index")
    out = copy.deepcopy(dict(raw))
    for iid, item in out["instances"].items():
        if not isinstance(item, dict):
            raise BeatStateError(f"invalid beat instance: {iid}")
        if not str(item.get("scene_id") or ""):
            raise BeatStateError(f"missing scene id: {iid}")
        if not isinstance(item.get("completed"), list) or not isinstance(item.get("receipts"), list):
            raise BeatStateError(f"invalid beat instance payload: {iid}")
    return out


def from_snapshot(
    raw: Mapping[str, Any] | None,
    *,
    current_scene_id: str,
    current_instance_id: str,
    legacy_completed: Sequence[str] = (),
    legacy_completed_by_card: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return validate(raw)
    state = new_state(current_scene_id, current_instance_id)
    by_card = dict(legacy_completed_by_card or {})
    for scene_id, beats in by_card.items():
        scene = str(scene_id or "").strip()
        if not scene or scene == current_scene_id:
            continue
        iid = f"{scene}:legacy:1"
        state["instances"][iid] = {
            "scene_id": scene,
            "completed": list(dict.fromkeys(str(x) for x in beats if str(x).strip())),
            "receipts": [],
            "legacy_source": "completed_by_card",
        }
        state["latest_instance_by_scene"][scene] = iid
    merged = list(dict.fromkeys(
        [str(x) for x in by_card.get(current_scene_id, ()) if str(x).strip()]
        + [str(x) for x in legacy_completed if str(x).strip()]
    ))
    current = state["instances"][current_instance_id]
    current["completed"] = merged
    current["legacy_source"] = "completed/completed_by_card" if merged else None
    return state


def current_instance_id(state: Mapping[str, Any]) -> str:
    return str(validate(state)["current_instance_id"])


def current_completed(state: Mapping[str, Any]) -> list[str]:
    checked = validate(state)
    return list(checked["instances"][checked["current_instance_id"]]["completed"])


def completed_by_scene(state: Mapping[str, Any]) -> dict[str, list[str]]:
    checked = validate(state)
    out: dict[str, list[str]] = {}
    for scene_id, iid in checked["latest_instance_by_scene"].items():
        item = checked["instances"].get(str(iid))
        if isinstance(item, dict):
            out[str(scene_id)] = list(item.get("completed") or [])
    return out


def next_instance_id(state: Mapping[str, Any], scene_id: str) -> str:
    checked = validate(state)
    scene = str(scene_id or "").strip()
    count = sum(
        1 for item in checked["instances"].values()
        if isinstance(item, dict) and str(item.get("scene_id") or "") == scene
    )
    return make_instance_id(scene, count + 1)


def begin_scene(state: Mapping[str, Any], scene_id: str, instance_id: str | None = None) -> dict[str, Any]:
    checked = validate(state)
    scene = str(scene_id or "").strip()
    iid = str(instance_id or next_instance_id(checked, scene))
    if iid in checked["instances"]:
        raise BeatStateError(f"beat instance exists: {iid}")
    checked["instances"][iid] = {
        "scene_id": scene,
        "completed": [],
        "receipts": [],
        "legacy_source": None,
    }
    checked["current_instance_id"] = iid
    checked["latest_instance_by_scene"][scene] = iid
    return checked


def restore_instance(state: Mapping[str, Any], instance_id: str) -> dict[str, Any]:
    checked = validate(state)
    iid = str(instance_id or "")
    if iid not in checked["instances"]:
        raise BeatStateError(f"unknown beat instance: {iid}")
    checked["current_instance_id"] = iid
    scene = str(checked["instances"][iid]["scene_id"])
    checked["latest_instance_by_scene"][scene] = iid
    return checked


def commit_beats(
    state: Mapping[str, Any],
    *,
    scope: RuntimeScope,
    card: Mapping[str, Any],
    beat_ids: Sequence[str],
    source_kind: str,
    turn: int,
    source_refs: Sequence[str] = (),
    event_id: str = "",
    allow_unknown: bool = False,
) -> BeatCommitResult:
    checked = validate(state)
    iid = checked["current_instance_id"]
    if iid != scope.scene_instance_id:
        raise BeatStateError(f"beat scope mismatch: {iid} != {scope.scene_instance_id}")
    item = checked["instances"][iid]
    scene_id = str(item["scene_id"])
    if str(card.get("scene_id") or scene_id) != scene_id:
        raise BeatStateError("beat card/instance scene mismatch")
    source = str(source_kind or "").strip()
    if not source:
        raise BeatStateError("beat source_kind required")

    requested = list(dict.fromkeys(str(x) for x in beat_ids if str(x).strip()))
    if not requested:
        return BeatCommitResult(checked, (), ())

    known = {
        str(row.get("id") or "").strip()
        for row in (card.get("must_happen") or [])
        if isinstance(row, Mapping) and str(row.get("id") or "").strip()
    }
    if not allow_unknown:
        unknown = set(requested) - known
        if unknown:
            raise BeatStateError(f"unknown beat ids: {sorted(unknown)}")

    done = set(str(x) for x in item.get("completed") or [])
    gates = beat_evidence.after_map(card)
    batch = set(requested)
    for beat in requested:
        missing = set(gates.get(beat) or ()) - (done | batch)
        if missing:
            raise BeatStateError(f"missing prerequisites for {beat}: {sorted(missing)}")

    newly = [beat for beat in requested if beat not in done]
    receipts: list[dict[str, Any]] = []
    stable_event = str(event_id or f"{source}:turn:{int(turn)}")
    for sequence, beat in enumerate(newly):
        payload = {
            "scene_id": scene_id,
            "scene_instance_id": iid,
            "beat_id": beat,
            "source_kind": source,
            "turn": int(turn),
        }
        envelope = ReceiptEnvelope.for_payload(
            receipt_id=f"beat:{canonical_payload_hash({'scope': scope.to_dict(), 'beat': beat, 'event': stable_event})}",
            request_id=f"beat:{stable_event}",
            turn_id=f"turn:{int(turn)}",
            sequence=sequence,
            scope=scope,
            producer="BeatState",
            source_refs=tuple(str(x) for x in source_refs if str(x).strip()),
            visibility="system",
            base_revision=len(item.get("receipts") or []),
            payload=payload,
        ).to_dict()
        receipts.append({
            "schema_version": "free_stage.beat_receipt.v1",
            "beat_id": beat,
            "scene_id": scene_id,
            "scene_instance_id": iid,
            "source_kind": source,
            "event_id": stable_event,
            "receipt": envelope,
        })

    if newly:
        item["completed"] = list(item.get("completed") or []) + newly
        item["receipts"] = list(item.get("receipts") or []) + receipts
    checked["latest_instance_by_scene"][scene_id] = iid
    return BeatCommitResult(checked, tuple(newly), tuple(copy.deepcopy(receipts)))


def receipts_for_current(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    checked = validate(state)
    return copy.deepcopy(checked["instances"][checked["current_instance_id"]]["receipts"])
