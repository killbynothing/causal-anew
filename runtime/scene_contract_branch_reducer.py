"""P2c reducer for the legacy scene-contract path ledger.

This is intentionally distinct from FreeStage branch_progress. The legacy
scene runtime stores {node_id: [path_id, ...]}, while FreeStage stores a flat
list of world markers.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Iterable
from typing import Any


class SceneContractBranchReducer:
    def __init__(self, initial: Mapping[str, Iterable[str]] | None = None) -> None:
        self._write_contract_branch_progress(initial or {})

    @staticmethod
    def _normalize(raw: Mapping[str, Iterable[str]] | None) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for node_id, values in dict(raw or {}).items():
            node = str(node_id or "").strip()
            if not node:
                continue
            unique = sorted({str(item) for item in (values or []) if str(item).strip()})
            if unique:
                out[node] = unique
        return out

    def _write_contract_branch_progress(
        self,
        values: Mapping[str, Iterable[str]] | None,
    ) -> None:
        """Sole production writer for legacy contract_branch_progress."""
        self.contract_branch_progress = self._normalize(values)

    def snapshot(self) -> dict[str, list[str]]:
        return copy.deepcopy(self.contract_branch_progress)

    def replace(self, values: Mapping[str, Iterable[str]] | None) -> dict[str, list[str]]:
        self._write_contract_branch_progress(values)
        return self.snapshot()

    def add_paths(
        self,
        node_id: str,
        path_ids: Iterable[str],
        *,
        valid_paths: Iterable[str],
    ) -> list[str]:
        node = str(node_id or "").strip()
        allowed = {str(item) for item in valid_paths if str(item).strip()}
        if not node or not allowed:
            return []
        current = set(self.contract_branch_progress.get(node, []))
        added: list[str] = []
        for raw in path_ids:
            path = str(raw or "").strip()
            if path in allowed and path not in current:
                current.add(path)
                added.append(path)
        if added:
            updated = self.snapshot()
            updated[node] = sorted(current)
            self._write_contract_branch_progress(updated)
        return added

    def active_paths(self, node_id: str) -> list[str]:
        return list(self.contract_branch_progress.get(str(node_id or "").strip(), []))
