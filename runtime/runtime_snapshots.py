"""Immutable P0b snapshot views.

Snapshots are read-only protocol views. They do not own persistence and are not
wired into FreeStageSession production yet.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from runtime.causal_protocol import RuntimeScope


def _freeze_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _thaw_json(payload_json: str) -> dict[str, Any]:
    raw = json.loads(payload_json)
    if not isinstance(raw, dict):
        raise ValueError("snapshot payload must decode to an object")
    return raw


@dataclass(frozen=True)
class WorldSnapshot:
    scope: RuntimeScope
    revision: int
    _payload_json: str
    source_receipt_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("snapshot revision must be >= 0")
        _thaw_json(self._payload_json)

    @classmethod
    def capture(
        cls,
        *,
        scope: RuntimeScope,
        revision: int,
        payload: Mapping[str, Any],
        source_receipt_ids: tuple[str, ...] | list[str] = (),
    ) -> "WorldSnapshot":
        return cls(
            scope=scope,
            revision=int(revision),
            _payload_json=_freeze_json(payload),
            source_receipt_ids=tuple(str(x) for x in source_receipt_ids if str(x).strip()),
        )

    def payload(self) -> dict[str, Any]:
        """Return a fresh mutable copy; mutating it cannot mutate the snapshot."""
        return _thaw_json(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "revision": self.revision,
            "payload": self.payload(),
            "source_receipt_ids": list(self.source_receipt_ids),
        }


@dataclass(frozen=True)
class ActorSnapshot:
    scope: RuntimeScope
    actor_cons: str
    revision: int
    _payload_json: str
    source_receipt_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.actor_cons.strip():
            raise ValueError("actor snapshot requires actor_cons")
        if self.revision < 0:
            raise ValueError("snapshot revision must be >= 0")
        _thaw_json(self._payload_json)

    @classmethod
    def capture(
        cls,
        *,
        scope: RuntimeScope,
        actor_cons: str,
        revision: int,
        payload: Mapping[str, Any],
        source_receipt_ids: tuple[str, ...] | list[str] = (),
    ) -> "ActorSnapshot":
        return cls(
            scope=scope,
            actor_cons=str(actor_cons),
            revision=int(revision),
            _payload_json=_freeze_json(payload),
            source_receipt_ids=tuple(str(x) for x in source_receipt_ids if str(x).strip()),
        )

    def payload(self) -> dict[str, Any]:
        return _thaw_json(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "actor_cons": self.actor_cons,
            "revision": self.revision,
            "payload": self.payload(),
            "source_receipt_ids": list(self.source_receipt_ids),
        }
