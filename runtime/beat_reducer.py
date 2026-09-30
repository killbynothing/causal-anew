"""P2c scene-local BeatState authority.

completed is a compatibility projection. Production beat completion must flow
through BeatState so every first completion keeps a machine-readable source.
Legacy snapshots migrate without inventing historical evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class BeatState:
    scene_id: str
    _completed: list[str] = field(default_factory=list)
    receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_version: str = BEAT_STATE_SCHEMA

    @classmethod
    def empty(cls, scene_id: str) -> "BeatState":
        return cls(scene_id=_text(scene_id))

    @classmethod
    def from_snapshot(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        scene_id: str,
        legacy_completed: Sequence[Any] = (),
    ) -> "BeatState":
        if raw is None:
            state = cls.empty(scene_id)
            state.replace_scene(
                scene_id,
                [_text(item) for item in legacy_completed if _text(item)],
                source_kind="legacy_snapshot",
                source_ref="free_stage.session.v1:completed",
                turn=0,
            )
            return state
        if not isinstance(raw, Mapping):
            raise ValueError("beat_state must be an object")
        if raw.get("schema_version") != BEAT_STATE_SCHEMA:
            raise ValueError(f"unsupported beat_state schema: {raw.get('schema_version')}")
        stored_scene = _text(raw.get("scene_id")) or _text(scene_id)
        completed = [_text(item) for item in (raw.get("completed") or []) if _text(item)]
        receipts_raw = raw.get("receipts") or {}
        if not isinstance(receipts_raw, Mapping):
            raise ValueError("beat_state.receipts must be an object")
        receipts = {
            _text(key): dict(value)
            for key, value in receipts_raw.items()
            if _text(key) and isinstance(value, Mapping)
        }
        if set(receipts) - set(completed):
            raise ValueError("beat_state receipt exists for non-completed beat")
        state = cls(
            scene_id=stored_scene,
            _completed=list(dict.fromkeys(completed)),
            receipts=receipts,
        )
        for beat in state._completed:
            if beat not in state.receipts:
                state.receipts[beat] = state._make_receipt(
                    beat,
                    source_kind="legacy_snapshot",
                    source_ref="beat_state:missing_receipt",
                    turn=0,
                )
        return state

    @property
    def completed(self) -> list[str]:
        return list(self._completed)

    def _make_receipt(
        self,
        beat_id: str,
        *,
        source_kind: str,
        source_ref: str,
        turn: int,
    ) -> dict[str, Any]:
        payload = {
            "scene_id": self.scene_id,
            "beat_id": beat_id,
            "source_kind": _text(source_kind) or "unspecified",
            "source_ref": _text(source_ref),
            "turn": int(turn),
        }
        return {
            "receipt_id": f"beat:{canonical_payload_hash(payload)}",
            **payload,
        }

    def complete(
        self,
        beat_id: str,
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> bool:
        beat = _text(beat_id)
        if not beat:
            raise ValueError("beat completion requires beat_id")
        if beat in self._completed:
            return False
        self._completed.append(beat)
        self.receipts[beat] = self._make_receipt(
            beat,
            source_kind=source_kind,
            source_ref=source_ref,
            turn=turn,
        )
        return True

    def complete_many(
        self,
        beats: Sequence[Any],
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> list[str]:
        newly: list[str] = []
        for raw in beats:
            beat = _text(raw)
            if beat and self.complete(
                beat,
                source_kind=source_kind,
                source_ref=source_ref,
                turn=turn,
            ):
                newly.append(beat)
        return newly

    def replace_scene(
        self,
        scene_id: str,
        completed: Sequence[Any] = (),
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> None:
        self.scene_id = _text(scene_id)
        self._completed = []
        self.receipts = {}
        self.complete_many(
            completed,
            source_kind=source_kind,
            source_ref=source_ref,
            turn=turn,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scene_id": self.scene_id,
            "completed": self.completed,
            "receipts": {key: dict(value) for key, value in self.receipts.items()},
        }
