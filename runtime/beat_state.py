"""P2c authoritative must-happen completion state.

BeatState owns the mutable current completion list and per-card snapshots.
Legacy completed/completed_by_card remain serialization projections only.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"


def _clean_ids(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


@dataclass
class BeatState:
    _completed: list[str] = field(default_factory=list)
    _completed_by_card: dict[str, list[str]] = field(default_factory=dict)
    _events: list[dict[str, Any]] = field(default_factory=list)
    _legacy_unresolved: list[str] = field(default_factory=list)

    @classmethod
    def from_saved(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_completed: Sequence[Any] | None = None,
        legacy_completed_by_card: Mapping[str, Any] | None = None,
    ) -> "BeatState":
        data = dict(raw or {})
        if data.get("schema_version") == BEAT_STATE_SCHEMA:
            completed = _clean_ids(data.get("completed"))
            by_card = {
                str(scene): _clean_ids(values)
                for scene, values in dict(data.get("completed_by_card") or {}).items()
                if isinstance(values, (list, tuple))
            }
            events = [
                copy.deepcopy(item)
                for item in data.get("events", [])
                if isinstance(item, dict)
            ]
            legacy = _clean_ids(data.get("legacy_unresolved"))
            return cls(completed, by_card, events, legacy)

        completed = _clean_ids(legacy_completed)
        by_card = {
            str(scene): _clean_ids(values)
            for scene, values in dict(legacy_completed_by_card or {}).items()
            if isinstance(values, (list, tuple))
        }
        return cls(completed, by_card, [], list(completed))

    def completed(self) -> list[str]:
        return list(self._completed)

    def completed_by_card(self) -> dict[str, list[str]]:
        return {scene: list(values) for scene, values in self._completed_by_card.items()}

    def events(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(item) for item in self._events]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BEAT_STATE_SCHEMA,
            "completed": self.completed(),
            "completed_by_card": self.completed_by_card(),
            "events": self.events(),
            "legacy_unresolved": list(self._legacy_unresolved),
        }

    def reset(self) -> None:
        self._completed.clear()
        self._completed_by_card.clear()
        self._events.clear()
        self._legacy_unresolved.clear()

    def clear_current(self) -> None:
        self._completed.clear()

    def replace_current(
        self,
        beat_ids: Sequence[Any],
        *,
        scene_id: str,
        source_kind: str,
        turn: int,
        source_refs: Sequence[str] = (),
        legacy: bool = False,
    ) -> list[str]:
        self._completed = []
        if legacy:
            self._completed = _clean_ids(beat_ids)
            self._legacy_unresolved = _clean_ids(
                [*self._legacy_unresolved, *self._completed]
            )
            return self.completed()
        self.complete_many(
            beat_ids,
            scene_id=scene_id,
            source_kind=source_kind,
            turn=turn,
            source_refs=source_refs,
        )
        return self.completed()

    def complete(
        self,
        beat_id: str,
        *,
        scene_id: str,
        source_kind: str,
        turn: int,
        source_refs: Sequence[str] = (),
    ) -> bool:
        beat = str(beat_id or "").strip()
        source = str(source_kind or "").strip()
        if not beat or not source:
            raise ValueError("beat completion requires beat_id and source_kind")
        if int(turn) < 0:
            raise ValueError("beat completion turn must be >= 0")
        if beat in self._completed:
            return False
        self._completed.append(beat)
        self._legacy_unresolved = [item for item in self._legacy_unresolved if item != beat]
        self._events.append({
            "beat_id": beat,
            "scene_id": str(scene_id or "").strip(),
            "source_kind": source,
            "turn": int(turn),
            "source_refs": [str(item) for item in source_refs if str(item).strip()],
        })
        return True

    def complete_many(
        self,
        beat_ids: Sequence[Any],
        *,
        scene_id: str,
        source_kind: str,
        turn: int,
        source_refs: Sequence[str] = (),
    ) -> list[str]:
        added: list[str] = []
        for beat in _clean_ids(beat_ids):
            if self.complete(
                beat,
                scene_id=scene_id,
                source_kind=source_kind,
                turn=turn,
                source_refs=source_refs,
            ):
                added.append(beat)
        return added

    def snapshot_card(self, scene_id: str) -> None:
        scene = str(scene_id or "").strip()
        if not scene:
            raise ValueError("beat snapshot requires scene_id")
        self._completed_by_card[scene] = self.completed()

    def restore_current(
        self,
        beat_ids: Sequence[Any],
        *,
        scene_id: str,
        source_kind: str = "snapshot_restore",
        turn: int = 0,
    ) -> None:
        self.replace_current(
            beat_ids,
            scene_id=scene_id,
            source_kind=source_kind,
            turn=turn,
            source_refs=(),
        )
