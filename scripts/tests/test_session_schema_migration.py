#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import copy
import json

from runtime.session_schema import (
    SESSION_SCHEMA_V1,
    SESSION_SCHEMA_V2,
    SessionSchemaError,
    UnsupportedSessionSchema,
    migrate_session_payload,
    validate_session_payload,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "scripts" / "tests" / "fixtures"


def load(name):
    path = FIXTURES / name
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_v1_to_v2_matches_fixture_without_mutating_source_bytes():
    path, raw = load("session_schema_v1_p0b.json")
    before_bytes = path.read_bytes()
    before_obj = copy.deepcopy(raw)
    _, expected = load("session_schema_v2_p0b.json")

    migrated = migrate_session_payload(raw)

    assert migrated == expected
    assert raw == before_obj
    assert path.read_bytes() == before_bytes
    assert migrated["schema_version"] == SESSION_SCHEMA_V2
    assert migrated["snapshot_revision"] == 0
    assert migrated["last_committed_batch_id"] is None
    assert "commit_state" not in migrated


def test_v2_migration_is_idempotent_but_returns_copy():
    _, raw = load("session_schema_v2_p0b.json")
    migrated = migrate_session_payload(raw)
    assert migrated == raw
    assert migrated is not raw
    migrated["world_cursor"]["scene_id"] = "MUTATED"
    assert raw["world_cursor"]["scene_id"] == "OPENING_RYUYA_PROLOGUE_001"


def test_unknown_or_malformed_versions_are_rejected():
    _, raw = load("session_schema_v1_p0b.json")

    unknown = dict(raw)
    unknown["schema_version"] = "free_stage.session.v999"
    try:
        validate_session_payload(unknown)
    except UnsupportedSessionSchema:
        pass
    else:
        raise AssertionError("unknown future schema must be rejected")

    try:
        migrate_session_payload(raw, target_version="free_stage.session.v999")
    except UnsupportedSessionSchema:
        pass
    else:
        raise AssertionError("unknown target schema must be rejected")

    bad_v2 = dict(raw)
    bad_v2["schema_version"] = SESSION_SCHEMA_V2
    bad_v2["snapshot_revision"] = -1
    bad_v2["last_committed_batch_id"] = None
    try:
        validate_session_payload(bad_v2)
    except SessionSchemaError:
        pass
    else:
        raise AssertionError("malformed v2 snapshot revision must be rejected")


def test_downgrade_is_forbidden():
    _, raw = load("session_schema_v2_p0b.json")
    try:
        migrate_session_payload(raw, target_version=SESSION_SCHEMA_V1)
    except SessionSchemaError:
        pass
    else:
        raise AssertionError("v2 -> v1 downgrade must be forbidden")


def test_p2c_switches_free_stage_production_to_v2_without_destroying_v1_source():
    source = (ROOT / "runtime" / "free_stage_prototype.py").read_text(encoding="utf-8")
    assert "SESSION_SCHEMA_VERSION = session_schema.SESSION_SCHEMA_V2" in source
    assert "session_schema.migrate_session_payload" in source
    _, raw = load("session_schema_v1_p0b.json")
    before = copy.deepcopy(raw)
    migrated = migrate_session_payload(raw)
    assert raw == before
    assert migrated["schema_version"] == SESSION_SCHEMA_V2


if __name__ == "__main__":
    test_v1_to_v2_matches_fixture_without_mutating_source_bytes()
    test_v2_migration_is_idempotent_but_returns_copy()
    test_unknown_or_malformed_versions_are_rejected()
    test_downgrade_is_forbidden()
    test_p2c_switches_free_stage_production_to_v2_without_destroying_v1_source()
    print("PASS test_session_schema_migration")
