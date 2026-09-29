"""P0b in-memory session schema migration contract.

Production FreeStageSession remains on free_stage.session.v1 during P0b.
This module proves deterministic, non-destructive migration behavior before any
reader/writer is switched to v2.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

SESSION_SCHEMA_V1 = "free_stage.session.v1"
SESSION_SCHEMA_V2 = "free_stage.session.v2"
SUPPORTED_SESSION_SCHEMAS = (SESSION_SCHEMA_V1, SESSION_SCHEMA_V2)


class SessionSchemaError(ValueError):
    pass


class UnsupportedSessionSchema(SessionSchemaError):
    pass


def _require_object(raw: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SessionSchemaError("session payload must be an object")
    return copy.deepcopy(dict(raw))


def validate_session_payload(raw: Mapping[str, Any]) -> str:
    version = str(raw.get("schema_version", "") or "")
    if version not in SUPPORTED_SESSION_SCHEMAS:
        raise UnsupportedSessionSchema(f"unsupported session schema: {version or '<missing>'}")
    if not str(raw.get("session_id", "") or "").strip():
        raise SessionSchemaError("session_id is required")
    if version == SESSION_SCHEMA_V2:
        revision = raw.get("snapshot_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise SessionSchemaError("v2 requires snapshot_revision >= 0")
        last_batch = raw.get("last_committed_batch_id")
        if last_batch is not None and not isinstance(last_batch, str):
            raise SessionSchemaError("last_committed_batch_id must be string/null")
    return version


def migrate_session_payload(
    raw: Mapping[str, Any],
    *,
    target_version: str = SESSION_SCHEMA_V2,
) -> dict[str, Any]:
    """Return a migrated deep copy. Never mutates or writes the source payload."""
    if target_version not in SUPPORTED_SESSION_SCHEMAS:
        raise UnsupportedSessionSchema(f"unsupported target session schema: {target_version}")

    source = _require_object(raw)
    source_version = validate_session_payload(source)

    if source_version == target_version:
        return source
    if source_version == SESSION_SCHEMA_V2 and target_version == SESSION_SCHEMA_V1:
        raise SessionSchemaError("session schema downgrade is not supported")
    if source_version != SESSION_SCHEMA_V1 or target_version != SESSION_SCHEMA_V2:
        raise SessionSchemaError(f"no migration path: {source_version} -> {target_version}")

    migrated = copy.deepcopy(source)
    migrated["schema_version"] = SESSION_SCHEMA_V2
    # Only committed snapshot identity lives in the session payload. Pending
    # delivery/recovery state belongs to RuntimeStore's outbox sidecar.
    migrated["snapshot_revision"] = 0
    migrated["last_committed_batch_id"] = None
    validate_session_payload(migrated)
    return migrated
