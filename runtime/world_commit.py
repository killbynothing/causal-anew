"""P2a single submission boundary for replayable world facts.

This module owns commits into the session world-transaction ledger. It does not
decide story semantics; callers must submit an already-authorized fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from runtime.causal_protocol import (
    ReceiptConflict,
    ReceiptEnvelope,
    RuntimeScope,
    canonical_payload_hash,
    commit_batch_id,
)

WORLD_COMMIT_SCHEMA = "free_stage.world_commit.v1"

# P2a deliberately migrates the mature world_transactions append path first.
# These authority-map fact families remain compatibility writers until P2c.
P2A_WORLD_MIGRATION_DEBT = (
    # P2c has migrated Beat/fact/world/observation/physical projections.
    # World cursor remains the final WorldCommit migration family.
    "world_cursor",
)


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



class WorldLedgerState:
    """P2c owner for replayable world transactions and resolver receipts."""

    def __init__(
        self,
        transactions: Mapping[str, Mapping[str, Any]] | None = None,
        causal_receipts: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._transactions: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(transactions or {}).items()
            if str(key).strip() and isinstance(value, Mapping)
        }
        self._causal_receipts: list[dict[str, Any]] = [
            dict(item) for item in (causal_receipts or ()) if isinstance(item, Mapping)
        ]

    @classmethod
    def empty(cls) -> "WorldLedgerState":
        return cls()

    @classmethod
    def from_snapshot(
        cls,
        transactions: Any,
        causal_receipts: Any,
    ) -> "WorldLedgerState":
        tx = transactions if isinstance(transactions, Mapping) else {}
        receipts = causal_receipts if isinstance(causal_receipts, (list, tuple)) else ()
        return cls(tx, receipts)

    @property
    def transactions(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._transactions.items()}

    @property
    def causal_receipts(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._causal_receipts]

    def replace_transactions(self, values: Any) -> None:
        if not isinstance(values, Mapping):
            raise ValueError("world transactions replacement must be a mapping")
        self._transactions = {
            str(key): dict(value)
            for key, value in values.items()
            if str(key).strip() and isinstance(value, Mapping)
        }

    def replace_causal_receipts(self, values: Any) -> None:
        if not isinstance(values, (list, tuple)):
            raise ValueError("causal receipts replacement must be a list/tuple")
        self._causal_receipts = [
            dict(item) for item in values if isinstance(item, Mapping)
        ]

    def reset(self) -> None:
        self._transactions = {}
        self._causal_receipts = []

    def commit_fact(self, **kwargs: Any) -> WorldCommitResult:
        return commit_world_fact(self._transactions, **kwargs)

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        record = self._transactions.get(_text(transaction_id))
        return dict(record) if isinstance(record, dict) else None

    def record_causal_receipt(self, receipt: Mapping[str, Any]) -> bool:
        row = dict(receipt)
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
