"""P2c Beat completion authority.

All production writes to the semantic `completed` fact must pass through the
single private writer `BeatReducer._write_completed`. Callers receive copies,
so list mutation cannot bypass the reducer.
"""
from __future__ import annotations

from collections.abc import Iterable


class BeatReducer:
    def __init__(self, initial: Iterable[str] = ()) -> None:
        self._write_completed(initial)

    @staticmethod
    def _normalize(values: Iterable[str]) -> list[str]:
        return [str(value) for value in values if str(value).strip()]

    def _write_completed(self, values: Iterable[str]) -> None:
        """The sole production writer for the semantic `completed` fact."""
        self.completed = self._normalize(values)

    def snapshot(self) -> list[str]:
        return list(self.completed)

    def replace(self, values: Iterable[str]) -> list[str]:
        self._write_completed(values)
        return self.snapshot()

    def clear(self) -> None:
        self._write_completed(())

    def complete(self, beat_id: str) -> bool:
        beat = str(beat_id or "").strip()
        if not beat or beat in self.completed:
            return False
        self._write_completed([*self.completed, beat])
        return True

    def extend(self, beat_ids: Iterable[str]) -> list[str]:
        """Preserve legacy extend ordering/duplicates while centralizing writes."""
        incoming = self._normalize(beat_ids)
        if not incoming:
            return []
        self._write_completed([*self.completed, *incoming])
        return incoming
