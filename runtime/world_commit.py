"""P2a single submission boundary for replayable world facts.

This module owns commits into the session world-transaction ledger. It does not
decide story semantics; callers must submit an already-authorized fact.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from runtime import world_calendar
from runtime.causal_protocol import (
    ReceiptConflict,
    ReceiptEnvelope,
    RuntimeScope,
    canonical_payload_hash,
    commit_batch_id,
)

WORLD_COMMIT_SCHEMA = "free_stage.world_commit.v1"
BRANCH_FACT_SCHEMA = "free_stage.branch_fact.v1"

# P2c has migrated every fact family that P0a assigned to WorldCommit.
P2A_WORLD_MIGRATION_DEBT: tuple[str, ...] = ()


class WorldCursorState:
    """P2c owner for run/worldline/time coordinates."""

    def __init__(self, cursor: Mapping[str, Any], *, run_no: int) -> None:
        self._cursor: dict[str, Any] = {}
        self.replace(cursor, run_no=run_no)

    def view(self) -> dict[str, Any]:
        return copy.deepcopy(self._cursor)

    def replace(self, cursor: Mapping[str, Any], *, run_no: int | None = None) -> dict[str, Any]:
        raw = copy.deepcopy(dict(cursor or {}))
        run = int(run_no if run_no is not None else raw.get("run", 0) or 0)
        if run < 1:
            raise ValueError("world cursor requires run>=1")
        raw["run"] = run
        raw["worldline"] = str(raw.get("worldline") or "WMAIN")
        raw["ch_anchor"] = int(raw.get("ch_anchor", 0) or 0)
        raw["world_clock"] = str(raw.get("world_clock") or "00:00")
        self._cursor = raw
        return self.view()

    def reset(self, cursor: Mapping[str, Any], *, run_no: int) -> dict[str, Any]:
        return self.replace(cursor, run_no=run_no)

    def set_run(self, run_no: int) -> dict[str, Any]:
        run = int(run_no)
        if run < 1:
            raise ValueError("world cursor requires run>=1")
        self._cursor = world_calendar.with_run(self._cursor, run)
        self._cursor.setdefault("worldline", "WMAIN")
        return self.view()

    def advance(
        self,
        *,
        ch_anchor: int | None = None,
        world_clock: str | None = None,
        run_no: int | None = None,
    ) -> dict[str, Any]:
        new = world_calendar.advance(
            self._cursor,
            ch_anchor=ch_anchor,
            world_clock=world_clock,
        )
        return self.replace(
            new,
            run_no=int(run_no) if run_no is not None else int(self._cursor["run"]),
        )


class WorldCommitState:
    """P2c-owned mutable ledger with copy-only compatibility views."""

    def __init__(
        self,
        *,
        branch_progress: Sequence[str] = (),
        branch_fact_events: Sequence[Mapping[str, Any]] = (),
        scene_receipts: Sequence[Mapping[str, Any]] = (),
        world_transactions: Mapping[str, Mapping[str, Any]] | None = None,
        causal_receipts: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._branch_progress = []
        for item in branch_progress:
            fact = _text(item)
            if fact and fact not in self._branch_progress:
                self._branch_progress.append(fact)
        self._branch_fact_events = [
            copy.deepcopy(dict(item))
            for item in branch_fact_events
            if isinstance(item, Mapping)
        ]
        self._scene_receipts = [
            copy.deepcopy(dict(item))
            for item in scene_receipts
            if isinstance(item, Mapping)
        ]
        self._world_transactions = {
            str(key): copy.deepcopy(dict(value))
            for key, value in dict(world_transactions or {}).items()
            if str(key).strip() and isinstance(value, Mapping)
        }
        self._causal_receipts = [
            copy.deepcopy(dict(item))
            for item in causal_receipts
            if isinstance(item, Mapping)
        ]

    @classmethod
    def from_legacy(cls, raw: Mapping[str, Any]) -> "WorldCommitState":
        return cls(
            branch_progress=(
                raw.get("branch_progress")
                if isinstance(raw.get("branch_progress"), (list, tuple))
                else ()
            ),
            branch_fact_events=(
                raw.get("branch_fact_events")
                if isinstance(raw.get("branch_fact_events"), (list, tuple))
                else ()
            ),
            scene_receipts=(
                raw.get("scene_receipts")
                if isinstance(raw.get("scene_receipts"), (list, tuple))
                else ()
            ),
            world_transactions=(
                raw.get("world_transactions")
                if isinstance(raw.get("world_transactions"), Mapping)
                else {}
            ),
            causal_receipts=(
                raw.get("causal_receipts")
                if isinstance(raw.get("causal_receipts"), (list, tuple))
                else ()
            ),
        )

    def reset(self) -> None:
        self._branch_progress.clear()
        self._branch_fact_events.clear()
        self._scene_receipts.clear()
        self._world_transactions.clear()
        self._causal_receipts.clear()

    def branch_progress_view(self) -> list[str]:
        return list(self._branch_progress)

    def branch_fact_events_view(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._branch_fact_events)

    def replace_branch_snapshot(self, facts: Sequence[str]) -> list[str]:
        """Legacy/migration reader only. New runtime writes use branch events."""
        current: list[str] = []
        for item in facts:
            fact = _text(item)
            if fact and fact not in current:
                current.append(fact)
        self._branch_progress = current
        return self.branch_progress_view()

    def _apply_branch_event(
        self,
        *,
        scope: RuntimeScope,
        request_id: str,
        operation: str,
        fact_id: str,
        source_kind: str,
        owner: str,
        scene_id: str,
        turn: int,
        source_refs: Sequence[str] = (),
    ) -> bool:
        fact = _text(fact_id)
        op = _text(operation)
        if op not in {"assert", "retract"}:
            raise ValueError(f"invalid branch fact operation: {op}")
        if not fact:
            raise ValueError("branch fact requires fact_id")
        if int(scope.run) < 1:
            raise ValueError("branch fact requires run>=1")

        if op == "assert" and fact in self._branch_progress:
            return False
        if op == "retract" and fact not in self._branch_progress:
            return False

        base_request = _text(request_id) or f"branch:{source_kind}:{turn}"
        scoped_request = f"{base_request}:{op}:{fact}"
        payload = {
            "operation": op,
            "fact_id": fact,
            "source_kind": _text(source_kind) or "runtime",
            "owner": _text(owner) or "world",
            "scene_id": _text(scene_id),
            "turn": int(turn),
        }
        receipt = ReceiptEnvelope.for_payload(
            receipt_id=(
                "branch:"
                + canonical_payload_hash({
                    "scope": scope.to_dict(),
                    "request_id": scoped_request,
                    "operation": op,
                    "fact_id": fact,
                })
            ),
            request_id=scoped_request,
            turn_id=f"turn:{int(turn)}",
            sequence=0,
            scope=scope,
            producer="WorldCommit.BranchFact",
            source_refs=tuple(_text(item) for item in source_refs if _text(item)),
            visibility="public",
            base_revision=0,
            payload=payload,
        )
        event = {
            "schema_version": BRANCH_FACT_SCHEMA,
            **payload,
            "receipt": receipt.to_dict(),
        }
        receipt_id = receipt.receipt_id
        for existing in self._branch_fact_events:
            existing_receipt = (
                existing.get("receipt")
                if isinstance(existing.get("receipt"), Mapping)
                else {}
            )
            if _text(existing_receipt.get("receipt_id")) != receipt_id:
                continue
            if canonical_payload_hash(existing) != canonical_payload_hash(event):
                raise ReceiptConflict(
                    f"branch receipt id reused with different payload: {receipt_id}"
                )
            return False

        self._branch_fact_events.append(event)
        if op == "assert":
            self._branch_progress.append(fact)
        else:
            self._branch_progress = [
                item for item in self._branch_progress if item != fact
            ]
        return True

    def assert_branch_fact(self, **kwargs: Any) -> bool:
        return self._apply_branch_event(operation="assert", **kwargs)

    def retract_branch_fact(self, **kwargs: Any) -> bool:
        return self._apply_branch_event(operation="retract", **kwargs)

    def scene_receipts_view(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._scene_receipts)

    def world_transactions_view(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._world_transactions)

    def causal_receipts_view(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._causal_receipts)

    def append_scene_receipt(self, record: Mapping[str, Any]) -> bool:
        row = copy.deepcopy(dict(record))
        scene_id = _text(row.get("scene_id"))
        fact_id = _text(row.get("fact_id"))
        if not scene_id or not fact_id:
            raise ValueError("scene receipt requires scene_id/fact_id")
        if any(
            _text(item.get("scene_id")) == scene_id
            and _text(item.get("fact_id")) == fact_id
            for item in self._scene_receipts
        ):
            return False
        self._scene_receipts.append(row)
        return True

    def append_causal_receipt(self, record: Mapping[str, Any]) -> bool:
        row = copy.deepcopy(dict(record))
        receipt_id = _text(row.get("receipt_id"))
        if not receipt_id:
            raise ValueError("causal receipt requires receipt_id")
        for existing in self._causal_receipts:
            if _text(existing.get("receipt_id")) != receipt_id:
                continue
            if canonical_payload_hash(existing) != canonical_payload_hash(row):
                raise ReceiptConflict(
                    f"causal receipt id reused with different payload: {receipt_id}"
                )
            return False
        self._causal_receipts.append(row)
        return True

    def commit_fact(self, **kwargs: Any) -> "WorldCommitResult":
        return commit_world_fact(self._world_transactions, **kwargs)

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        row = self._world_transactions.get(_text(transaction_id))
        return copy.deepcopy(row) if isinstance(row, dict) else None


@dataclass(frozen=True)
class WorldCommitResult:
    record: dict[str, Any]
    committed: bool


@dataclass(frozen=True)
class WorldBatchResult:
    batch_id: str
    records: tuple[dict[str, Any], ...]
    committed_ids: tuple[str, ...]
    existing_ids: tuple[str, ...]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _core(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "transaction_id": _text(record.get("transaction_id")),
        "kind": _text(record.get("kind")),
        "outcome": _text(record.get("outcome")),
        "owner": _text(record.get("owner")),
        "scene_id": _text(record.get("scene_id")),
        "turn": int(record.get("turn", 0) or 0),
        "worldline": _text(record.get("worldline")),
        "run": int(record.get("run", 0) or 0),
        "public_effect": _text(record.get("public_effect")),
    }


def _build_candidate(
    *,
    scope: RuntimeScope,
    request_id: str,
    turn_id: str,
    batch_id: str,
    sequence: int,
    fact: Mapping[str, Any],
    base_revision: int,
) -> dict[str, Any]:
    tx_id = _text(fact.get("transaction_id"))
    kind = _text(fact.get("kind"))
    outcome = _text(fact.get("outcome"))
    owner = _text(fact.get("owner"))
    turn = int(fact.get("turn", 0) or 0)
    if not tx_id or not kind or not outcome or not owner:
        raise ValueError("world commit requires transaction/kind/outcome/owner")
    if turn < 0:
        raise ValueError("world commit turn must be >= 0")

    payload = {
        "transaction_id": tx_id,
        "kind": kind,
        "outcome": outcome,
        "owner": owner,
        "scene_id": _text(fact.get("scene_id")),
        "turn": turn,
        "worldline": scope.worldline,
        "run": int(scope.run),
        "public_effect": _text(fact.get("public_effect")),
    }
    refs = fact.get("source_refs") or ()
    if not isinstance(refs, (list, tuple)):
        raise ValueError("world commit source_refs must be list/tuple")
    receipt = ReceiptEnvelope.for_payload(
        receipt_id=f"world:{canonical_payload_hash({'scope': scope.to_dict(), 'transaction_id': tx_id})}",
        request_id=request_id,
        turn_id=_text(turn_id) or f"turn:{turn}",
        sequence=int(sequence),
        scope=scope,
        producer="WorldCommit",
        source_refs=tuple(_text(item) for item in refs if _text(item)),
        visibility="public",
        base_revision=int(base_revision),
        payload=payload,
    )
    return {
        "schema_version": WORLD_COMMIT_SCHEMA,
        **payload,
        "request_id": request_id,
        "batch_id": batch_id,
        "receipt": receipt.to_dict(),
    }


def commit_world_batch(
    ledger: MutableMapping[str, dict[str, Any]],
    *,
    scope: RuntimeScope,
    request_id: str,
    turn_id: str,
    facts: Sequence[Mapping[str, Any]],
    batch_index: int = 0,
    base_revision: int = 0,
) -> WorldBatchResult:
    """Validate the entire batch first, then mutate the ledger once.

    Any conflict aborts before the first new fact is inserted. Retries are
    idempotent only when fact and provenance are identical.
    """
    req_id = _text(request_id)
    if not req_id:
        raise ValueError("world commit batch requires request_id")
    if int(scope.run) < 1:
        raise ValueError("world commit requires run>=1")
    if not facts:
        raise ValueError("world commit batch requires at least one fact")

    batch_id = commit_batch_id(scope, request_id=req_id, batch_index=int(batch_index))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sequence, fact in enumerate(facts):
        candidate = _build_candidate(
            scope=scope,
            request_id=req_id,
            turn_id=turn_id,
            batch_id=batch_id,
            sequence=sequence,
            fact=fact,
            base_revision=base_revision,
        )
        tx_id = candidate["transaction_id"]
        if tx_id in seen:
            raise ReceiptConflict(f"duplicate transaction id inside batch: {tx_id}")
        seen.add(tx_id)
        candidates.append(candidate)

    resolved: list[dict[str, Any]] = []
    new_records: list[dict[str, Any]] = []
    committed_ids: list[str] = []
    existing_ids: list[str] = []

    # Phase 1: validate every candidate without mutating ledger.
    for candidate in candidates:
        tx_id = candidate["transaction_id"]
        existing = ledger.get(tx_id)
        if existing is None:
            resolved.append(candidate)
            new_records.append(candidate)
            committed_ids.append(tx_id)
            continue
        if _core(existing) != _core(candidate):
            raise ReceiptConflict(f"world transaction id reused with different fact: {tx_id}")
        if existing.get("schema_version") != WORLD_COMMIT_SCHEMA:
            resolved.append(dict(existing))
            existing_ids.append(tx_id)
            continue
        if canonical_payload_hash(existing) != canonical_payload_hash(candidate):
            raise ReceiptConflict(f"world transaction id reused with different provenance: {tx_id}")
        resolved.append(dict(existing))
        existing_ids.append(tx_id)

    # Phase 2: all validation passed; now publish the new facts.
    for candidate in new_records:
        ledger[candidate["transaction_id"]] = candidate

    return WorldBatchResult(
        batch_id=batch_id,
        records=tuple(dict(item) for item in resolved),
        committed_ids=tuple(committed_ids),
        existing_ids=tuple(existing_ids),
    )


def commit_world_fact(
    ledger: MutableMapping[str, dict[str, Any]],
    *,
    scope: RuntimeScope,
    request_id: str,
    turn_id: str,
    transaction_id: str,
    kind: str,
    outcome: str,
    owner: str,
    scene_id: str,
    turn: int,
    public_effect: str = "",
    source_refs: Sequence[str] = (),
    base_revision: int = 0,
) -> WorldCommitResult:
    """Single-fact compatibility facade over the atomic batch boundary."""
    result = commit_world_batch(
        ledger,
        scope=scope,
        request_id=request_id,
        turn_id=turn_id,
        facts=(
            {
                "transaction_id": transaction_id,
                "kind": kind,
                "outcome": outcome,
                "owner": owner,
                "scene_id": scene_id,
                "turn": int(turn),
                "public_effect": public_effect,
                "source_refs": tuple(source_refs),
            },
        ),
        batch_index=0,
        base_revision=base_revision,
    )
    tx_id = _text(transaction_id)
    return WorldCommitResult(
        record=dict(result.records[0]),
        committed=tx_id in result.committed_ids,
    )
