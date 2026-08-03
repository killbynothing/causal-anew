"""Append-only runtime overlay; canonical world truth is never a session write target."""
from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


def _connect_runtime(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_bonds (
            run INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            action_flag TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            PRIMARY KEY (run, character_id, action_flag)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_storylet_events (
            run INTEGER NOT NULL CHECK (run >= 1),
            worldline TEXT NOT NULL,
            event_id TEXT NOT NULL,
            storylet_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            PRIMARY KEY (run, worldline, event_id)
        )
        """
    )
    return conn


def _legacy_rows(legacy_db_path: Path | None) -> list[tuple[int, str, str, str]]:
    if legacy_db_path is None or not legacy_db_path.exists():
        return []
    try:
        uri = f"{legacy_db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_bonds'"
            ).fetchone()
            if not exists:
                return []
            return [tuple(row) for row in conn.execute("SELECT run, character_id, action_flag, timestamp FROM run_bonds")]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def bootstrap_runtime_state(runtime_db_path: Path, *, legacy_db_path: Path | None = None) -> None:
    """Copy legacy runtime rows out once/idempotently; never mutate the legacy DB."""
    conn = _connect_runtime(runtime_db_path)
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO run_bonds (run, character_id, action_flag, timestamp) VALUES (?, ?, ?, ?)",
            _legacy_rows(legacy_db_path),
        )
        conn.commit()
    finally:
        conn.close()


def append_run_bonds(
    runtime_db_path: Path,
    *,
    run_no: int,
    branch_progress: list[str],
    legacy_db_path: Path | None = None,
) -> None:
    bootstrap_runtime_state(runtime_db_path, legacy_db_path=legacy_db_path)
    bond_mapping = {
        "choiceA_brace": "kakashi",
        "B1_dog": "xiuzai",
        "bp_invited": "akito",
    }
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [(int(run_no), bond_mapping[flag], flag, now) for flag in branch_progress if flag in bond_mapping]
    if not rows:
        return
    conn = _connect_runtime(runtime_db_path)
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO run_bonds (run, character_id, action_flag, timestamp) VALUES (?, ?, ?, ?)", rows
        )
        conn.commit()
    finally:
        conn.close()


def load_run_bonds(runtime_db_path: Path, *, legacy_db_path: Path | None = None) -> list[tuple[int, str, str, str]]:
    bootstrap_runtime_state(runtime_db_path, legacy_db_path=legacy_db_path)
    conn = _connect_runtime(runtime_db_path)
    try:
        return [tuple(row) for row in conn.execute("SELECT run, character_id, action_flag, timestamp FROM run_bonds")]
    finally:
        conn.close()


def append_storylet_event(
    runtime_db_path: Path,
    *,
    run_no: int,
    worldline: str,
    event_id: str,
    storylet_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Append one run-local storylet event; canonical DBs are never opened here."""
    if int(run_no) < 1:
        raise ValueError("ephemeral storylets may only exist in run >= 1")
    required = {
        "worldline": worldline,
        "event_id": event_id,
        "storylet_id": storylet_id,
        "event_type": event_type,
    }
    if any(not str(value).strip() for value in required.values()):
        raise ValueError("storylet event identity fields must not be blank")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect_runtime(runtime_db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO runtime_storylet_events
            (run, worldline, event_id, storylet_id, event_type, payload_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(run_no), str(worldline), str(event_id), str(storylet_id), str(event_type),
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_storylet_events(
    runtime_db_path: Path, *, run_no: int, worldline: str,
) -> list[dict]:
    """Read ordered, run/worldline-isolated storylet events."""
    if int(run_no) < 1:
        return []
    conn = _connect_runtime(runtime_db_path)
    try:
        rows = conn.execute(
            """
            SELECT event_id, storylet_id, event_type, payload_json, timestamp
            FROM runtime_storylet_events
            WHERE run = ? AND worldline = ?
            ORDER BY rowid ASC
            """,
            (int(run_no), str(worldline)),
        ).fetchall()
        return [
            {
                "event_id": str(event_id),
                "storylet_id": str(storylet_id),
                "event_type": str(event_type),
                "payload": json.loads(payload_json),
                "timestamp": str(timestamp),
            }
            for event_id, storylet_id, event_type, payload_json, timestamp in rows
        ]
    finally:
        conn.close()
