"""P2c single mutable owner for the persisted world cursor.

Normal scene progression delegates to world_calendar.advance so monotonic-time
rules stay where they already live. Explicit load/reset/flashback replacement
is preserved as a sourced compatibility operation; this module does not decide
whether flashbacks should eventually become scene-local time.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from runtime import world_calendar

WORLD_CURSOR_STATE_SCHEMA = "free_stage.world_cursor_state.v1"


def _normalize(cursor: Mapping[str, Any] | None, *, run_no: int) -> dict[str, Any]:
    raw = dict(cursor or {})
    try:
        ch_anchor = int(raw.get("ch_anchor", 0) or 0)
    except (TypeError, ValueError):
        ch_anchor = 0
    clock = str(raw.get("world_clock") or raw.get("clock") or "00:00")
    worldline = str(raw.get("worldline") or "WMAIN")
    return {
        "ch_anchor": ch_anchor,
        "world_clock": clock,
        "run": int(run_no),
        "worldline": worldline,
    }


class WorldCursorState:
    """Single cursor owner; all exposed cursor values are defensive copies."""

    def __init__(
        self,
        cursor: Mapping[str, Any] | None,
        *,
        run_no: int,
        revision: int = 0,
        last_source: Mapping[str, Any] | None = None,
    ) -> None:
        self._cursor = _normalize(cursor, run_no=run_no)
        self._revision = max(0, int(revision or 0))
        self._last_source = copy.deepcopy(dict(last_source or {}))

    @classmethod
    def empty(
        cls,
        cursor: Mapping[str, Any] | None,
        *,
        run_no: int,
        source_kind: str = "session_init",
        source_ref: str = "",
    ) -> "WorldCursorState":
        return cls(
            cursor,
            run_no=run_no,
            last_source={"kind": str(source_kind), "ref": str(source_ref)},
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Any,
        *,
        legacy_cursor: Mapping[str, Any] | None,
        run_no: int,
    ) -> "WorldCursorState":
        if (
            isinstance(snapshot, Mapping)
            and snapshot.get("schema_version") == WORLD_CURSOR_STATE_SCHEMA
        ):
            cursor = snapshot.get("cursor")
            if not isinstance(cursor, Mapping):
                raise ValueError("world_cursor_state.cursor must be an object")
            return cls(
                cursor,
                run_no=run_no,
                revision=int(snapshot.get("revision", 0) or 0),
                last_source=(
                    snapshot.get("last_source")
                    if isinstance(snapshot.get("last_source"), Mapping)
                    else None
                ),
            )
        return cls(
            legacy_cursor,
            run_no=run_no,
            last_source={"kind": "legacy_snapshot", "ref": "world_cursor"},
        )

    @property
    def cursor(self) -> dict[str, Any]:
        return copy.deepcopy(self._cursor)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def last_source(self) -> dict[str, Any]:
        return copy.deepcopy(self._last_source)

    def _commit(
        self,
        candidate: Mapping[str, Any],
        *,
        run_no: int,
        source_kind: str,
        source_ref: str,
    ) -> bool:
        normalized = _normalize(candidate, run_no=run_no)
        if normalized == self._cursor:
            return False
        self._cursor = normalized
        self._revision += 1
        self._last_source = {
            "kind": str(source_kind or "unknown"),
            "ref": str(source_ref or ""),
        }
        return True

    def replace(
        self,
        cursor: Mapping[str, Any] | None,
        *,
        run_no: int,
        source_kind: str,
        source_ref: str = "",
    ) -> bool:
        return self._commit(
            dict(cursor or {}),
            run_no=run_no,
            source_kind=source_kind,
            source_ref=source_ref,
        )

    def advance(
        self,
        *,
        ch_anchor: int | None,
        world_clock: str | None,
        run_no: int,
        source_kind: str,
        source_ref: str = "",
    ) -> bool:
        candidate = world_calendar.advance(
            self._cursor,
            ch_anchor=ch_anchor,
            world_clock=world_clock,
        )
        return self._commit(
            candidate,
            run_no=run_no,
            source_kind=source_kind,
            source_ref=source_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORLD_CURSOR_STATE_SCHEMA,
            "revision": self._revision,
            "last_source": self.last_source,
            "cursor": self.cursor,
        }
