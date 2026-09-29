"""P2c BeatReducer core.

The reducer owns scene beat completion semantics. Legacy completed and
completed_by_card remain storage/projection fields during migration, but
production code must submit all changes through this reducer.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

BEAT_RECEIPT_SCHEMA = "free_stage.beat_transition.v1"
VALID_OPERATIONS = {
    "complete",
    "replace_complete",
    "snapshot",
    "enter_empty",
    "restore",
    "reset_all",
}


def _clean_ids(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        value = str(raw or "").strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _clean_by_scene(value: Mapping[str, Any] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, raw in dict(value or {}).items():
        scene_id = str(key or "").strip()
        if not scene_id or not isinstance(raw, (list, tuple)):
            continue
        out[scene_id] = _clean_ids(raw)
    return out


def _receipt_id(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "beat:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class BeatReduceResult:
    completed: tuple[str, ...]
    completed_by_card: dict[str, list[str]]
    added: tuple[str, ...] = ()
    receipt: dict[str, Any] | None = None


def reduce_beat_state(
    *,
    completed: Sequence[Any] | None,
    completed_by_card: Mapping[str, Any] | None,
    scene_id: str,
    operation: str,
    beat_ids: Sequence[Any] = (),
    turn_no: int = 0,
    source_kind: str,
    evidence_refs: Sequence[Any] = (),
) -> BeatReduceResult:
    """Reduce one beat-state operation without mutating caller-owned containers.

    restore is migration/return semantics and never creates fresh evidence.
    replace_complete preserves legacy brief-skip exact replacement while
    still emitting receipts for beats newly completed by that explicit action.
    """
    op = str(operation or "").strip()
    if op not in VALID_OPERATIONS:
        raise ValueError(f"unsupported beat operation: {op}")
    scene = str(scene_id or "").strip()
    if op != "reset_all" and not scene:
        raise ValueError("beat operation requires scene_id")
    source = str(source_kind or "").strip()
    if not source:
        raise ValueError("beat operation requires source_kind")
    turn = int(turn_no)
    if turn < 0:
        raise ValueError("beat turn must be >= 0")

    before = _clean_ids(completed)
    current = list(before)
    by_scene = _clean_by_scene(completed_by_card)
    requested = _clean_ids(beat_ids)
    added: list[str] = []

    if op == "complete":
        seen = set(current)
        for beat in requested:
            if beat not in seen:
                current.append(beat)
                seen.add(beat)
                added.append(beat)
    elif op == "replace_complete":
        before_set = set(before)
        current = list(requested)
        added = [beat for beat in current if beat not in before_set]
    elif op == "snapshot":
        by_scene[scene] = list(current)
    elif op == "enter_empty":
        current = []
    elif op == "restore":
        current = list(requested)
    elif op == "reset_all":
        current = []
        by_scene = {}

    receipt = None
    if added:
        payload = {
            "schema_version": BEAT_RECEIPT_SCHEMA,
            "scene_id": scene,
            "turn": turn,
            "operation": op,
            "added": list(added),
            "completed_after": list(current),
            "source_kind": source,
            "evidence_refs": [
                str(item).strip()
                for item in evidence_refs
                if str(item).strip()
            ],
        }
        payload["receipt_id"] = _receipt_id(payload)
        receipt = payload

    return BeatReduceResult(
        completed=tuple(current),
        completed_by_card={key: list(value) for key, value in by_scene.items()},
        added=tuple(added),
        receipt=receipt,
    )
