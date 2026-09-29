#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tempfile import TemporaryDirectory

from runtime.causal_protocol import (
    COMMIT_BATCH_UNIQUE_KEY_FIELDS,
    CommitCursor,
    CommitProtocolError,
    PendingCommit,
    ReceiptConflict,
    ReceiptEnvelope,
    RuntimeScope,
    acknowledge_commit,
    assert_idempotent_receipt,
    assert_scope,
    canonical_payload_hash,
    commit_batch_id,
    prepare_commit,
)
from runtime.runtime_snapshots import ActorSnapshot, WorldSnapshot
from runtime.runtime_store import RuntimeStore, RuntimeStoreError


def scope(run=2, scene_instance_id="S1#visit1"):
    return RuntimeScope(
        worldline="WMAIN",
        run=run,
        ch_anchor=1,
        session_id="p0b-fixture",
        scene_instance_id=scene_instance_id,
    )


def test_hash_and_receipt_retry_are_deterministic():
    assert canonical_payload_hash({"b": 2, "a": 1}) == canonical_payload_hash({"a": 1, "b": 2})
    env = ReceiptEnvelope.for_payload(
        receipt_id="r1",
        request_id="req1",
        turn_id="turn:1",
        sequence=0,
        scope=scope(),
        producer="PlayerActionResolver",
        source_refs=["input:1"],
        visibility="public",
        base_revision=4,
        payload={"verb": "accept", "target": "pendant"},
    )
    same = ReceiptEnvelope.from_dict(env.to_dict())
    assert assert_idempotent_receipt(env, same) is env

    changed = ReceiptEnvelope.for_payload(
        receipt_id="r1",
        request_id="req1",
        turn_id="turn:1",
        sequence=0,
        scope=scope(),
        producer="PlayerActionResolver",
        source_refs=["input:1"],
        visibility="public",
        base_revision=4,
        payload={"verb": "decline", "target": "pendant"},
    )
    try:
        assert_idempotent_receipt(env, changed)
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same receipt id with different payload must conflict")


def test_receipt_scope_rejects_run_zero_and_wrong_scene():
    try:
        ReceiptEnvelope.for_payload(
            receipt_id="r0",
            request_id="req0",
            turn_id="turn:0",
            sequence=0,
            scope=scope(run=0),
            producer="Resolver",
            visibility="system",
            base_revision=0,
            payload={},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("committed receipt must reject run=0")

    env = ReceiptEnvelope.for_payload(
        receipt_id="r2", request_id="req2", turn_id="turn:2", sequence=0,
        scope=scope(), producer="Resolver", visibility="public", base_revision=0,
        payload={"event": "x"},
    )
    try:
        assert_scope(env, scope(scene_instance_id="S1#visit2"))
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("cross-scene replay must be rejected")


def test_pending_ack_cursor_is_retryable_and_conflict_safe():
    cursor = CommitCursor(revision=3)
    pending = PendingCommit.for_payload(
        batch_id="batch:3:0",
        request_id="req3",
        base_revision=3,
        batch_index=0,
        payload={"receipt_ids": ["r3"]},
        receipt_ids=["r3"],
    )
    prepared = prepare_commit(cursor, pending)
    assert prepared.pending == pending
    assert prepare_commit(prepared, pending) == prepared

    conflicting = PendingCommit.for_payload(
        batch_id="batch:3:0",
        request_id="req3",
        base_revision=3,
        batch_index=0,
        payload={"receipt_ids": ["DIFFERENT"]},
        receipt_ids=["DIFFERENT"],
    )
    try:
        prepare_commit(prepared, conflicting)
    except ReceiptConflict:
        pass
    else:
        raise AssertionError("same batch id/different payload must conflict")

    other = PendingCommit.for_payload(
        batch_id="batch:3:1", request_id="req3", base_revision=3, batch_index=1,
        payload={"x": 1},
    )
    try:
        prepare_commit(prepared, other)
    except CommitProtocolError:
        pass
    else:
        raise AssertionError("only one pending batch is allowed")

    acked = acknowledge_commit(prepared, "batch:3:0")
    assert acked.revision == 4
    assert acked.pending is None
    assert acked.last_committed_batch_id == "batch:3:0"
    assert acknowledge_commit(acked, "batch:3:0") == acked


def test_batch_id_is_stable_and_scope_sensitive():
    assert COMMIT_BATCH_UNIQUE_KEY_FIELDS == (
        "worldline", "run", "session_id", "scene_instance_id", "request_id", "batch_index"
    )
    first = commit_batch_id(scope(), request_id="req-key", batch_index=0)
    assert first == commit_batch_id(scope(), request_id="req-key", batch_index=0)
    assert first != commit_batch_id(scope(scene_instance_id="S1#visit2"), request_id="req-key", batch_index=0)
    assert first != commit_batch_id(scope(), request_id="req-key", batch_index=1)


def test_stale_revision_is_rejected():
    cursor = CommitCursor(revision=5)
    pending = PendingCommit.for_payload(
        batch_id="b", request_id="r", base_revision=4, batch_index=0, payload={},
    )
    try:
        prepare_commit(cursor, pending)
    except CommitProtocolError:
        pass
    else:
        raise AssertionError("stale base revision must be rejected")


def test_runtime_store_outbox_is_atomic_and_strict():
    with TemporaryDirectory() as tmp:
        store = RuntimeStore(tmp, "p0b-session")
        assert store.load_commit_cursor() == CommitCursor()

        pending = PendingCommit.for_payload(
            batch_id="batch:p0b",
            request_id="req-p0b",
            base_revision=0,
            batch_index=0,
            payload={"r": 1},
            receipt_ids=["r1"],
        )
        prepared = prepare_commit(CommitCursor(), pending)
        store.save_commit_cursor(prepared)
        before = store.commit_state_path.read_bytes()
        assert store.load_commit_cursor() == prepared

        acked = acknowledge_commit(prepared, "batch:p0b")
        try:
            store.save_commit_cursor(acked, failpoint="after_temp_write")
        except RuntimeStoreError:
            pass
        else:
            raise AssertionError("fault injection must fail")
        assert store.commit_state_path.read_bytes() == before
        assert store.load_commit_cursor() == prepared
        assert not store.commit_state_path.with_name(store.commit_state_path.name + ".tmp").exists()

        store.save_commit_cursor(acked)
        assert store.load_commit_cursor() == acked

        store.commit_state_path.write_text("{broken", encoding="utf-8")
        try:
            store.load_commit_cursor()
        except RuntimeStoreError:
            pass
        else:
            raise AssertionError("corrupt outbox must not look like a fresh cursor")


def test_snapshots_are_deeply_immutable_views():
    source = {"nested": {"items": [1, 2]}, "cursor": {"scene": "S1"}}
    world = WorldSnapshot.capture(scope=scope(run=0), revision=8, payload=source, source_receipt_ids=["r1"])
    actor = ActorSnapshot.capture(
        scope=scope(), actor_cons="C.ryuya.W1", revision=8,
        payload={"goals": ["wait"], "visible": source},
        source_receipt_ids=["r1"],
    )
    source["nested"]["items"].append(99)
    assert world.payload()["nested"]["items"] == [1, 2]

    thawed = world.payload()
    thawed["nested"]["items"].append(77)
    assert world.payload()["nested"]["items"] == [1, 2]
    assert actor.actor_cons == "C.ryuya.W1"
    assert actor.to_dict()["source_receipt_ids"] == ["r1"]


if __name__ == "__main__":
    test_hash_and_receipt_retry_are_deterministic()
    test_receipt_scope_rejects_run_zero_and_wrong_scene()
    test_pending_ack_cursor_is_retryable_and_conflict_safe()
    test_batch_id_is_stable_and_scope_sensitive()
    test_stale_revision_is_rejected()
    test_runtime_store_outbox_is_atomic_and_strict()
    test_snapshots_are_deeply_immutable_views()
    print("PASS test_receipt_protocol")
