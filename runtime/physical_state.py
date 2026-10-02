"""P2c owner for player physical state and NPC BodyFrame projections."""
from __future__ import annotations

import copy
from typing import Any, Mapping

PHYSICAL_STATE_SCHEMA = "free_stage.physical_state.v1"

DEFAULT_PLAYER_STATE: dict[str, Any] = {
    "injury": "正常/良好",
    "status": "行动中",
    "convergence_rate": 100,
    "energy": 0.78,
    "physical": "good",
    "elapsed_minutes": 0,
}


def _normalize_player(raw: Any) -> dict[str, Any]:
    out = copy.deepcopy(DEFAULT_PLAYER_STATE)
    if isinstance(raw, Mapping):
        out.update(copy.deepcopy(dict(raw)))
    return out


def _normalize_frames(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): copy.deepcopy(dict(value))
        for key, value in raw.items()
        if str(key).strip() and isinstance(value, Mapping)
    }


class PhysicalState:
    """Single mutable owner; public views are defensive copies."""

    def __init__(
        self,
        player_state: Any = None,
        body_frames: Any = None,
        *,
        revision: int = 0,
        last_source: Mapping[str, Any] | None = None,
    ) -> None:
        self._player = _normalize_player(player_state)
        self._frames = _normalize_frames(body_frames)
        self._revision = max(0, int(revision or 0))
        self._last_source = copy.deepcopy(dict(last_source or {}))

    @classmethod
    def empty(cls) -> "PhysicalState":
        return cls()

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Any,
        *,
        legacy_player_state: Any = None,
        legacy_body_frames: Any = None,
    ) -> "PhysicalState":
        if (
            isinstance(snapshot, Mapping)
            and snapshot.get("schema_version") == PHYSICAL_STATE_SCHEMA
        ):
            return cls(
                snapshot.get("player_state"),
                snapshot.get("body_frames"),
                revision=int(snapshot.get("revision", 0) or 0),
                last_source=(
                    snapshot.get("last_source")
                    if isinstance(snapshot.get("last_source"), Mapping)
                    else None
                ),
            )
        return cls(
            legacy_player_state,
            legacy_body_frames,
            last_source={"kind": "legacy_snapshot", "ref": "player_state+body_frames"},
        )

    @property
    def player_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._player)

    @property
    def body_frames(self) -> dict[str, Any]:
        return copy.deepcopy(self._frames)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def last_source(self) -> dict[str, Any]:
        return copy.deepcopy(self._last_source)

    def _commit(self, *, source_kind: str, source_ref: str) -> None:
        self._revision += 1
        self._last_source = {
            "kind": str(source_kind or "unknown"),
            "ref": str(source_ref or ""),
        }

    def replace_player(
        self,
        value: Any,
        *,
        source_kind: str,
        source_ref: str = "",
    ) -> bool:
        candidate = _normalize_player(value)
        if candidate == self._player:
            return False
        self._player = candidate
        self._commit(source_kind=source_kind, source_ref=source_ref)
        return True

    def patch_player(
        self,
        patch: Mapping[str, Any],
        *,
        source_kind: str,
        source_ref: str = "",
        preserve: tuple[str, ...] = (),
    ) -> bool:
        candidate = copy.deepcopy(self._player)
        preserved = {key: candidate.get(key) for key in preserve}
        candidate.update(copy.deepcopy(dict(patch)))
        for key, value in preserved.items():
            candidate[key] = value
        candidate = _normalize_player(candidate)
        if candidate == self._player:
            return False
        self._player = candidate
        self._commit(source_kind=source_kind, source_ref=source_ref)
        return True

    def increment_elapsed(
        self,
        minutes: int,
        *,
        source_kind: str,
        source_ref: str = "",
    ) -> int:
        current = int(self._player.get("elapsed_minutes", 0) or 0)
        self.patch_player(
            {"elapsed_minutes": current + int(minutes)},
            source_kind=source_kind,
            source_ref=source_ref,
        )
        return int(self._player.get("elapsed_minutes", 0) or 0)

    def decrease_convergence(
        self,
        amount: int,
        *,
        source_kind: str,
        source_ref: str = "",
    ) -> int:
        current = int(self._player.get("convergence_rate", 100) or 0)
        value = max(0, current - int(amount))
        self.patch_player(
            {"convergence_rate": value},
            source_kind=source_kind,
            source_ref=source_ref,
        )
        return value

    def replace_body_frames(
        self,
        value: Any,
        *,
        source_kind: str,
        source_ref: str = "",
    ) -> bool:
        candidate = _normalize_frames(value)
        if candidate == self._frames:
            return False
        self._frames = candidate
        self._commit(source_kind=source_kind, source_ref=source_ref)
        return True

    def replace_all(
        self,
        *,
        player_state: Any,
        body_frames: Any,
        source_kind: str,
        source_ref: str = "",
    ) -> bool:
        player = _normalize_player(player_state)
        frames = _normalize_frames(body_frames)
        if player == self._player and frames == self._frames:
            return False
        self._player = player
        self._frames = frames
        self._commit(source_kind=source_kind, source_ref=source_ref)
        return True

    def reset(self, *, source_kind: str = "session_reset", source_ref: str = "") -> None:
        changed = self._player != DEFAULT_PLAYER_STATE or bool(self._frames)
        self._player = copy.deepcopy(DEFAULT_PLAYER_STATE)
        self._frames = {}
        if changed:
            self._commit(source_kind=source_kind, source_ref=source_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PHYSICAL_STATE_SCHEMA,
            "revision": self._revision,
            "last_source": self.last_source,
            "player_state": self.player_state,
            "body_frames": self.body_frames,
        }
