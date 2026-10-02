"""P2c single mutable owner for the session world cursor.

This closes direct Session writers first. In-world transition provenance is
still tracked as P2 debt until cursor moves are sourced from WorldCommit
receipts; snapshot/reset replacements are compatibility/tooling operations.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from runtime import world_calendar

WORLD_CURSOR_STATE_SCHEMA = "free_stage.world_cursor_state.v1"


def _normalize(raw: Mapping[str, Any] | None, *, run: int) -> dict[str, Any]:
    cursor = copy.deepcopy(dict(raw or {}))
    try:
        run_no = int(run)
    except (TypeError, ValueError):
        run_no = 1
    if run_no < 1:
        raise ValueError("world cursor requires run>=1")
    cursor["run"] = run_no
    cursor["worldline"] = str(cursor.get("worldline") or "WMAIN")
    cursor["ch_anchor"] = int(cursor.get("ch_anchor", 0) or 0)
    cursor["world_clock"] = str(cursor.get("world_clock") or "00:00")
    return cursor


@dataclass
class WorldCursorState:
    _cursor: dict[str, Any]
    _events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_cursor(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        run: int,
    ) -> "WorldCursorState":
        return cls(_normalize(raw, run=run))

    @classmethod
    def from_saved(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_cursor: Mapping[str, Any] | None,
        run: int,
    ) -> "WorldCursorState":
        data = dict(raw or {})
        if data.get("schema_version") == WORLD_CURSOR_STATE_SCHEMA:
            cursor = data.get("cursor") if isinstance(data.get("cursor"), Mapping) else legacy_cursor
            events = [
                copy.deepcopy(dict(item))
                for item in data.get("events", ())
                if isinstance(item, Mapping)
            ]
            return cls(_normalize(cursor, run=run), events)
        return cls.from_cursor(legacy_cursor, run=run)

    def cursor(self) -> dict[str, Any]:
        return copy.deepcopy(self._cursor)

    def events(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(item) for item in self._events]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORLD_CURSOR_STATE_SCHEMA,
            "cursor": self.cursor(),
            "events": self.events(),
        }

    def replace(
        self,
        raw: Mapping[str, Any],
        *,
        run: int,
        source_kind: str,
    ) -> dict[str, Any]:
        source = str(source_kind or "").strip()
        if not source:
            raise ValueError("world cursor replace requires source_kind")
        before = self.cursor()
        self._cursor = _normalize(raw, run=run)
        self._events.append({
            "kind": "replace",
            "source_kind": source,
            "before": before,
            "after": self.cursor(),
        })
        return self.cursor()

    def advance(
        self,
        *,
        run: int,
        ch_anchor: int,
        world_clock: str,
        source_kind: str,
    ) -> dict[str, Any]:
        source = str(source_kind or "").strip()
        if not source:
            raise ValueError("world cursor advance requires source_kind")
        before = self.cursor()
        advanced = world_calendar.advance(
            before,
            ch_anchor=int(ch_anchor),
            world_clock=str(world_clock),
        )
        self._cursor = _normalize(advanced, run=run)
        self._events.append({
            "kind": "advance",
            "source_kind": source,
            "before": before,
            "after": self.cursor(),
        })
        return self.cursor()
