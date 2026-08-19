"""Open a play-time run: append-only run_meta (run>=1). Never touches run=0."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KINDS = frozenset({"fresh", "beta", "fork"})
INHERIT_LEVELS = frozenset({0, 1, 2})


def profile_hash(profile: dict[str, Any] | None) -> str:
    payload = profile if isinstance(profile, dict) else {}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def next_run_no(con: sqlite3.Connection) -> int:
    raw = con.execute("SELECT COALESCE(MAX(run), 0) FROM run_meta").fetchone()[0]
    n = int(raw or 0) + 1
    if n < 1:
        raise ValueError("run=0 is read-only; runtime runs start at 1")
    return n


def get_run(db_path: Path | str, run: int) -> dict[str, Any] | None:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT * FROM run_meta WHERE run=?", (int(run),)).fetchone()
        return dict(row) if row is not None else None
    finally:
        con.close()


def open_run(
    db_path: Path | str,
    *,
    opening_id: str,
    player_line: str = "a_qi",
    kind: str = "fresh",
    inherit_level: int = 0,
    parent_run: int = 0,
    fork_event: str | None = None,
    player_profile_hash: str = "",
) -> dict[str, Any]:
    """Insert one run_meta row. Sequential ids. Does not mutate run=0 canon rows."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    inherit_level = int(inherit_level)
    if inherit_level not in INHERIT_LEVELS:
        raise ValueError("inherit_level must be 0, 1, or 2")
    parent_run = int(parent_run)
    if parent_run < 0:
        raise ValueError("parent_run must be >= 0")

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("BEGIN IMMEDIATE")
        run_no = next_run_no(con)
        opened_at = _now_iso()
        con.execute(
            """
            INSERT INTO run_meta (
                run, parent_run, kind, fork_event, inherit_level,
                player_line, opening_id, player_profile_hash, opened_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_no,
                parent_run,
                kind,
                fork_event,
                inherit_level,
                str(player_line or "a_qi"),
                str(opening_id or "") or None,
                str(player_profile_hash or "") or None,
                opened_at,
            ),
        )
        con.commit()
        return {
            "run": run_no,
            "parent_run": parent_run,
            "kind": kind,
            "fork_event": fork_event,
            "inherit_level": inherit_level,
            "player_line": str(player_line or "a_qi"),
            "opening_id": str(opening_id or "") or None,
            "player_profile_hash": str(player_profile_hash or "") or None,
            "opened_at": opened_at,
            "closed_at": None,
            "final_delta_summary": None,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
