"""Filesystem adapter for runtime session snapshots.

It owns paths and JSON I/O only.  Session state shape remains owned by the
session-domain layer, so this module cannot create a second state model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.file_locks import SESSION_FILE_LOCK


class RuntimeStore:
    def __init__(self, state_dir: Path | str, session_id: str) -> None:
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / f"{session_id}.json"

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

    def delete(self) -> None:
        with SESSION_FILE_LOCK:
            if self.state_path.exists():
                self.state_path.unlink()
