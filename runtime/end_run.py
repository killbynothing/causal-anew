"""Knife 4: EndRun — settle this run and print a cold player receipt.

Receipt lists what happened. No emotion, no signature (those stay ★★★).
Idempotent: a closed run returns the same sheet without double-settling.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

def _desc_text(raw: str | None, node_id: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return node_id
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(obj, dict):
        return text
    return str(obj.get("desc") or obj.get("verdict") or node_id)


def build_receipt(
    con: sqlite3.Connection,
    run: int,
    *,
    opening_id: str = "",
    settle_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    meta = cur.execute("SELECT * FROM run_meta WHERE run=?", (int(run),)).fetchone()
    if meta is None:
        raise ValueError(f"run_meta missing for run={run}")
    rows = cur.execute(
        "SELECT delta_id, node_id, description, converged FROM delta_ledger WHERE run=? ORDER BY delta_id",
        (int(run),),
    ).fetchall()
    done = []
    for row in rows:
        node_id = str(row["node_id"] or "")
        done.append(
            {
                "delta_id": row["delta_id"],
                "node_id": node_id,
                "text": _desc_text(row["description"], node_id),
                "converged": int(row["converged"] or 0),
            }
        )
    summary = settle_summary
    if summary is None:
        raw = meta["final_delta_summary"]
        if raw:
            try:
                parsed = json.loads(raw)
                summary = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                summary = {}
        else:
            summary = {}
    rejected = [
        {"node_id": str(item.get("node_id") or ""), "reason": "fixed_bottom"}
        for item in list(summary.get("rejected") or [])
        if isinstance(item, dict)
    ]
    n_sediment = summary.get("n_sediment")
    if n_sediment is None:
        n_sediment = cur.execute(
            "SELECT COUNT(*) FROM delta_sediment WHERE src_run=?", (int(run),)
        ).fetchone()[0]
    return {
        "run": int(run),
        "opening_id": str(opening_id or meta["opening_id"] or ""),
        "closed_at": meta["closed_at"],
        "done": done,
        "rejected_fixed": rejected,
        "n_delta": int(summary.get("n_delta", len(done))),
        "n_sediment": int(n_sediment),
        "n_rejected_fixed": int(summary.get("n_rejected_fixed", len(rejected))),
    }


def close_run(
    db_path: Path | str,
    run: int,
    *,
    opening_id: str = "",
) -> dict[str, Any]:
    """Settle + close run_meta. Second call returns the existing receipt."""
    run = int(run)
    if run < 1:
        raise ValueError("run=0 is read-only; cannot close canon")
    from scripts.settle_run import settle

    con = sqlite3.connect(str(db_path), timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        # One write transaction owns "is it already closed?" + settlement +
        # receipt. Concurrent closers serialize here instead of both settling.
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT * FROM run_meta WHERE run=?",
            (run,),
        ).fetchone()
        if existing is None:
            raise ValueError(f"run_meta missing for run={run}")
        if existing["closed_at"]:
            receipt = build_receipt(con, run, opening_id=opening_id)
            con.commit()
            return receipt

        summary = settle(con, run, apply=True, commit=False)
        receipt = build_receipt(con, run, opening_id=opening_id, settle_summary=summary)
        con.commit()
        return receipt
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
