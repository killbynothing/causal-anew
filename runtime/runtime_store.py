"""Filesystem adapter for runtime session snapshots.

It owns paths and JSON I/O only.  Session state shape remains owned by the
session-domain layer, so this module cannot create a second state model.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runtime.causal_protocol import CommitCursor, CommitProtocolError
from runtime.file_locks import SESSION_FILE_LOCK


class RuntimeStoreError(RuntimeError):
    pass


class RuntimeStore:
    def __init__(self, state_dir: Path | str, session_id: str) -> None:
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / f"{session_id}.json"
        # P0b outbox sidecar. FreeStageSession does not use it yet.
        self.commit_state_path = self.state_dir / f"{session_id}.commit.json"

    def load(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return raw if isinstance(raw, dict) else None

    def save(self, payload: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with SESSION_FILE_LOCK:
            self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_commit_cursor(self) -> CommitCursor:
        """Strictly load the P0b pending/ack outbox cursor.

        Missing means no prepared work. Corruption is an error, never silently
        treated as a fresh cursor.
        """
        if not self.commit_state_path.exists():
            return CommitCursor()
        try:
            raw = json.loads(self.commit_state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise RuntimeStoreError("commit cursor file must contain an object")
            return CommitCursor.from_dict(raw)
        except (json.JSONDecodeError, OSError, CommitProtocolError, ValueError) as exc:
            if isinstance(exc, RuntimeStoreError):
                raise
            raise RuntimeStoreError(f"invalid commit cursor: {exc}") from exc

    def save_commit_cursor(
        self,
        cursor: CommitCursor,
        *,
        failpoint: str | None = None,
    ) -> None:
        """Atomically replace the outbox sidecar.

        failpoint='after_temp_write' exists only for deterministic P0b fault
        injection tests. This method is not production-wired yet.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.commit_state_path.with_name(self.commit_state_path.name + ".tmp")
        payload = json.dumps(cursor.to_dict(), ensure_ascii=False, indent=2)
        with SESSION_FILE_LOCK:
            try:
                temp_path.write_text(payload, encoding="utf-8")
                if failpoint == "after_temp_write":
                    raise RuntimeStoreError("injected failure after temp write")
                if failpoint not in (None, "after_temp_write"):
                    raise RuntimeStoreError(f"unknown failpoint: {failpoint}")
                os.replace(temp_path, self.commit_state_path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()

    def delete(self) -> None:
        with SESSION_FILE_LOCK:
            if self.state_path.exists():
                self.state_path.unlink()
