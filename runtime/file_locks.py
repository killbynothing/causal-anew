# -*- coding: utf-8 -*-
"""Shared process-local locks for console/runtime file writes."""
from __future__ import annotations

from threading import RLock

CONFIG_LOCK = RLock()
SESSION_FILE_LOCK = RLock()
SCENE_LOG_LOCK = RLock()
STATE_LOCK = RLock()
DELTA_LEDGER_LOCK = RLock()

_SESSION_REQUEST_LOCKS_GUARD = RLock()
_SESSION_REQUEST_LOCKS: dict[str, RLock] = {}


def session_request_lock(session_id: str) -> RLock:
    """One process-local lock per session for load→reduce→save serialization."""
    key = str(session_id or "").strip()
    if not key:
        raise ValueError("session_id is required for request lock")
    with _SESSION_REQUEST_LOCKS_GUARD:
        lock = _SESSION_REQUEST_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _SESSION_REQUEST_LOCKS[key] = lock
        return lock

