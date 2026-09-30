"""P2c-1 single owner for current-scene Beat completion state.

FreeStageSession may expose completed as a compatibility view, but all
production completion/restore/reset writes are reduced here with source
metadata. Legacy snapshots are migrated as legacy evidence, never fabricated
as player action receipts.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"
BEAT_RECEIPT_SCHEMA = "free_stage.beat_receipt.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        beat = _text(raw)
        if not beat or beat in seen:
            continue
        seen.add(beat)
        out.append(beat)
    return out


class BeatReducer:
    def __init__(
        self,
        completed: Sequence[Any] | None = None,
        receipts: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._completed: list[str] = _normalize(completed)
        self._receipts: list[dict[str, Any]] = [
            copy.deepcopy(dict(row))
            for row in (receipts or ())
            if isinstance(row, Mapping)
        ]
        self._receipt_ids: set[str] = {
            _text(row.get("receipt_id"))
            for row in self._receipts
            if _text(row.get("receipt_id"))
        }

    @classmethod
    def from_state(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_completed: Sequence[Any] | None = None,
        scene_id: str = "",
    ) -> "BeatReducer":
        if raw is not None:
            if not isinstance(raw, Mapping):
                raise ValueError("beat_state must be an object")
            if raw.get("schema_version") != BEAT_STATE_SCHEMA:
                raise ValueError(
                    f"unsupported beat_state schema: {raw.get('schema_version')!r}"
                )
            completed = raw.get("completed") or ()
            receipts = raw.get("receipts") or ()
            if not isinstance(completed, (list, tuple)):
                raise ValueError("beat_state.completed must be list/tuple")
            if not isinstance(receipts, (list, tuple)):
                raise ValueError("beat_state.receipts must be list/tuple")
            return cls(completed, receipts)

        reducer = cls()
        reducer.replace_current(
            legacy_completed or (),
            scene_id=scene_id,
            turn=0,
            source_kind="legacy_load",
            source_ref="session.completed",
            operation="legacy_restore",
        )
        return reducer

    def view(self) -> list[str]:
        return list(self._completed)

    def receipts(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(row) for row in self._receipts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BEAT_STATE_SCHEMA,
            "completed": self.view(),
            "receipts": self.receipts(),
        }

    def _append_receipt(
        self,
        beat_id: str,
        *,
        scene_id: str,
        turn: int,
        source_kind: str,
        source_ref: str,
        operation: str,
    ) -> None:
        source = _text(source_kind)
        if not source:
            raise ValueError("beat mutation requires source_kind")
        payload = {
            "beat_id": _text(beat_id),
            "scene_id": _text(scene_id),
            "turn": int(turn),
            "source_kind": source,
            "source_ref": _text(source_ref),
            "operation": _text(operation) or "complete",
        }
        receipt_id = f"beat:{canonical_payload_hash(payload)}"
        if receipt_id in self._receipt_ids:
            return
        self._receipts.append(
            {
                "schema_version": BEAT_RECEIPT_SCHEMA,
                "receipt_id": receipt_id,
                **payload,
            }
        )
        self._receipt_ids.add(receipt_id)

    def complete(
        self,
        beat_id: str,
        *,
        scene_id: str,
        turn: int,
        source_kind: str,
        source_ref: str = "",
    ) -> bool:
        beat = _text(beat_id)
        if not beat:
            return False
        if beat in self._completed:
            return False
        self._completed.append(beat)
        self._append_receipt(
            beat,
            scene_id=scene_id,
            turn=turn,
            source_kind=source_kind,
            source_ref=source_ref,
            operation="complete",
        )
        return True

    def complete_many(
        self,
        beat_ids: Sequence[Any],
        *,
        scene_id: str,
        turn: int,
        source_kind: str,
        source_ref: str = "",
    ) -> tuple[str, ...]:
        added: list[str] = []
        for beat in _normalize(beat_ids):
            if self.complete(
                beat,
                scene_id=scene_id,
                turn=turn,
                source_kind=source_kind,
                source_ref=source_ref,
            ):
                added.append(beat)
        return tuple(added)

    def replace_current(
        self,
        beat_ids: Sequence[Any],
        *,
        scene_id: str,
        turn: int,
        source_kind: str,
        source_ref: str = "",
        operation: str = "restore",
    ) -> tuple[str, ...]:
        target = _normalize(beat_ids)
        previous = set(self._completed)
        self._completed = target
        added: list[str] = []
        for beat in target:
            if beat in previous:
                continue
            self._append_receipt(
                beat,
                scene_id=scene_id,
                turn=turn,
                source_kind=source_kind,
                source_ref=source_ref,
                operation=operation,
            )
            added.append(beat)
        return tuple(added)

    def clear_current(self) -> None:
        self._completed = []

    def reset_all(self) -> None:
        self._completed = []
        self._receipts = []
        self._receipt_ids = set()
