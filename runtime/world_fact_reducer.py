"""P2c compatibility projections for session world facts.

This reducer is the only FreeStageSession-side writer for branch_progress and
scene_receipts. It does not decide whether a world fact is true; upstream
PlayerAction/WorldCommit/scene evidence still owns that decision.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from typing import Any


class WorldFactReducer:
    def __init__(
        self,
        branch_progress: Iterable[str] = (),
        scene_receipts: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self._write_branch_progress(branch_progress)
        self._write_scene_receipts(scene_receipts)

    @staticmethod
    def _normalize_branch(values: Iterable[str]) -> list[str]:
        return [str(value) for value in values if str(value).strip()]

    def _write_branch_progress(self, values: Iterable[str]) -> None:
        self.branch_progress = self._normalize_branch(values)

    def _write_scene_receipts(self, values: Iterable[Mapping[str, Any]]) -> None:
        self.scene_receipts = [
            copy.deepcopy(dict(value))
            for value in values
            if isinstance(value, Mapping)
        ]

    def branch_snapshot(self) -> list[str]:
        return list(self.branch_progress)

    def receipt_snapshot(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(item) for item in self.scene_receipts]

    def replace_branch(self, values: Iterable[str]) -> list[str]:
        self._write_branch_progress(values)
        return self.branch_snapshot()

    def replace_receipts(self, values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        self._write_scene_receipts(values)
        return self.receipt_snapshot()

    def clear(self) -> None:
        self._write_branch_progress(())
        self._write_scene_receipts(())

    def add_branch(self, fact_id: str) -> bool:
        fact = str(fact_id or "").strip()
        if not fact or fact in self.branch_progress:
            return False
        self._write_branch_progress([*self.branch_progress, fact])
        return True

    def filter_branch(self, keep: Callable[[str], bool]) -> list[str]:
        kept = [item for item in self.branch_progress if keep(item)]
        if kept != self.branch_progress:
            self._write_branch_progress(kept)
        return self.branch_snapshot()

    def append_scene_receipt(
        self,
        *,
        scene_id: str,
        fact_id: str,
        owner: str,
        turn: int,
        source_input: str = "",
        source_kind: str = "player_input",
    ) -> bool:
        scene = str(scene_id or "").strip()
        fact = str(fact_id or "").strip()
        if not fact:
            return False
        if any(
            item.get("scene_id") == scene and item.get("fact_id") == fact
            for item in self.scene_receipts
        ):
            return False
        row = {
            "scene_id": scene,
            "fact_id": fact,
            "owner": str(owner or ""),
            "turn": int(turn),
            "source_input": str(source_input or ""),
            "source_kind": str(source_kind or ""),
        }
        self._write_scene_receipts([*self.scene_receipts, row])
        return True
