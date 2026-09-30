"""P2c-7 single owner for the playable world's runtime cursor.

world_calendar remains the pure rule kernel. This owner only controls mutable
cursor state and returns copy-only views so session/domain envelopes cannot
become a second write authority.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from runtime import world_calendar


def _normalize(
    raw: Mapping[str, Any] | None,
    *,
    default_run: int = 1,
    default_worldline: str = "WMAIN",
) -> dict[str, Any]:
    cursor = copy.deepcopy(dict(raw or {}))
    try:
        ch_anchor = int(cursor.get("ch_anchor", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("world cursor ch_anchor must be an integer") from exc
    try:
        run = int(cursor.get("run", default_run) or default_run)
    except (TypeError, ValueError) as exc:
        raise ValueError("world cursor run must be an integer") from exc
    if run < 1:
        raise ValueError("playable world cursor requires run>=1")
    worldline = str(cursor.get("worldline") or default_worldline).strip()
    if not worldline:
        raise ValueError("world cursor requires worldline")
    world_clock = str(cursor.get("world_clock") or "00:00").strip()
    # Reuse the existing rule kernel for clock parsing; P2c-7 does not invent
    # new time semantics.
    world_calendar.minutes(world_clock)

    cursor["ch_anchor"] = ch_anchor
    cursor["world_clock"] = world_clock
    cursor["run"] = run
    cursor["worldline"] = worldline
    return cursor


class WorldCursorOwner:
    """Own one mutable cursor; every public read is a deep copy."""

    def __init__(self, cursor: Mapping[str, Any] | None = None) -> None:
        self._cursor = _normalize(cursor)

    @classmethod
    def from_legacy(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        fallback: Mapping[str, Any],
    ) -> "WorldCursorOwner":
        source = raw if isinstance(raw, Mapping) and raw else fallback
        return cls(source)

    def view(self) -> dict[str, Any]:
        return copy.deepcopy(self._cursor)

    def replace(self, cursor: Mapping[str, Any]) -> dict[str, Any]:
        """Explicit scene/reset/flashback replacement.

        This preserves legacy semantics for deliberate coordinate jumps. Normal
        chronological transitions must use advance(), which enforces monotonic
        world-calendar time.
        """
        self._cursor = _normalize(
            cursor,
            default_run=int(self._cursor.get("run", 1) or 1),
            default_worldline=str(self._cursor.get("worldline") or "WMAIN"),
        )
        return self.view()

    def set_run(self, run: int) -> dict[str, Any]:
        updated = world_calendar.with_run(self._cursor, int(run))
        self._cursor = _normalize(
            updated,
            default_run=int(run),
            default_worldline=str(self._cursor.get("worldline") or "WMAIN"),
        )
        return self.view()

    def advance(
        self,
        *,
        ch_anchor: int | None = None,
        world_clock: str | None = None,
    ) -> dict[str, Any]:
        """Monotonic transition; failure leaves the owned cursor unchanged."""
        old = self.view()
        candidate = world_calendar.advance(
            old,
            ch_anchor=ch_anchor,
            world_clock=world_clock,
        )
        # Time advancement may not alter the orthogonal axes.
        candidate["run"] = old["run"]
        candidate["worldline"] = old["worldline"]
        normalized = _normalize(candidate)
        self._cursor = normalized
        return self.view()
