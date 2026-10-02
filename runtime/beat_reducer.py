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


SCENE_BEAT_ARCHIVE_SCHEMA = "free_stage.scene_beat_archive.v1"


@dataclass
class SceneBeatArchive:
    """Cross-scene completion snapshots owned by BeatReducer.

    This preserves the legacy "latest snapshot per scene" semantics. It does
    not reinterpret scene completion as append-only history.
    """
    _by_scene: dict[str, list[str]] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_version: str = SCENE_BEAT_ARCHIVE_SCHEMA

    @classmethod
    def empty(cls) -> "SceneBeatArchive":
        return cls()

    @classmethod
    def from_snapshot(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_completed_by_card: Mapping[str, Any] | None = None,
    ) -> "SceneBeatArchive":
        if raw is None:
            state = cls.empty()
            for scene_id, beats in dict(legacy_completed_by_card or {}).items():
                if isinstance(beats, (list, tuple, set)):
                    state.record(
                        str(scene_id),
                        list(beats),
                        source_kind="legacy_snapshot",
                        source_ref="free_stage.session.v1:completed_by_card",
                        turn=0,
                    )
            return state
        if not isinstance(raw, Mapping):
            raise ValueError("scene_beat_archive must be an object")
        if raw.get("schema_version") != SCENE_BEAT_ARCHIVE_SCHEMA:
            raise ValueError(
                f"unsupported scene_beat_archive schema: {raw.get('schema_version')}"
            )
        by_scene_raw = raw.get("completed_by_card") or {}
        sources_raw = raw.get("sources") or {}
        if not isinstance(by_scene_raw, Mapping) or not isinstance(sources_raw, Mapping):
            raise ValueError("scene_beat_archive fields must be objects")
        state = cls.empty()
        state._by_scene = {
            _text(scene_id): list(dict.fromkeys(
                _text(item) for item in beats if _text(item)
            ))
            for scene_id, beats in by_scene_raw.items()
            if _text(scene_id) and isinstance(beats, (list, tuple))
        }
        state.sources = {
            _text(scene_id): dict(source)
            for scene_id, source in sources_raw.items()
            if _text(scene_id) and isinstance(source, Mapping)
        }
        for scene_id, beats in state._by_scene.items():
            state.sources.setdefault(
                scene_id,
                state._make_source(
                    scene_id,
                    beats,
                    source_kind="legacy_snapshot",
                    source_ref="scene_beat_archive:missing_source",
                    turn=0,
                ),
            )
        return state

    @property
    def completed_by_card(self) -> dict[str, list[str]]:
        return {scene_id: list(beats) for scene_id, beats in self._by_scene.items()}

    def _make_source(
        self,
        scene_id: str,
        beats: Sequence[Any],
        *,
        source_kind: str,
        source_ref: str,
        turn: int,
    ) -> dict[str, Any]:
        normalized = [_text(item) for item in beats if _text(item)]
        payload = {
            "scene_id": _text(scene_id),
            "completed": list(dict.fromkeys(normalized)),
            "source_kind": _text(source_kind) or "unspecified",
            "source_ref": _text(source_ref),
            "turn": int(turn),
        }
        return {
            "archive_id": f"scene-beat:{canonical_payload_hash(payload)}",
            **payload,
        }

    def record(
        self,
        scene_id: str,
        completed: Sequence[Any],
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> bool:
        scene = _text(scene_id)
        if not scene:
            raise ValueError("scene beat archive requires scene_id")
        beats = list(dict.fromkeys(_text(item) for item in completed if _text(item)))
        if self._by_scene.get(scene) == beats:
            return False
        self._by_scene[scene] = beats
        self.sources[scene] = self._make_source(
            scene,
            beats,
            source_kind=source_kind,
            source_ref=source_ref,
            turn=turn,
        )
        return True

    def replace_all(
        self,
        values: Mapping[str, Any] | None,
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> None:
        self._by_scene = {}
        self.sources = {}
        for scene_id, beats in dict(values or {}).items():
            if isinstance(beats, (list, tuple, set)):
                self.record(
                    str(scene_id),
                    list(beats),
                    source_kind=source_kind,
                    source_ref=source_ref,
                    turn=turn,
                )

    def reset(self) -> None:
        self._by_scene = {}
        self.sources = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "completed_by_card": self.completed_by_card,
            "sources": {key: dict(value) for key, value in self.sources.items()},
        }


CANON_PERFORMANCE_STATE_SCHEMA = "free_stage.canon_performance_state.v1"
_CANON_UNSET = object()


def _canon_scene_defaults(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = dict(raw or {})
    return {
        "completed_segments": list(dict.fromkeys(
            _text(item) for item in (data.get("completed_segments") or []) if _text(item)
        )),
        "not_visible_segments": list(dict.fromkeys(
            _text(item) for item in (data.get("not_visible_segments") or []) if _text(item)
        )),
        "pending_stop": _text(data.get("pending_stop")),
        "player_position": _text(data.get("player_position")),
    }


@dataclass
class CanonPerformanceState:
    """Single mutable owner for canonical performance progress."""

    _scenes: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    revision: int = 0
    schema_version: str = CANON_PERFORMANCE_STATE_SCHEMA

    @classmethod
    def empty(cls) -> "CanonPerformanceState":
        return cls()

    @classmethod
    def from_snapshot(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_state: Mapping[str, Any] | None = None,
    ) -> "CanonPerformanceState":
        if raw is None:
            state = cls.empty()
            state.replace_all(
                legacy_state or {},
                source_kind="legacy_snapshot",
                source_ref="canon_performance_state",
                turn=0,
            )
            return state
        if not isinstance(raw, Mapping):
            raise ValueError("canon_performance must be an object")
        if raw.get("schema_version") != CANON_PERFORMANCE_STATE_SCHEMA:
            raise ValueError(
                f"unsupported canon_performance schema: {raw.get('schema_version')}"
            )
        scenes_raw = raw.get("scenes") or {}
        sources_raw = raw.get("sources") or {}
        if not isinstance(scenes_raw, Mapping) or not isinstance(sources_raw, Mapping):
            raise ValueError("canon_performance scenes/sources must be objects")
        return cls(
            _scenes={
                _text(scene_id): _canon_scene_defaults(scene)
                for scene_id, scene in scenes_raw.items()
                if _text(scene_id) and isinstance(scene, Mapping)
            },
            sources={
                _text(scene_id): dict(source)
                for scene_id, source in sources_raw.items()
                if _text(scene_id) and isinstance(source, Mapping)
            },
            revision=max(0, int(raw.get("revision", 0) or 0)),
        )

    @property
    def scenes(self) -> dict[str, dict[str, Any]]:
        return {
            scene_id: {
                "completed_segments": list(state["completed_segments"]),
                "not_visible_segments": list(state["not_visible_segments"]),
                "pending_stop": state["pending_stop"],
                "player_position": state["player_position"],
            }
            for scene_id, state in self._scenes.items()
        }

    def scene(self, scene_id: str) -> dict[str, Any]:
        scene = _text(scene_id)
        state = _canon_scene_defaults(self._scenes.get(scene))
        return {
            "completed_segments": list(state["completed_segments"]),
            "not_visible_segments": list(state["not_visible_segments"]),
            "pending_stop": state["pending_stop"],
            "player_position": state["player_position"],
        }

    def update_scene(
        self,
        scene_id: str,
        *,
        add_completed: Sequence[Any] = (),
        add_hidden: Sequence[Any] = (),
        pending_stop: Any = _CANON_UNSET,
        player_position: Any = _CANON_UNSET,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> bool:
        scene = _text(scene_id)
        if not scene:
            raise ValueError("canon performance update requires scene_id")
        before = _canon_scene_defaults(self._scenes.get(scene))
        after = _canon_scene_defaults(before)
        for raw in add_completed:
            value = _text(raw)
            if value and value not in after["completed_segments"]:
                after["completed_segments"].append(value)
        for raw in add_hidden:
            value = _text(raw)
            if value and value not in after["not_visible_segments"]:
                after["not_visible_segments"].append(value)
        if pending_stop is not _CANON_UNSET:
            after["pending_stop"] = _text(pending_stop)
        if player_position is not _CANON_UNSET:
            after["player_position"] = _text(player_position)
        if after == before and scene in self._scenes:
            return False
        self._scenes[scene] = after
        self.revision += 1
        payload = {
            "scene_id": scene,
            "state": after,
            "source_kind": _text(source_kind) or "unspecified",
            "source_ref": _text(source_ref),
            "turn": int(turn),
        }
        self.sources[scene] = {
            "receipt_id": f"canon-performance:{canonical_payload_hash(payload)}",
            **payload,
        }
        return True

    def replace_all(
        self,
        values: Mapping[str, Any] | None,
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
    ) -> None:
        self._scenes = {}
        self.sources = {}
        for scene_id, scene in dict(values or {}).items():
            if not isinstance(scene, Mapping):
                continue
            normalized = _canon_scene_defaults(scene)
            self._scenes[_text(scene_id)] = normalized
            payload = {
                "scene_id": _text(scene_id),
                "state": normalized,
                "source_kind": _text(source_kind) or "unspecified",
                "source_ref": _text(source_ref),
                "turn": int(turn),
            }
            self.sources[_text(scene_id)] = {
                "receipt_id": f"canon-performance:{canonical_payload_hash(payload)}",
                **payload,
            }

    def reset(self) -> None:
        if self._scenes or self.sources:
            self._scenes = {}
            self.sources = {}
            self.revision += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "scenes": self.scenes,
            "sources": {key: dict(value) for key, value in self.sources.items()},
        }
