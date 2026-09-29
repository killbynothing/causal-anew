"""P2a world fact commit boundary.

This is deliberately narrower than a generic event bus. It first owns terminal
world transactions so a stable fact cannot silently accept two outcomes. Later
P2 migrations can add projections behind the same commit boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.causal_protocol import canonical_payload_hash


class WorldCommitConflict(ValueError):
    """A stable world fact id was reused for a different semantic fact."""


def _semantic_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "transaction_id": str(record.get("transaction_id") or "").strip(),
        "kind": str(record.get("kind") or "").strip(),
        "outcome": str(record.get("outcome") or "").strip(),
        "owner": str(record.get("owner") or "").strip(),
        "worldline": str(record.get("worldline") or "WMAIN").strip() or "WMAIN",
        "run": int(record.get("run") or 0),
        "public_effect": str(record.get("public_effect") or "").strip(),
    }


@dataclass(frozen=True)
class WorldTransactionProposal:
    transaction_id: str
    kind: str
    outcome: str
    owner: str
    scene_id: str
    turn: int
    worldline: str
    run: int
    public_effect: str = ""

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("world transaction requires a stable id")
        if self.run < 1:
            raise ValueError("world transaction requires run>=1")
        if not self.kind.strip() or not self.outcome.strip() or not self.owner.strip():
            raise ValueError("world transaction requires kind/outcome/owner")

    def record(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id.strip(),
            "kind": self.kind.strip(),
            "outcome": self.outcome.strip(),
            "owner": self.owner.strip(),
            "scene_id": self.scene_id.strip(),
            "turn": int(self.turn),
            "worldline": self.worldline.strip() or "WMAIN",
            "run": int(self.run),
            "public_effect": self.public_effect.strip(),
        }


@dataclass(frozen=True)
class WorldCommitReceipt:
    receipt_id: str
    transaction_id: str
    payload_hash: str
    committed_record: dict[str, Any]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "free_stage.world_commit_receipt.v1",
            "receipt_id": self.receipt_id,
            "transaction_id": self.transaction_id,
            "payload_hash": self.payload_hash,
            "committed_record": dict(self.committed_record),
            "status": self.status,
        }


def commit_transaction(
    transactions: Mapping[str, Mapping[str, Any]] | None,
    proposal: WorldTransactionProposal,
) -> tuple[dict[str, dict[str, Any]], WorldCommitReceipt]:
    """Commit one terminal fact.

    scene_id and turn are first-observation provenance, not semantic identity.
    Reload/flashback replay may therefore confirm a fact without moving its
    origin or rewriting its outcome.
    """
    current = {
        str(key): dict(value)
        for key, value in dict(transactions or {}).items()
        if str(key).strip() and isinstance(value, Mapping)
    }
    candidate = proposal.record()
    semantic = _semantic_record(candidate)
    payload_hash = canonical_payload_hash(semantic)
    tx_id = proposal.transaction_id.strip()
    receipt_id = f"worldtx:{proposal.worldline}:{proposal.run}:{tx_id}"

    existing = current.get(tx_id)
    if existing is not None:
        if _semantic_record(existing) != semantic:
            raise WorldCommitConflict(
                f"world transaction conflict for {tx_id}: "
                f"existing={_semantic_record(existing)!r} candidate={semantic!r}"
            )
        return current, WorldCommitReceipt(
            receipt_id=receipt_id,
            transaction_id=tx_id,
            payload_hash=payload_hash,
            committed_record=dict(existing),
            status="idempotent",
        )

    current[tx_id] = candidate
    return current, WorldCommitReceipt(
        receipt_id=receipt_id,
        transaction_id=tx_id,
        payload_hash=payload_hash,
        committed_record=dict(candidate),
        status="committed",
    )
