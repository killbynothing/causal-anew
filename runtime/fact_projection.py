"""P2c compatibility projection for branch markers and scene receipts.

This state is not a new world authority. It may only project already-observed
or already-authorized facts into legacy branch_progress / scene_receipts views.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import canonical_payload_hash

FACT_PROJECTION_SCHEMA = "free_stage.fact_projection.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class RuntimeFactProjection:
    _branches: list[str] = field(default_factory=list)
    branch_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    _scene_receipts: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = FACT_PROJECTION_SCHEMA

    @classmethod
    def empty(cls) -> "RuntimeFactProjection":
        return cls()

    @classmethod
    def from_snapshot(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_branches: Sequence[Any] = (),
        legacy_scene_receipts: Sequence[Any] = (),
    ) -> "RuntimeFactProjection":
        if raw is None:
            state = cls.empty()
            state.replace_branches(
                legacy_branches,
                source_kind="legacy_snapshot",
                source_ref="free_stage.session.v1:branch_progress",
                turn=0,
                scene_id="",
            )
            for item in legacy_scene_receipts:
                if not isinstance(item, Mapping):
                    continue
                state.record_scene_receipt(
                    _text(item.get("fact_id")),
                    owner=_text(item.get("owner")) or "legacy",
                    turn=int(item.get("turn", 0) or 0),
                    scene_id=_text(item.get("scene_id")),
                    source_input=_text(item.get("source_input")),
                    source_kind=_text(item.get("source_kind")) or "legacy_snapshot",
                )
            return state
        if not isinstance(raw, Mapping):
            raise ValueError("fact_projection must be an object")
        if raw.get("schema_version") != FACT_PROJECTION_SCHEMA:
            raise ValueError(f"unsupported fact_projection schema: {raw.get('schema_version')}")
        branches = [_text(x) for x in (raw.get("branch_progress") or []) if _text(x)]
        sources_raw = raw.get("branch_sources") or {}
        if not isinstance(sources_raw, Mapping):
            raise ValueError("fact_projection.branch_sources must be an object")
        sources = {
            _text(k): dict(v)
            for k, v in sources_raw.items()
            if _text(k) and isinstance(v, Mapping)
        }
        receipts = [
            dict(item)
            for item in (raw.get("scene_receipts") or [])
            if isinstance(item, Mapping)
        ]
        state = cls(
            _branches=list(dict.fromkeys(branches)),
            branch_sources=sources,
            _scene_receipts=receipts,
        )
        for branch in state._branches:
            state.branch_sources.setdefault(
                branch,
                state._make_branch_source(
                    branch,
                    source_kind="legacy_snapshot",
                    source_ref="fact_projection:missing_source",
                    turn=0,
                    scene_id="",
                ),
            )
        return state

    @property
    def branch_progress(self) -> list[str]:
        return list(self._branches)

    @property
    def scene_receipts(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._scene_receipts]

    def _make_branch_source(
        self,
        fact_id: str,
        *,
        source_kind: str,
        source_ref: str,
        turn: int,
        scene_id: str,
    ) -> dict[str, Any]:
        payload = {
            "fact_id": fact_id,
            "source_kind": _text(source_kind) or "unspecified",
            "source_ref": _text(source_ref),
            "turn": int(turn),
            "scene_id": _text(scene_id),
        }
        return {
            "projection_id": f"branch:{canonical_payload_hash(payload)}",
            **payload,
        }

    def add_branch(
        self,
        fact_id: str,
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
        scene_id: str = "",
    ) -> bool:
        fact = _text(fact_id)
        if not fact:
            raise ValueError("branch projection requires fact_id")
        if fact in self._branches:
            return False
        self._branches.append(fact)
        self.branch_sources[fact] = self._make_branch_source(
            fact,
            source_kind=source_kind,
            source_ref=source_ref,
            turn=turn,
            scene_id=scene_id,
        )
        return True

    def remove_ids(self, ids: Sequence[Any]) -> list[str]:
        targets = {_text(item) for item in ids if _text(item)}
        removed = [item for item in self._branches if item in targets]
        if removed:
            self._branches = [item for item in self._branches if item not in targets]
            for item in removed:
                self.branch_sources.pop(item, None)
        return removed

    def remove_prefixes(self, prefixes: Sequence[str]) -> list[str]:
        prefixes_tuple = tuple(_text(p) for p in prefixes if _text(p))
        removed = [
            item for item in self._branches
            if prefixes_tuple and item.startswith(prefixes_tuple)
        ]
        if removed:
            self.remove_ids(removed)
        return removed

    def replace_branches(
        self,
        values: Sequence[Any],
        *,
        source_kind: str,
        source_ref: str = "",
        turn: int = 0,
        scene_id: str = "",
    ) -> None:
        self._branches = []
        self.branch_sources = {}
        for raw in values:
            fact = _text(raw)
            if fact:
                self.add_branch(
                    fact,
                    source_kind=source_kind,
                    source_ref=source_ref,
                    turn=turn,
                    scene_id=scene_id,
                )

    def record_scene_receipt(
        self,
        fact_id: str,
        *,
        owner: str,
        turn: int,
        scene_id: str,
        source_input: str = "",
        source_kind: str = "player_input",
    ) -> bool:
        fact = _text(fact_id)
        scene = _text(scene_id)
        if not fact:
            raise ValueError("scene receipt requires fact_id")
        if any(
            _text(item.get("scene_id")) == scene and _text(item.get("fact_id")) == fact
            for item in self._scene_receipts
        ):
            return False
        payload = {
            "scene_id": scene,
            "fact_id": fact,
            "owner": _text(owner),
            "turn": int(turn),
            "source_input": _text(source_input),
            "source_kind": _text(source_kind),
        }
        self._scene_receipts.append({
            "receipt_id": f"scene:{canonical_payload_hash(payload)}",
            **payload,
        })
        return True

    def replace_scene_receipts(
        self,
        values: Sequence[Any],
        *,
        source_kind: str = "compat_assignment",
    ) -> None:
        self._scene_receipts = []
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            self.record_scene_receipt(
                _text(raw.get("fact_id")),
                owner=_text(raw.get("owner")) or "legacy",
                turn=int(raw.get("turn", 0) or 0),
                scene_id=_text(raw.get("scene_id")),
                source_input=_text(raw.get("source_input")),
                source_kind=_text(raw.get("source_kind")) or source_kind,
            )

    def reset(self) -> None:
        self._branches = []
        self.branch_sources = {}
        self._scene_receipts = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "branch_progress": self.branch_progress,
            "branch_sources": {
                key: dict(value) for key, value in self.branch_sources.items()
            },
            "scene_receipts": self.scene_receipts,
        }
