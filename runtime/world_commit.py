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
)

WORLD_COMMIT_SCHEMA = "free_stage.world_commit.v1"

# P2a deliberately migrates the mature world_transactions append path first.
# These authority-map fact families remain compatibility writers until P2c.
P2A_WORLD_MIGRATION_DEBT = (
    "branch_progress",
    "scene_receipts",
    "world_transactions",  # reset/load compatibility writers remain
    "causal_receipts",
    "run_observation_ledger",
    "player_state",
    "body_frames",
    "world_cursor",
)


@dataclass(frozen=True)
class WorldCommitResult:
    record: dict[str, Any]
    committed: bool


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
    """Commit one immutable world fact, or return the exact prior retry.

    Reusing a transaction id with a different fact, scope, request, or source
    chain is a hard conflict. Legacy records without envelopes remain readable
    and can only be retried when their public core is identical.
    """
    tx_id = _text(transaction_id)
    req_id = _text(request_id)
    if not tx_id or not req_id or not _text(kind) or not _text(outcome) or not _text(owner):
        raise ValueError("world commit requires transaction/request/kind/outcome/owner")
    if int(turn) < 0:
        raise ValueError("world commit turn must be >= 0")
    if int(scope.run) < 1:
        raise ValueError("world commit requires run>=1")

    payload = {
        "transaction_id": tx_id,
        "kind": _text(kind),
        "outcome": _text(outcome),
        "owner": _text(owner),
        "scene_id": _text(scene_id),
        "turn": int(turn),
        "worldline": scope.worldline,
        "run": int(scope.run),
        "public_effect": _text(public_effect),
    }
    receipt = ReceiptEnvelope.for_payload(
        receipt_id=f"world:{canonical_payload_hash({'scope': scope.to_dict(), 'transaction_id': tx_id})}",
        request_id=req_id,
        turn_id=_text(turn_id) or f"turn:{int(turn)}",
        sequence=0,
        scope=scope,
        producer="WorldCommit",
        source_refs=tuple(_text(item) for item in source_refs if _text(item)),
        visibility="public",
        base_revision=int(base_revision),
        payload=payload,
    )
    candidate = {
        "schema_version": WORLD_COMMIT_SCHEMA,
        **payload,
        "request_id": req_id,
        "receipt": receipt.to_dict(),
    }

    existing = ledger.get(tx_id)
    if existing is not None:
        if _core(existing) != payload:
            raise ReceiptConflict(f"world transaction id reused with different fact: {tx_id}")
        # Legacy pre-P2a records have no envelope. Their public fact is frozen,
        # but we do not retroactively fabricate provenance.
        if existing.get("schema_version") != WORLD_COMMIT_SCHEMA:
            return WorldCommitResult(record=dict(existing), committed=False)
        if canonical_payload_hash(existing) != canonical_payload_hash(candidate):
            raise ReceiptConflict(f"world transaction id reused with different provenance: {tx_id}")
        return WorldCommitResult(record=dict(existing), committed=False)

    ledger[tx_id] = candidate
    return WorldCommitResult(record=dict(candidate), committed=True)
