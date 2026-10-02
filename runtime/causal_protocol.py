"""N2's small, replayable observation -> proposal -> event -> receipt protocol.

These records carry identifiers and safe summaries, never hidden prompt text or
chain-of-thought.  A proposal is explicitly not a world fact; only resolver
output may create an event receipt.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class ObservationFrame:
    observation_id: str
    actor_cons: str
    scene_id: str
    turn: int
    public_dialogue_count: int
    private_perception_count: int
    source_trace_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    observation_id: str
    actor_cons: str
    action_kind: str
    requested_outcome: str
    turn: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldEvent:
    event_id: str
    proposal_id: str
    event_kind: str
    outcome: str
    scene_effects: tuple[str, ...]
    turn: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "proposal_id": self.proposal_id,
            "event_kind": self.event_kind,
            "outcome": self.outcome,
            "scene_effects": list(self.scene_effects),
            "turn": self.turn,
        }


@dataclass(frozen=True)
class EventReceipt:
    receipt_id: str
    observation: ObservationFrame
    proposal: ActionProposal
    event: WorldEvent

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "free_stage.causal_receipt.v1",
            "receipt_id": self.receipt_id,
            "observation": self.observation.to_dict(),
            "proposal": self.proposal.to_dict(),
            "event": self.event.to_dict(),
        }


@dataclass
class CausalReceiptLedger:
    """Single mutable owner for resolver-owned causal receipts."""

    _rows: list[dict[str, Any]] = field(default_factory=list)
    _hash_by_id: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_saved(cls, raw: list[Any] | tuple[Any, ...] | None) -> "CausalReceiptLedger":
        ledger = cls()
        for item in raw or ():
            if not isinstance(item, Mapping):
                continue
            ledger.append(dict(item))
        return ledger

    def rows(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(item) for item in self._rows]

    def reset(self) -> None:
        self._rows.clear()
        self._hash_by_id.clear()

    def append(self, receipt: Mapping[str, Any]) -> bool:
        row = copy.deepcopy(dict(receipt))
        receipt_id = str(row.get("receipt_id") or "").strip()
        if not receipt_id:
            raise ValueError("causal receipt requires receipt_id")
        digest = canonical_payload_hash(row)
        prior = self._hash_by_id.get(receipt_id)
        if prior is not None:
            if prior != digest:
                raise ReceiptConflict(
                    f"causal receipt id reused with different payload: {receipt_id}"
                )
            return False
        self._rows.append(row)
        self._hash_by_id[receipt_id] = digest
        return True


def observation_from_packet(packet: Mapping[str, Any], *, turn: int) -> ObservationFrame:
    actor_cons = str(packet.get("actor_cons", "") or "").strip()
    scene_id = str(packet.get("scene", "") or "").strip()
    if not actor_cons or not scene_id:
        raise ValueError("observation requires actor_cons and scene")
    return ObservationFrame(
        observation_id=f"obs:{scene_id}:{turn}:{actor_cons}",
        actor_cons=actor_cons,
        scene_id=scene_id,
        turn=max(0, int(turn)),
        public_dialogue_count=len(packet.get("observable_dialogue", ()) or ()),
        private_perception_count=len(packet.get("private_perceptions", ()) or ()),
        source_trace_count=len(packet.get("source_trace", ()) or ()),
    )


def resolve_actor_decision(
    observation: ObservationFrame,
    decision: Mapping[str, Any],
    *,
    scene_effects: Mapping[str, Any] | None = None,
) -> EventReceipt:
    """Turn an actor's validated decision into a resolver-owned event receipt."""
    actor_cons = str(decision.get("actor_cons", "") or "").strip()
    outcome = str(decision.get("outcome", "") or "").strip()
    decision_id = str(decision.get("decision_id", "") or "").strip()
    if actor_cons != observation.actor_cons or not outcome or not decision_id:
        raise ValueError("decision does not belong to the observation or lacks a stable id")
    effects = tuple(sorted(str(key) for key, value in dict(scene_effects or {}).items() if bool(value)))
    proposal = ActionProposal(
        proposal_id=f"proposal:{decision_id}", observation_id=observation.observation_id,
        actor_cons=actor_cons, action_kind="actor_owned_decision", requested_outcome=outcome,
        turn=observation.turn,
    )
    event = WorldEvent(
        event_id=f"event:{decision_id}", proposal_id=proposal.proposal_id,
        event_kind="actor_autonomous_choice", outcome=outcome, scene_effects=effects,
        turn=observation.turn,
    )
    return EventReceipt(
        receipt_id=f"receipt:{decision_id}", observation=observation, proposal=proposal, event=event,
    )


# ---------------------------------------------------------------------------
# P0b protocol contracts. These are pure data/validation helpers only.
# Production FreeStageSession wiring remains on the legacy v1 path until P1/P2.
# ---------------------------------------------------------------------------

RECEIPT_ENVELOPE_SCHEMA = "free_stage.receipt_envelope.v1"
COMMIT_CURSOR_SCHEMA = "free_stage.commit_cursor.v1"
COMMIT_BATCH_UNIQUE_KEY_FIELDS = (
    "worldline",
    "run",
    "session_id",
    "scene_instance_id",
    "request_id",
    "batch_index",
)


class ReceiptConflict(ValueError):
    """Same stable id was reused with a different committed payload."""


class CommitProtocolError(ValueError):
    """Pending/ack cursor violates the single in-flight batch contract."""


@dataclass(frozen=True)
class RuntimeScope:
    worldline: str
    run: int
    ch_anchor: int
    session_id: str
    scene_instance_id: str

    def __post_init__(self) -> None:
        if not str(self.worldline).strip():
            raise ValueError("scope requires worldline")
        if int(self.run) < 0:
            raise ValueError("scope run must be >= 0")
        if int(self.ch_anchor) < 0:
            raise ValueError("scope ch_anchor must be >= 0")
        if not str(self.session_id).strip():
            raise ValueError("scope requires session_id")
        if not str(self.scene_instance_id).strip():
            raise ValueError("scope requires scene_instance_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "worldline": self.worldline,
            "run": int(self.run),
            "ch_anchor": int(self.ch_anchor),
            "session_id": self.session_id,
            "scene_instance_id": self.scene_instance_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeScope":
        return cls(
            worldline=str(raw.get("worldline", "") or ""),
            run=int(raw.get("run", 0) or 0),
            ch_anchor=int(raw.get("ch_anchor", 0) or 0),
            session_id=str(raw.get("session_id", "") or ""),
            scene_instance_id=str(raw.get("scene_instance_id", "") or ""),
        )


def canonical_payload_hash(payload: Mapping[str, Any] | list[Any] | tuple[Any, ...] | str | int | float | bool | None) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ReceiptEnvelope:
    receipt_id: str
    request_id: str
    turn_id: str
    sequence: int
    scope: RuntimeScope
    producer: str
    source_refs: tuple[str, ...]
    visibility: str
    base_revision: int
    payload_hash: str
    schema_version: str = RECEIPT_ENVELOPE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != RECEIPT_ENVELOPE_SCHEMA:
            raise ValueError(f"unsupported receipt envelope schema: {self.schema_version}")
        if self.scope.run < 1:
            raise ValueError("committed runtime receipts require run>=1")
        if not self.receipt_id.strip() or not self.request_id.strip() or not self.turn_id.strip():
            raise ValueError("receipt/request/turn ids are required")
        if self.sequence < 0 or self.base_revision < 0:
            raise ValueError("sequence/base_revision must be >= 0")
        if not self.producer.strip():
            raise ValueError("producer is required")
        if self.visibility not in {"public", "private", "director", "system"}:
            raise ValueError(f"unsupported visibility: {self.visibility}")
        if len(self.payload_hash) != 64:
            raise ValueError("payload_hash must be sha256 hex")

    @classmethod
    def for_payload(
        cls,
        *,
        receipt_id: str,
        request_id: str,
        turn_id: str,
        sequence: int,
        scope: RuntimeScope,
        producer: str,
        source_refs: tuple[str, ...] | list[str] = (),
        visibility: str,
        base_revision: int,
        payload: Any,
    ) -> "ReceiptEnvelope":
        return cls(
            receipt_id=receipt_id,
            request_id=request_id,
            turn_id=turn_id,
            sequence=int(sequence),
            scope=scope,
            producer=producer,
            source_refs=tuple(str(x) for x in source_refs if str(x).strip()),
            visibility=visibility,
            base_revision=int(base_revision),
            payload_hash=canonical_payload_hash(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "request_id": self.request_id,
            "turn_id": self.turn_id,
            "sequence": self.sequence,
            "scope": self.scope.to_dict(),
            "producer": self.producer,
            "source_refs": list(self.source_refs),
            "visibility": self.visibility,
            "base_revision": self.base_revision,
            "payload_hash": self.payload_hash,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ReceiptEnvelope":
        if raw.get("schema_version") != RECEIPT_ENVELOPE_SCHEMA:
            raise ValueError("unsupported receipt envelope schema")
        source_refs = raw.get("source_refs") or ()
        if not isinstance(source_refs, (list, tuple)):
            raise ValueError("source_refs must be a list/tuple")
        scope_raw = raw.get("scope")
        if not isinstance(scope_raw, Mapping):
            raise ValueError("receipt envelope requires scope")
        return cls(
            receipt_id=str(raw.get("receipt_id", "") or ""),
            request_id=str(raw.get("request_id", "") or ""),
            turn_id=str(raw.get("turn_id", "") or ""),
            sequence=int(raw.get("sequence", 0) or 0),
            scope=RuntimeScope.from_dict(scope_raw),
            producer=str(raw.get("producer", "") or ""),
            source_refs=tuple(str(x) for x in source_refs if str(x).strip()),
            visibility=str(raw.get("visibility", "") or ""),
            base_revision=int(raw.get("base_revision", 0) or 0),
            payload_hash=str(raw.get("payload_hash", "") or ""),
        )


def assert_idempotent_receipt(existing: ReceiptEnvelope, candidate: ReceiptEnvelope) -> ReceiptEnvelope:
    """Return existing for byte-equivalent logical retry; conflict otherwise."""
    if existing.receipt_id != candidate.receipt_id:
        raise ReceiptConflict("receipt ids differ")
    if existing != candidate:
        raise ReceiptConflict(f"receipt id reused with different envelope/payload: {existing.receipt_id}")
    return existing


def commit_batch_id(
    scope: RuntimeScope,
    *,
    request_id: str,
    batch_index: int,
) -> str:
    """Stable future DB idempotency key; no DB table is changed in P0b."""
    if scope.run < 1:
        raise CommitProtocolError("commit batch requires run>=1")
    if not str(request_id).strip() or int(batch_index) < 0:
        raise CommitProtocolError("commit batch requires request_id and batch_index>=0")
    digest = canonical_payload_hash(
        {
            "worldline": scope.worldline,
            "run": scope.run,
            "session_id": scope.session_id,
            "scene_instance_id": scope.scene_instance_id,
            "request_id": str(request_id),
            "batch_index": int(batch_index),
        }
    )
    return f"batch:{digest}"


def assert_scope(envelope: ReceiptEnvelope, expected: RuntimeScope) -> None:
    if envelope.scope != expected:
        raise ReceiptConflict(
            f"receipt scope mismatch: got={envelope.scope.to_dict()} expected={expected.to_dict()}"
        )


@dataclass(frozen=True)
class PendingCommit:
    batch_id: str
    request_id: str
    base_revision: int
    batch_index: int
    payload_hash: str
    receipt_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.batch_id.strip() or not self.request_id.strip():
            raise CommitProtocolError("pending commit requires batch_id/request_id")
        if self.base_revision < 0 or self.batch_index < 0:
            raise CommitProtocolError("base_revision/batch_index must be >= 0")
        if len(self.payload_hash) != 64:
            raise CommitProtocolError("pending payload_hash must be sha256 hex")

    @classmethod
    def for_payload(
        cls,
        *,
        batch_id: str,
        request_id: str,
        base_revision: int,
        batch_index: int,
        payload: Any,
        receipt_ids: tuple[str, ...] | list[str] = (),
    ) -> "PendingCommit":
        return cls(
            batch_id=batch_id,
            request_id=request_id,
            base_revision=int(base_revision),
            batch_index=int(batch_index),
            payload_hash=canonical_payload_hash(payload),
            receipt_ids=tuple(str(x) for x in receipt_ids if str(x).strip()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "request_id": self.request_id,
            "base_revision": self.base_revision,
            "batch_index": self.batch_index,
            "payload_hash": self.payload_hash,
            "receipt_ids": list(self.receipt_ids),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PendingCommit":
        ids = raw.get("receipt_ids") or ()
        if not isinstance(ids, (list, tuple)):
            raise CommitProtocolError("receipt_ids must be list/tuple")
        return cls(
            batch_id=str(raw.get("batch_id", "") or ""),
            request_id=str(raw.get("request_id", "") or ""),
            base_revision=int(raw.get("base_revision", 0) or 0),
            batch_index=int(raw.get("batch_index", 0) or 0),
            payload_hash=str(raw.get("payload_hash", "") or ""),
            receipt_ids=tuple(str(x) for x in ids if str(x).strip()),
        )


@dataclass(frozen=True)
class CommitCursor:
    revision: int = 0
    last_committed_batch_id: str | None = None
    pending: PendingCommit | None = None
    schema_version: str = COMMIT_CURSOR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != COMMIT_CURSOR_SCHEMA:
            raise CommitProtocolError(f"unsupported commit cursor schema: {self.schema_version}")
        if self.revision < 0:
            raise CommitProtocolError("revision must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "last_committed_batch_id": self.last_committed_batch_id,
            "pending": self.pending.to_dict() if self.pending else None,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CommitCursor":
        if raw.get("schema_version") != COMMIT_CURSOR_SCHEMA:
            raise CommitProtocolError("unsupported commit cursor schema")
        pending_raw = raw.get("pending")
        pending = None
        if pending_raw is not None:
            if not isinstance(pending_raw, Mapping):
                raise CommitProtocolError("pending must be object/null")
            pending = PendingCommit.from_dict(pending_raw)
        return cls(
            revision=int(raw.get("revision", 0) or 0),
            last_committed_batch_id=(
                str(raw.get("last_committed_batch_id"))
                if raw.get("last_committed_batch_id") is not None
                else None
            ),
            pending=pending,
        )


def prepare_commit(cursor: CommitCursor, pending: PendingCommit) -> CommitCursor:
    """Prepare exactly one batch. Same retry is idempotent; conflicts are hard errors."""
    if pending.base_revision != cursor.revision:
        raise CommitProtocolError(
            f"stale base_revision: pending={pending.base_revision} cursor={cursor.revision}"
        )
    if cursor.pending is None:
        return CommitCursor(
            revision=cursor.revision,
            last_committed_batch_id=cursor.last_committed_batch_id,
            pending=pending,
        )
    if cursor.pending == pending:
        return cursor
    if cursor.pending.batch_id == pending.batch_id:
        raise ReceiptConflict(f"batch id reused with different payload: {pending.batch_id}")
    raise CommitProtocolError(
        f"another batch is already pending: {cursor.pending.batch_id}"
    )


def acknowledge_commit(cursor: CommitCursor, batch_id: str) -> CommitCursor:
    """Advance recovery cursor after the prepared batch has durably committed."""
    if cursor.pending is None:
        if cursor.last_committed_batch_id == batch_id:
            return cursor
        raise CommitProtocolError("cannot ack without pending batch")
    if cursor.pending.batch_id != batch_id:
        raise CommitProtocolError(
            f"ack batch mismatch: pending={cursor.pending.batch_id} got={batch_id}"
        )
    return CommitCursor(
        revision=cursor.revision + 1,
        last_committed_batch_id=batch_id,
        pending=None,
    )
