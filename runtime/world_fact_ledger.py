"""P2c append-only event ledger for branch facts and scene receipts.

The event history is authoritative. branch_progress is the folded current view;
scene_receipts is a historical evidence view. Retraction never deletes evidence.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import ReceiptConflict, canonical_payload_hash

WORLD_FACT_LEDGER_SCHEMA = "free_stage.world_fact_ledger.v1"


def _clean(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


@dataclass
class WorldFactLedger:
    _legacy_branch: list[str] = field(default_factory=list)
    _legacy_receipts: list[dict[str, Any]] = field(default_factory=list)
    _events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_saved(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        legacy_branch: Sequence[Any] | None = None,
        legacy_receipts: Sequence[Mapping[str, Any]] | None = None,
    ) -> "WorldFactLedger":
        data = dict(raw or {})
        if data.get("schema_version") == WORLD_FACT_LEDGER_SCHEMA:
            return cls(
                _clean(data.get("legacy_branch")),
                [
                    copy.deepcopy(dict(item))
                    for item in data.get("legacy_receipts", [])
                    if isinstance(item, Mapping)
                ],
                [
                    copy.deepcopy(dict(item))
                    for item in data.get("events", [])
                    if isinstance(item, Mapping)
                ],
            )
        return cls(
            _clean(legacy_branch),
            [
                copy.deepcopy(dict(item))
                for item in (legacy_receipts or ())
                if isinstance(item, Mapping)
            ],
            [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORLD_FACT_LEDGER_SCHEMA,
            "legacy_branch": list(self._legacy_branch),
            "legacy_receipts": [copy.deepcopy(item) for item in self._legacy_receipts],
            "events": [copy.deepcopy(item) for item in self._events],
        }

    def reset(self) -> None:
        self._legacy_branch.clear()
        self._legacy_receipts.clear()
        self._events.clear()

    def events(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(item) for item in self._events]

    def active_branch(self) -> list[str]:
        active = list(self._legacy_branch)
        for event in self._events:
            if not bool(event.get("project_branch")):
                continue
            fact_id = str(event.get("fact_id") or "").strip()
            if not fact_id:
                continue
            if event.get("op") == "assert":
                if fact_id not in active:
                    active.append(fact_id)
            elif event.get("op") == "retract":
                active = [item for item in active if item != fact_id]
        return active

    def scene_receipts(self) -> list[dict[str, Any]]:
        out = [copy.deepcopy(item) for item in self._legacy_receipts]
        seen = {
            (str(item.get("scene_id") or ""), str(item.get("fact_id") or ""))
            for item in out
        }
        for event in self._events:
            if event.get("op") != "assert" or not bool(event.get("observable_receipt")):
                continue
            key = (str(event.get("scene_id") or ""), str(event.get("fact_id") or ""))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            out.append({
                "scene_id": key[0],
                "fact_id": key[1],
                "owner": str(event.get("owner") or ""),
                "turn": int(event.get("turn", 0) or 0),
                "source_input": str(event.get("source_input") or ""),
                "source_kind": str(event.get("source_kind") or ""),
                "event_id": str(event.get("event_id") or ""),
                "source_refs": list(event.get("source_refs") or []),
            })
        return out

    def _append(self, candidate: dict[str, Any]) -> bool:
        event_id = str(candidate.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("world fact event requires event_id")
        for existing in self._events:
            if str(existing.get("event_id") or "") != event_id:
                continue
            if canonical_payload_hash(existing) != canonical_payload_hash(candidate):
                raise ReceiptConflict(
                    f"world fact event id reused with different payload: {event_id}"
                )
            return False
        self._events.append(copy.deepcopy(candidate))
        return True

    def assert_fact(
        self,
        *,
        event_id: str,
        fact_id: str,
        scene_id: str,
        owner: str,
        turn: int,
        source_kind: str,
        source_input: str = "",
        source_refs: Sequence[str] = (),
        project_branch: bool = True,
        observable_receipt: bool = False,
    ) -> bool:
        fact = str(fact_id or "").strip()
        source = str(source_kind or "").strip()
        if not fact or not source:
            raise ValueError("world fact assertion requires fact_id/source_kind")
        before = fact in self.active_branch()
        self._append({
            "event_id": str(event_id),
            "op": "assert",
            "fact_id": fact,
            "scene_id": str(scene_id or "").strip(),
            "owner": str(owner or "").strip(),
            "turn": int(turn),
            "source_kind": source,
            "source_input": str(source_input or ""),
            "source_refs": [str(item) for item in source_refs if str(item).strip()],
            "project_branch": bool(project_branch),
            "observable_receipt": bool(observable_receipt),
        })
        return bool(project_branch and not before and fact in self.active_branch())

    def retract_fact(
        self,
        *,
        event_id: str,
        fact_id: str,
        scene_id: str,
        turn: int,
        source_kind: str,
    ) -> bool:
        fact = str(fact_id or "").strip()
        if not fact:
            return False
        before = fact in self.active_branch()
        self._append({
            "event_id": str(event_id),
            "op": "retract",
            "fact_id": fact,
            "scene_id": str(scene_id or "").strip(),
            "owner": "system",
            "turn": int(turn),
            "source_kind": str(source_kind or "branch_retract"),
            "source_input": "",
            "source_refs": [],
            "project_branch": True,
            "observable_receipt": False,
        })
        return bool(before and fact not in self.active_branch())
