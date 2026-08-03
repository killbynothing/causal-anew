"""The serialisable domain boundary for a playable session.

The existing free-stage session still exposes legacy fields while the runtime is
being migrated.  This envelope makes their ownership explicit and gives future
routers/frames one stable hand-off format without changing saved games in place.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from runtime.entry_context import EntryContext


@dataclass(frozen=True)
class SessionDomainState:
    player_identity: dict[str, Any]
    world_cursor: dict[str, Any]
    route_ledger: list[str]
    entry_context: EntryContext | None = None

    SCHEMA_VERSION = 1

    @classmethod
    def from_legacy(
        cls,
        *,
        player_profile: dict[str, Any] | None,
        world_cursor: dict[str, Any] | None,
        branch_progress: list[str] | None,
        entry_context: EntryContext | None,
    ) -> "SessionDomainState":
        return cls(
            player_identity=copy.deepcopy(dict(player_profile or {})),
            world_cursor=copy.deepcopy(dict(world_cursor or {})),
            route_ledger=[str(item) for item in branch_progress or [] if str(item).strip()],
            entry_context=entry_context,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "player_identity": copy.deepcopy(self.player_identity),
            "world_cursor": copy.deepcopy(self.world_cursor),
            "route_ledger": list(self.route_ledger),
            "entry_context": self.entry_context.to_dict() if self.entry_context else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "SessionDomainState | None":
        if not isinstance(raw, dict) or raw.get("schema_version") != cls.SCHEMA_VERSION:
            return None
        player_identity = raw.get("player_identity")
        world_cursor = raw.get("world_cursor")
        route_ledger = raw.get("route_ledger")
        if not isinstance(player_identity, dict) or not isinstance(world_cursor, dict) or not isinstance(route_ledger, list):
            return None
        return cls(
            player_identity=copy.deepcopy(player_identity),
            world_cursor=copy.deepcopy(world_cursor),
            route_ledger=[str(item) for item in route_ledger if str(item).strip()],
            entry_context=EntryContext.from_dict(raw.get("entry_context")),
        )

    def legacy_fields(self) -> dict[str, Any]:
        """Compatibility adapter; remove only after callers use this state directly."""
        return {
            "player_profile": copy.deepcopy(self.player_identity),
            "world_cursor": copy.deepcopy(self.world_cursor),
            "branch_progress": list(self.route_ledger),
            "entry_context": self.entry_context,
        }
