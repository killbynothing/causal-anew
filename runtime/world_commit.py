"""P2a single submission boundary for replayable world facts.

This module owns commits into the session world-transaction ledger. It does not
decide story semantics; callers must submit an already-authorized fact.
"""
from __future__ import annotations

import copy
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
SCENE_FACT_LEDGER_SCHEMA = "free_stage.scene_fact_ledger.v1"
SCENE_FACT_EVENT_SCHEMA = "free_stage.scene_fact_event.v1"

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



@dataclass(frozen=True)
class SceneFactCommitResult:
    event: dict[str, Any]
    committed: bool


def new_scene_fact_ledger() -> dict[str, Any]:
    return {
        "schema_version": SCENE_FACT_LEDGER_SCHEMA,
        "events": {},
        "event_order": [],
    }


def normalize_scene_fact_ledger(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return new_scene_fact_ledger()
    if not isinstance(raw, Mapping):
        raise ValueError("scene fact ledger must be an object")
    data = copy.deepcopy(dict(raw))
    if data.get("schema_version") != SCENE_FACT_LEDGER_SCHEMA:
        raise ValueError(
            f"unsupported scene fact ledger schema: {data.get('schema_version')!r}"
        )
    if not isinstance(data.get("events"), dict):
        raise ValueError("scene fact ledger events must be an object")
    if not isinstance(data.get("event_order"), list):
        raise ValueError("scene fact ledger event_order must be a list")
    events = data["events"]
    order = [str(item) for item in data["event_order"] if str(item).strip()]
    if len(order) != len(set(order)):
        raise ValueError("scene fact ledger event_order contains duplicates")
    if set(order) != set(str(key) for key in events):
        raise ValueError("scene fact ledger event_order/events mismatch")
    for event_id in order:
        event = events.get(event_id)
        if not isinstance(event, Mapping):
            raise ValueError(f"scene fact event must be an object: {event_id}")
        if event.get("schema_version") != SCENE_FACT_EVENT_SCHEMA:
            raise ValueError(f"unsupported scene fact event schema: {event_id}")
    data["event_order"] = order
    return data


def _scene_fact_event_id(
    scope: RuntimeScope,
    *,
    request_id: str,
    operation: str,
    fact_id: str,
) -> str:
    return (
        "scene-fact:"
        + canonical_payload_hash(
            {
                "scope": scope.to_dict(),
                "request_id": _text(request_id),
                "operation": _text(operation),
                "fact_id": _text(fact_id),
            }
        )
    )


def _scene_receipt_id(scope: RuntimeScope, fact_id: str) -> str:
    return (
        "scene:"
        + canonical_payload_hash(
            {
                "scope": scope.to_dict(),
                "fact_id": _text(fact_id),
            }
        )
    )


def _append_scene_fact_event(
    ledger: MutableMapping[str, Any],
    *,
    scope: RuntimeScope,
    request_id: str,
    fact_id: str,
    operation: str,
    owner: str,
    turn: int,
    source_kind: str,
    source_input: str = "",
    source_refs: Sequence[str] = (),
    branch_visible: bool,
    receipt_visible: bool,
    legacy_receipt_id: str = "",
) -> SceneFactCommitResult:
    if ledger.get("schema_version") != SCENE_FACT_LEDGER_SCHEMA:
        raise ValueError("scene fact ledger schema mismatch")
    if not isinstance(ledger.get("events"), dict) or not isinstance(
        ledger.get("event_order"), list
    ):
        raise ValueError("scene fact ledger is malformed")
    if int(scope.run) < 1:
        raise ValueError("scene fact commit requires run>=1")

    req_id = _text(request_id)
    fact = _text(fact_id)
    op = _text(operation)
    kind = _text(source_kind)
    who = _text(owner)
    refs = tuple(_text(item) for item in source_refs if _text(item))
    if not req_id or not fact or op not in {"assert", "revoke"} or not kind or not who:
        raise ValueError("scene fact commit requires request/fact/op/owner/source_kind")
    if int(turn) < 0:
        raise ValueError("scene fact turn must be >=0")

    event_id = _scene_fact_event_id(
        scope,
        request_id=req_id,
        operation=op,
        fact_id=fact,
    )
    payload = {
        "event_id": event_id,
        "operation": op,
        "fact_id": fact,
        "owner": who,
        "turn": int(turn),
        "source_kind": kind,
        "source_input": _text(source_input),
        "source_refs": list(refs),
        "branch_visible": bool(branch_visible),
        "receipt_visible": bool(receipt_visible),
        "legacy_receipt_id": _text(legacy_receipt_id),
        "scope": scope.to_dict(),
    }
    receipt = ReceiptEnvelope.for_payload(
        receipt_id=f"world-scene:{canonical_payload_hash({'event_id': event_id})}",
        request_id=req_id,
        turn_id=f"turn:{int(turn)}",
        sequence=0,
        scope=scope,
        producer="WorldCommit",
        source_refs=refs,
        visibility="public",
        base_revision=0,
        payload=payload,
    )
    event = {
        "schema_version": SCENE_FACT_EVENT_SCHEMA,
        **payload,
        "commit_receipt": receipt.to_dict(),
    }

    events = ledger["events"]
    existing = events.get(event_id)
    if existing is not None:
        if canonical_payload_hash(existing) != canonical_payload_hash(event):
            raise ReceiptConflict(
                f"scene fact event id reused with different payload: {event_id}"
            )
        return SceneFactCommitResult(event=copy.deepcopy(existing), committed=False)

    events[event_id] = event
    ledger["event_order"].append(event_id)
    return SceneFactCommitResult(event=copy.deepcopy(event), committed=True)


def project_branch_progress(ledger: Mapping[str, Any] | None) -> list[str]:
    data = normalize_scene_fact_ledger(ledger)
    active: list[str] = []
    for event_id in data["event_order"]:
        event = data["events"][event_id]
        if not bool(event.get("branch_visible")):
            continue
        fact = _text(event.get("fact_id"))
        if not fact:
            continue
        if event.get("operation") == "assert":
            if fact not in active:
                active.append(fact)
        elif event.get("operation") == "revoke":
            active = [item for item in active if item != fact]
    return active


def _compat_scene_receipt(event: Mapping[str, Any]) -> dict[str, Any]:
    scope = RuntimeScope.from_dict(dict(event.get("scope") or {}))
    receipt_id = _text(event.get("legacy_receipt_id")) or _scene_receipt_id(
        scope, _text(event.get("fact_id"))
    )
    commit_receipt = (
        dict(event.get("commit_receipt"))
        if isinstance(event.get("commit_receipt"), Mapping)
        else {}
    )
    return {
        "scene_id": _text(event.get("scene_id"))
        or scope.scene_instance_id.split(":visit:", 1)[0],
        "scene_instance_id": scope.scene_instance_id,
        "fact_id": _text(event.get("fact_id")),
        "owner": _text(event.get("owner")),
        "turn": int(event.get("turn", 0) or 0),
        "source_input": _text(event.get("source_input")),
        "source_kind": _text(event.get("source_kind")),
        "receipt_id": receipt_id,
        "world_receipt_id": _text(commit_receipt.get("receipt_id")),
    }


def project_scene_receipts(ledger: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    data = normalize_scene_fact_ledger(ledger)
    out: list[dict[str, Any]] = []
    for event_id in data["event_order"]:
        event = data["events"][event_id]
        if event.get("operation") != "assert" or not bool(event.get("receipt_visible")):
            continue
        out.append(_compat_scene_receipt(event))
    return out


def assert_branch_fact(
    ledger: MutableMapping[str, Any],
    *,
    scope: RuntimeScope,
    request_id: str,
    fact_id: str,
    owner: str,
    turn: int,
    source_kind: str,
    source_refs: Sequence[str],
    source_input: str = "",
) -> SceneFactCommitResult:
    fact = _text(fact_id)
    req_id = _text(request_id)
    candidate_id = _scene_fact_event_id(
        scope,
        request_id=req_id,
        operation="assert",
        fact_id=fact,
    )
    # Same stable request/fact key must first prove exact idempotency. This
    # catches a retry whose owner/source/payload changed instead of silently
    # accepting it merely because the fact is already active.
    if candidate_id in (ledger.get("events") or {}):
        return _append_scene_fact_event(
            ledger,
            scope=scope,
            request_id=req_id,
            fact_id=fact,
            operation="assert",
            owner=owner,
            turn=int(turn),
            source_kind=source_kind,
            source_input=source_input,
            source_refs=source_refs,
            branch_visible=True,
            receipt_visible=False,
        )
    if fact in project_branch_progress(ledger):
        for event_id in reversed(list(ledger.get("event_order") or [])):
            event = (ledger.get("events") or {}).get(event_id)
            if (
                isinstance(event, Mapping)
                and event.get("operation") == "assert"
                and bool(event.get("branch_visible"))
                and _text(event.get("fact_id")) == fact
            ):
                return SceneFactCommitResult(event=copy.deepcopy(dict(event)), committed=False)
    return _append_scene_fact_event(
        ledger,
        scope=scope,
        request_id=req_id,
        fact_id=fact,
        operation="assert",
        owner=owner,
        turn=int(turn),
        source_kind=source_kind,
        source_input=source_input,
        source_refs=source_refs,
        branch_visible=True,
        receipt_visible=False,
    )


def revoke_branch_facts(
    ledger: MutableMapping[str, Any],
    *,
    scope: RuntimeScope,
    request_id: str,
    fact_ids: Sequence[str],
    owner: str,
    turn: int,
    source_kind: str,
    source_refs: Sequence[str],
) -> tuple[str, ...]:
    active = set(project_branch_progress(ledger))
    revoked: list[str] = []
    for fact_id in fact_ids:
        fact = _text(fact_id)
        if not fact or fact not in active:
            continue
        result = _append_scene_fact_event(
            ledger,
            scope=scope,
            request_id=f"{_text(request_id)}:{fact}",
            fact_id=fact,
            operation="revoke",
            owner=owner,
            turn=int(turn),
            source_kind=source_kind,
            source_refs=source_refs,
            branch_visible=True,
            receipt_visible=False,
        )
        if result.committed:
            revoked.append(fact)
            active.discard(fact)
    return tuple(revoked)


def record_scene_receipt(
    ledger: MutableMapping[str, Any],
    *,
    scope: RuntimeScope,
    request_id: str,
    scene_id: str,
    fact_id: str,
    owner: str,
    turn: int,
    source_kind: str,
    source_input: str = "",
    source_refs: Sequence[str] = (),
    legacy_receipt_id: str = "",
) -> tuple[dict[str, Any], bool]:
    fact = _text(fact_id)
    for row in project_scene_receipts(ledger):
        if (
            row.get("scene_instance_id") == scope.scene_instance_id
            and row.get("fact_id") == fact
        ):
            if _text(row.get("owner")) != _text(owner):
                raise ReceiptConflict(
                    f"scene receipt fact owner changed in same scene instance: {fact}"
                )
            return dict(row), False

    result = _append_scene_fact_event(
        ledger,
        scope=scope,
        request_id=request_id,
        fact_id=fact,
        operation="assert",
        owner=owner,
        turn=int(turn),
        source_kind=source_kind,
        source_input=source_input,
        source_refs=source_refs,
        branch_visible=False,
        receipt_visible=True,
        legacy_receipt_id=legacy_receipt_id,
    )
    event = dict(result.event)
    event["scene_id"] = _text(scene_id)
    ledger["events"][event["event_id"]]["scene_id"] = _text(scene_id)
    return _compat_scene_receipt(event), result.committed


def active_scene_fact_ids(ledger: Mapping[str, Any] | None) -> set[str]:
    return set(project_branch_progress(ledger)) | {
        _text(row.get("fact_id"))
        for row in project_scene_receipts(ledger)
        if _text(row.get("fact_id"))
    }


def migrate_legacy_scene_facts(
    ledger: MutableMapping[str, Any],
    *,
    scope: RuntimeScope,
    branch_progress: Sequence[str],
    scene_receipts: Sequence[Mapping[str, Any]],
) -> None:
    """One-way adapter. It never fabricates PlayerAction receipts."""
    if ledger.get("event_order"):
        return

    for index, raw in enumerate(scene_receipts):
        row = dict(raw)
        fact = _text(row.get("fact_id"))
        if not fact:
            continue
        scene_id = _text(row.get("scene_id")) or scope.scene_instance_id.split(":visit:", 1)[0]
        instance = _text(row.get("scene_instance_id")) or (
            f"{scene_id}:legacy:"
            + canonical_payload_hash(
                {
                    "session_id": scope.session_id,
                    "scene_id": scene_id,
                    "fact_id": fact,
                    "index": index,
                }
            )[:12]
        )
        row_scope = RuntimeScope(
            worldline=scope.worldline,
            run=scope.run,
            ch_anchor=scope.ch_anchor,
            session_id=scope.session_id,
            scene_instance_id=instance,
        )
        if row_scope.run < 1:
            event_id = (
                "scene-fact:legacy:"
                + canonical_payload_hash(
                    {"scope": row_scope.to_dict(), "fact_id": fact, "index": index}
                )
            )
            event = {
                "schema_version": SCENE_FACT_EVENT_SCHEMA,
                "event_id": event_id,
                "operation": "assert",
                "fact_id": fact,
                "owner": _text(row.get("owner")) or "legacy",
                "turn": int(row.get("turn", 0) or 0),
                "source_kind": _text(row.get("source_kind")) or "legacy_scene_receipt",
                "source_input": _text(row.get("source_input")),
                "source_refs": ["legacy:scene_receipts"],
                "branch_visible": False,
                "receipt_visible": True,
                "legacy_receipt_id": _text(row.get("receipt_id")),
                "scope": row_scope.to_dict(),
                "scene_id": scene_id,
                "commit_receipt": {},
            }
            ledger["events"][event_id] = event
            ledger["event_order"].append(event_id)
        else:
            record_scene_receipt(
                ledger,
                scope=row_scope,
                request_id=f"legacy-scene-receipt:{index}:{fact}",
                scene_id=scene_id,
                fact_id=fact,
                owner=_text(row.get("owner")) or "legacy",
                turn=int(row.get("turn", 0) or 0),
                source_kind=_text(row.get("source_kind")) or "legacy_scene_receipt",
                source_input=_text(row.get("source_input")),
                source_refs=("legacy:scene_receipts",),
                legacy_receipt_id=_text(row.get("receipt_id")),
            )

    for index, fact_id in enumerate(branch_progress):
        fact = _text(fact_id)
        if not fact:
            continue
        if scope.run < 1:
            event_id = (
                "scene-fact:legacy-branch:"
                + canonical_payload_hash(
                    {"scope": scope.to_dict(), "fact_id": fact, "index": index}
                )
            )
            ledger["events"][event_id] = {
                "schema_version": SCENE_FACT_EVENT_SCHEMA,
                "event_id": event_id,
                "operation": "assert",
                "fact_id": fact,
                "owner": "legacy",
                "turn": 0,
                "source_kind": "legacy_branch_progress",
                "source_input": "",
                "source_refs": ["legacy:branch_progress"],
                "branch_visible": True,
                "receipt_visible": False,
                "legacy_receipt_id": "",
                "scope": scope.to_dict(),
                "commit_receipt": {},
            }
            ledger["event_order"].append(event_id)
        else:
            assert_branch_fact(
                ledger,
                scope=scope,
                request_id=f"legacy-branch:{index}:{fact}",
                fact_id=fact,
                owner="legacy",
                turn=0,
                source_kind="legacy_branch_progress",
                source_refs=("legacy:branch_progress",),
            )
