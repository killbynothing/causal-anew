"""P2c world-coordinate storage authority.

The reducer owns only the current cursor projection. ExitPolicy/transition
logic decides where the scene goes; world_calendar computes candidate time/
chapter movement. Callers receive copies so dict mutation cannot bypass this
authority.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


class WorldCursorReducer:
    def __init__(
        self,
        initial: Mapping[str, Any] | None = None,
        *,
        run_no: int = 1,
    ) -> None:
        self._write_world_cursor(initial or {}, run_no=run_no)

    @staticmethod
    def _normalize(
        values: Mapping[str, Any] | None,
        *,
        run_no: int,
        fallback_worldline: str = "WMAIN",
    ) -> dict[str, Any]:
        cursor = copy.deepcopy(dict(values or {}))
        try:
            run = int(run_no or cursor.get("run") or 1)
        except (TypeError, ValueError):
            run = 1
        if run < 1:
            run = 1
        worldline = str(cursor.get("worldline") or fallback_worldline or "WMAIN").strip()
        cursor["run"] = run
        cursor["worldline"] = worldline or "WMAIN"
        return cursor

    def _write_world_cursor(
        self,
        values: Mapping[str, Any] | None,
        *,
        run_no: int,
        fallback_worldline: str = "WMAIN",
    ) -> None:
        """Sole production writer for semantic world_cursor."""
        self.world_cursor = self._normalize(
            values,
            run_no=run_no,
            fallback_worldline=fallback_worldline,
        )

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.world_cursor)

    def replace(
        self,
        values: Mapping[str, Any] | None,
        *,
        run_no: int,
        fallback_worldline: str = "WMAIN",
    ) -> dict[str, Any]:
        self._write_world_cursor(
            values,
            run_no=run_no,
            fallback_worldline=fallback_worldline,
        )
        return self.snapshot()
