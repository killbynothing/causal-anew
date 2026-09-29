"""P2c Beat authority: one reducer, append-only completion receipts, legacy projections."""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import ReceiptConflict, canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"
BEAT_RECEIPT_SCHEMA = "free_stage.beat_receipt.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def empty_state(scene_id: str) -> dict[str, Any]:
    return {
        "schema_version": BEAT_STATE_SCHEMA,
        "scene_id": _text(scene_id),
        "scene_epoch": 1,
        "current_completed": [],
        "completed_by_card": {},
        "receipts": [],
    }


def _validate(state: Mapping[str, Any]) -> None:
    if state.get("schema_version") != BEAT_STATE_SCHEMA:
        raise ValueError("unsupported beat state schema")
    if int(state.get("scene_epoch", 0) or 0) < 1:
        raise ValueError("beat scene_epoch must be >= 1")
    if not isinstance(state.get("current_completed"), list):
        raise ValueError("beat current_completed must be a list")
    if not isinstance(state.get("completed_by_card"), dict):
        raise ValueError("beat completed_by_card must be an object")
    if not isinstance(state.get("receipts"), list):
        raise ValueError("beat receipts must be a list")


def normalize_state(raw: Mapping[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(dict(raw))
    _validate(state)
    state["scene_id"] = _text(state.get("scene_id"))
    state["scene_epoch"] = int(state.get("scene_epoch", 1) or 1)
    state["current_completed"] = list(dict.fromkeys(
        _text(item) for item in state.get("current_completed", []) if _text(item)
    ))
    state["completed_by_card"] = {
        _text(scene): list(dict.fromkeys(_text(item) for item in beats if _text(item)))
        for scene, beats in dict(state.get("completed_by_card", {})).items()
        if _text(scene) and isinstance(beats, list)
    }
    state["receipts"] = [
        copy.deepcopy(row) for row in state.get("receipts", []) if isinstance(row, dict)
    ]
    return state


def migrate_legacy(
    *,
    scene_id: str,
    completed: Sequence[str],
    completed_by_card: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    state = empty_state(scene_id)
    state["completed_by_card"] = {
        _text(scene): list(dict.fromkeys(_text(item) for item in beats if _text(item)))
        for scene, beats in completed_by_card.items()
        if _text(scene)
    }
    state["current_completed"] = list(dict.fromkeys(
        _text(item) for item in completed if _text(item)
    ))
    for beat_id in state["current_completed"]:
        state["receipts"].append({
            "schema_version": BEAT_RECEIPT_SCHEMA,
            "receipt_id": "beat:legacy:" + canonical_payload_hash({
                "scene_id": _text(scene_id), "beat_id": beat_id, "epoch": 1
            }),
            "scene_id": _text(scene_id),
            "scene_epoch": 1,
            "beat_id": beat_id,
            "turn": 0,
            "source_kind": "legacy_load",
            "evidence_refs": [],
        })
    return state


def checkpoint_current(state: Mapping[str, Any]) -> dict[str, Any]:
    out = normalize_state(state)
    scene_id = _text(out.get("scene_id"))
    if scene_id:
        out["completed_by_card"][scene_id] = list(out["current_completed"])
    return out


def switch_scene(
    state: Mapping[str, Any],
    target_scene_id: str,
    *,
    restore_completed: Sequence[str] | None = None,
) -> dict[str, Any]:
    out = checkpoint_current(state)
    target = _text(target_scene_id)
    if not target:
        raise ValueError("beat switch requires target_scene_id")
    out["scene_id"] = target
    out["scene_epoch"] = int(out.get("scene_epoch", 1) or 1) + 1
    out["current_completed"] = list(dict.fromkeys(
        _text(item) for item in (restore_completed or ()) if _text(item)
    ))
    out["completed_by_card"][target] = list(out["current_completed"])
    return out


def reset(state: Mapping[str, Any], scene_id: str) -> dict[str, Any]:
    out = empty_state(scene_id)
    out["scene_epoch"] = int(dict(state).get("scene_epoch", 0) or 0) + 1
    return out


def complete(
    state: Mapping[str, Any],
    beat_id: str,
    *,
    turn: int,
    source_kind: str,
    evidence_refs: Sequence[str] = (),
) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    out = normalize_state(state)
    beat = _text(beat_id)
    if not beat:
        raise ValueError("beat_id is required")
    if beat in out["current_completed"]:
        prior = next(
            (
                row for row in out["receipts"]
                if row.get("beat_id") == beat
                and row.get("scene_id") == out["scene_id"]
                and int(row.get("scene_epoch", 0) or 0) == out["scene_epoch"]
            ),
            {},
        )
        return out, False, copy.deepcopy(prior)

    receipt_id = "beat:" + canonical_payload_hash({
        "scene_id": out["scene_id"],
        "scene_epoch": out["scene_epoch"],
        "beat_id": beat,
    })
    candidate = {
        "schema_version": BEAT_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "scene_id": out["scene_id"],
        "scene_epoch": out["scene_epoch"],
        "beat_id": beat,
        "turn": int(turn),
        "source_kind": _text(source_kind) or "unknown",
        "evidence_refs": [_text(item) for item in evidence_refs if _text(item)],
    }
    for prior in out["receipts"]:
        if prior.get("receipt_id") != receipt_id:
            continue
        if canonical_payload_hash(prior) != canonical_payload_hash(candidate):
            raise ReceiptConflict(f"beat receipt id reused with different evidence: {receipt_id}")
        if beat not in out["current_completed"]:
            out["current_completed"].append(beat)
        out["completed_by_card"][out["scene_id"]] = list(out["current_completed"])
        return out, False, copy.deepcopy(prior)

    out["receipts"].append(candidate)
    out["current_completed"].append(beat)
    out["completed_by_card"][out["scene_id"]] = list(out["current_completed"])
    return out, True, copy.deepcopy(candidate)


def complete_many(
    state: Mapping[str, Any],
    beat_ids: Sequence[str],
    *,
    turn: int,
    source_kind: str,
    evidence_refs: Sequence[str] = (),
) -> tuple[dict[str, Any], list[str]]:
    out = normalize_state(state)
    committed: list[str] = []
    for beat_id in beat_ids:
        out, added, _receipt = complete(
            out,
            beat_id,
            turn=turn,
            source_kind=source_kind,
            evidence_refs=evidence_refs,
        )
        if added:
            committed.append(_text(beat_id))
    return out, committed


def projections(state: Mapping[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    out = checkpoint_current(state)
    return (
        list(out["current_completed"]),
        {scene: list(beats) for scene, beats in out["completed_by_card"].items()},
    )
