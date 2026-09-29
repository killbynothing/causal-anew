"""P2c-3 scene fact authority.

Scene receipts are append-only evidence. branch_progress is a compatibility
projection of currently-active facts/flow markers and may change through
assert/retract/replace operations, but callers never mutate it directly.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCENE_FACT_RECEIPT_SCHEMA = "free_stage.scene_fact_receipt.v1"
VALID_OPERATIONS = {"observe", "assert", "retract", "replace", "reset_all"}


def _clean_ids(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        value = str(raw or "").strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _receipt_operation(row: Mapping[str, Any]) -> str:
    op = str(row.get("operation") or "").strip()
    # Legacy scene_receipts were positive observations with no operation field.
    return op if op in {"observe", "assert", "retract"} else "observe"


def active_fact_ids(
    branch_progress: Sequence[Any] | None,
    scene_receipts: Sequence[Mapping[str, Any]] | None,
) -> set[str]:
    """Rebuild active facts from legacy projection plus append-only receipt log."""
    active = set(_clean_ids(branch_progress))
    for raw in scene_receipts or ():
        if not isinstance(raw, Mapping):
            continue
        fact_id = str(raw.get("fact_id") or "").strip()
        if not fact_id:
            continue
        if _receipt_operation(raw) == "retract":
            active.discard(fact_id)
        else:
            active.add(fact_id)
    return active


def _receipt_id(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "scene-fact:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class SceneFactReduceResult:
    branch_progress: tuple[str, ...]
    scene_receipts: tuple[dict[str, Any], ...]
    asserted: tuple[str, ...] = ()
    retracted: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()


def reduce_scene_facts(
    *,
    branch_progress: Sequence[Any] | None,
    scene_receipts: Sequence[Mapping[str, Any]] | None,
    scene_id: str,
    operation: str,
    fact_ids: Sequence[Any] = (),
    retract_ids: Sequence[Any] = (),
    owner: str,
    turn_no: int,
    source_kind: str,
    source_input: str = "",
    evidence_refs: Sequence[Any] = (),
) -> SceneFactReduceResult:
    """Pure scene-fact reducer with append-only evidence."""
    op = str(operation or "").strip()
    if op not in VALID_OPERATIONS:
        raise ValueError(f"unsupported scene fact operation: {op}")
    source = str(source_kind or "").strip()
    if not source:
        raise ValueError("scene fact operation requires source_kind")
    turn = int(turn_no)
    if turn < 0:
        raise ValueError("scene fact turn must be >= 0")

    branch = _clean_ids(branch_progress)
    receipts = [
        copy.deepcopy(dict(row))
        for row in (scene_receipts or ())
        if isinstance(row, Mapping)
    ]
    if op == "reset_all":
        return SceneFactReduceResult(branch_progress=(), scene_receipts=())

    scene = str(scene_id or "").strip()
    if not scene:
        raise ValueError("scene fact operation requires scene_id")
    owner_text = str(owner or "").strip()
    if not owner_text:
        raise ValueError("scene fact operation requires owner")

    requested = _clean_ids(fact_ids)
    retract = _clean_ids(retract_ids)
    if op == "retract" and not retract:
        retract = list(requested)
        requested = []
    if op == "replace" and not requested:
        raise ValueError("replace requires at least one asserted fact")
    if op in {"observe", "assert"} and not requested:
        return SceneFactReduceResult(tuple(branch), tuple(receipts))

    refs = [str(item).strip() for item in evidence_refs if str(item).strip()]
    asserted: list[str] = []
    retracted: list[str] = []
    receipt_ids: list[str] = []

    def append_event(fact_id: str, event_op: str) -> None:
        payload = {
            "schema_version": SCENE_FACT_RECEIPT_SCHEMA,
            "scene_id": scene,
            "fact_id": fact_id,
            "operation": event_op,
            "owner": owner_text,
            "turn": turn,
            "source_input": str(source_input or ""),
            "source_kind": source,
            "evidence_refs": list(refs),
            "ordinal": len(receipts),
        }
        payload["receipt_id"] = _receipt_id(payload)
        receipts.append(payload)
        receipt_ids.append(payload["receipt_id"])

    def latest_op(fact_id: str) -> str | None:
        for row in reversed(receipts):
            if str(row.get("scene_id") or "") != scene:
                continue
            if str(row.get("fact_id") or "") != fact_id:
                continue
            return _receipt_operation(row)
        return None

    to_retract = retract if op in {"retract", "replace"} else []
    for fact_id in to_retract:
        was_active = fact_id in active_fact_ids(branch, receipts)
        if fact_id in branch:
            branch = [item for item in branch if item != fact_id]
        if was_active:
            append_event(fact_id, "retract")
            retracted.append(fact_id)

    if op == "observe":
        for fact_id in requested:
            if latest_op(fact_id) not in {None, "retract"}:
                continue
            append_event(fact_id, "observe")
    elif op in {"assert", "replace"}:
        for fact_id in requested:
            branch_changed = fact_id not in branch
            if branch_changed:
                branch.append(fact_id)
                asserted.append(fact_id)
            if branch_changed or latest_op(fact_id) in {None, "retract"}:
                append_event(fact_id, "assert")

    return SceneFactReduceResult(
        branch_progress=tuple(branch),
        scene_receipts=tuple(copy.deepcopy(row) for row in receipts),
        asserted=tuple(asserted),
        retracted=tuple(retracted),
        receipt_ids=tuple(receipt_ids),
    )
