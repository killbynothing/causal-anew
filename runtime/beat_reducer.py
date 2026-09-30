"""P2c Beat authority for current completion and ancillary Beat state.

The reducer owns:
- current-scene completed beats;
- per-scene completion snapshots;
- cross-view physical frame beat ledger;
- deterministic canon-performance cursor state.

Session code receives copy-safe projections only. Legacy top-level fields are
accepted during load migration, but production writes stay inside this module.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from runtime import beat_ledger as frame_beat_ledger
from runtime.causal_protocol import canonical_payload_hash

BEAT_STATE_SCHEMA_V1 = "free_stage.beat_state.v1"
BEAT_STATE_SCHEMA = "free_stage.beat_state.v2"
BEAT_RECEIPT_SCHEMA = "free_stage.beat_receipt.v1"
_UNSET = object()

_CANON_DEFAULT = {
    "completed_segments": [],
    "not_visible_segments": [],
    "pending_stop": "",
    "player_position": "",
}


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


def _normalize_by_card(raw: Mapping[str, Any] | None) -> dict[str, list[str]]:
    return {
        str(scene_id): _normalize(values)
        for scene_id, values in dict(raw or {}).items()
        if str(scene_id).strip() and isinstance(values, (list, tuple))
    }


def _normalize_frame_ledger(raw: Mapping[str, Any] | None) -> dict[str, list[str]]:
    return {
        str(run_key): _normalize(values)
        for run_key, values in dict(raw or {}).items()
        if str(run_key).strip() and isinstance(values, (list, tuple))
    }


def _normalize_canon_state(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for scene_id, value in dict(raw or {}).items():
        if not str(scene_id).strip() or not isinstance(value, Mapping):
            continue
        state = copy.deepcopy(_CANON_DEFAULT)
        state["completed_segments"] = _normalize(value.get("completed_segments") or ())
        state["not_visible_segments"] = _normalize(value.get("not_visible_segments") or ())
        state["pending_stop"] = _text(value.get("pending_stop"))
        state["player_position"] = _text(value.get("player_position"))
        out[str(scene_id)] = state
    return out


class BeatReducer:
    def __init__(
        self,
        completed: Sequence[Any] | None = None,
        receipts: Sequence[Mapping[str, Any]] | None = None,
        *,
        completed_by_card: Mapping[str, Any] | None = None,
        completed_beats: Mapping[str, Any] | None = None,
        canon_performance_state: Mapping[str, Any] | None = None,
    ) -> None:
        self._completed: list[str] = _normalize(completed)
        self._completed_by_card: dict[str, list[str]] = _normalize_by_card(completed_by_card)
        self._completed_beats: dict[str, list[str]] = _normalize_frame_ledger(completed_beats)
        self._canon_performance_state: dict[str, dict[str, Any]] = _normalize_canon_state(
            canon_performance_state
        )
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
        legacy_completed_by_card: Mapping[str, Any] | None = None,
        legacy_completed_beats: Mapping[str, Any] | None = None,
        legacy_canon_performance_state: Mapping[str, Any] | None = None,
        scene_id: str = "",
    ) -> "BeatReducer":
        if raw is not None:
            if not isinstance(raw, Mapping):
                raise ValueError("beat_state must be an object")
            version = raw.get("schema_version")
            if version not in {BEAT_STATE_SCHEMA_V1, BEAT_STATE_SCHEMA}:
                raise ValueError(f"unsupported beat_state schema: {version!r}")
            completed = raw.get("completed") or ()
            receipts = raw.get("receipts") or ()
            if not isinstance(completed, (list, tuple)):
                raise ValueError("beat_state.completed must be list/tuple")
            if not isinstance(receipts, (list, tuple)):
                raise ValueError("beat_state.receipts must be list/tuple")
            if version == BEAT_STATE_SCHEMA_V1:
                return cls(
                    completed,
                    receipts,
                    completed_by_card=legacy_completed_by_card,
                    completed_beats=legacy_completed_beats,
                    canon_performance_state=legacy_canon_performance_state,
                )
            return cls(
                completed,
                receipts,
                completed_by_card=raw.get("completed_by_card"),
                completed_beats=raw.get("completed_beats"),
                canon_performance_state=raw.get("canon_performance_state"),
            )

        reducer = cls(
            completed_by_card=legacy_completed_by_card,
            completed_beats=legacy_completed_beats,
            canon_performance_state=legacy_canon_performance_state,
        )
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

    def completed_by_card_view(self) -> dict[str, list[str]]:
        return copy.deepcopy(self._completed_by_card)

    def completed_beats_view(self) -> dict[str, list[str]]:
        return copy.deepcopy(self._completed_beats)

    def canon_performance_state_view(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._canon_performance_state)

    def canon_scene_state(self, scene_id: str) -> dict[str, Any]:
        scene = _text(scene_id)
        state = self._canon_performance_state.get(scene)
        if state is None:
            return copy.deepcopy(_CANON_DEFAULT)
        return copy.deepcopy(state)

    def receipts(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(row) for row in self._receipts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BEAT_STATE_SCHEMA,
            "completed": self.view(),
            "completed_by_card": self.completed_by_card_view(),
            "completed_beats": self.completed_beats_view(),
            "canon_performance_state": self.canon_performance_state_view(),
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

    def snapshot_scene(
        self,
        scene_id: str,
        beat_ids: Sequence[Any] | None = None,
    ) -> list[str]:
        scene = _text(scene_id)
        if not scene:
            raise ValueError("scene snapshot requires scene_id")
        snapshot = _normalize(self._completed if beat_ids is None else beat_ids)
        self._completed_by_card[scene] = snapshot
        return list(snapshot)

    def replace_completed_by_card(self, raw: Mapping[str, Any] | None) -> None:
        self._completed_by_card = _normalize_by_card(raw)

    def mark_frame_beats(
        self,
        *,
        run: int,
        frame_id: str,
        beat_ids: Sequence[Any],
    ) -> tuple[str, ...]:
        frame = _text(frame_id)
        if int(run) < 1 or not frame:
            raise ValueError("frame beat mutation requires run>=1 and frame_id")
        before = frame_beat_ledger.completed_beats(self._completed_beats, int(run), frame)
        next_ledger = self.completed_beats_view()
        frame_beat_ledger.mark_done(
            next_ledger,
            int(run),
            frame,
            _normalize(beat_ids),
        )
        self._completed_beats = _normalize_frame_ledger(next_ledger)
        after = frame_beat_ledger.completed_beats(self._completed_beats, int(run), frame)
        return tuple(sorted(after - before))

    def frame_completed_beats(self, *, run: int, frame_id: str) -> set[str]:
        return frame_beat_ledger.completed_beats(
            self._completed_beats,
            int(run),
            _text(frame_id),
        )

    def replace_completed_beats(self, raw: Mapping[str, Any] | None) -> None:
        self._completed_beats = _normalize_frame_ledger(raw)

    def update_canon_scene(
        self,
        scene_id: str,
        *,
        completed_segment: str | None = None,
        hidden_segment: str | None = None,
        pending_stop: Any = _UNSET,
        player_position: Any = _UNSET,
    ) -> dict[str, Any]:
        scene = _text(scene_id)
        if not scene:
            raise ValueError("canon state mutation requires scene_id")
        state = self.canon_scene_state(scene)
        completed = _normalize(state.get("completed_segments") or ())
        hidden = _normalize(state.get("not_visible_segments") or ())
        completed_id = _text(completed_segment)
        hidden_id = _text(hidden_segment)
        if completed_id and completed_id not in completed:
            completed.append(completed_id)
        if hidden_id and hidden_id not in hidden:
            hidden.append(hidden_id)
        state["completed_segments"] = completed
        state["not_visible_segments"] = hidden
        if pending_stop is not _UNSET:
            state["pending_stop"] = _text(pending_stop)
        if player_position is not _UNSET:
            state["player_position"] = _text(player_position)
        self._canon_performance_state[scene] = copy.deepcopy(state)
        return copy.deepcopy(state)

    def replace_canon_performance_state(self, raw: Mapping[str, Any] | None) -> None:
        self._canon_performance_state = _normalize_canon_state(raw)

    def reset_all(self) -> None:
        self._completed = []
        self._completed_by_card = {}
        self._completed_beats = {}
        self._canon_performance_state = {}
        self._receipts = []
        self._receipt_ids = set()
