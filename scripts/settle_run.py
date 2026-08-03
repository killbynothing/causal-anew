# -*- coding: utf-8 -*-
"""EndRun settlement: delta_ledger → delta_sediment (deterministic, no LLM).

β v0.2 §二 §五. Fixed-bottom gate reads causal_constants; never softens those nodes.

Usage:
  python scripts/settle_run.py --run 1
  python scripts/settle_run.py --run 1 --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.softening_params import KIND_WEIGHT, S_MAX_DEFAULT, soft_field  # noqa: E402

DB_DEFAULT = ROOT / "data" / "world_truth.db"


def load_fixed_bottom_nodes(cur: sqlite3.Cursor) -> set[str]:
    """Union of dependency-chain event tokens on causal_constants."""
    nodes: set[str] = set()
    for (raw,) in cur.execute("SELECT dependency_chain FROM causal_constants"):
        if not raw:
            continue
        try:
            chain = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(chain, list):
            nodes.update(str(x) for x in chain)
    # also treat const_ids themselves as unsoftenable labels
    for (cid,) in cur.execute("SELECT const_id FROM causal_constants"):
        nodes.add(str(cid))
    return nodes


def classify_delta(
    row: sqlite3.Row,
    *,
    scar_keys_seen: set[tuple[str, str]],
    named_paths: set[str],
) -> str | None:
    """Return sediment kind or None (= evaporate).

    precedent: converged + named δ path receipt
    scar: same (node, emo) in another run, or nonempty emo_tag this run (v0 stub)
    """
    delta_id = str(row["delta_id"])
    node_id = str(row["node_id"] or "")
    emo = str(row["emo_tag"] or "")
    converged = int(row["converged"] or 0)

    if converged == 1 and delta_id in named_paths:
        return "precedent"

    key = (node_id, emo or "untagged")
    if key in scar_keys_seen:
        return "scar"
    if emo:
        return "scar"
    return None


def soft_field(weights: list[float], s_max: float = S_MAX_DEFAULT) -> float:
    """Re-export for callers/tests; implementation lives in softening_params."""
    from runtime.softening_params import soft_field as _sf

    return _sf(weights, s_max=s_max)


def settle(con: sqlite3.Connection, run: int, *, apply: bool) -> dict:
    cur = con.cursor()
    cur.row_factory = sqlite3.Row

    meta = cur.execute("SELECT * FROM run_meta WHERE run=?", (run,)).fetchone()
    if meta is None:
        raise SystemExit(f"[FAIL] run_meta missing for run={run}")

    fixed = load_fixed_bottom_nodes(cur)
    # named paths from receipts — table may not exist yet
    named_paths: set[str] = set()
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "receipts" in tables:
        for (payload,) in cur.execute(
            "SELECT payload FROM receipts WHERE run=? AND kind='delta_path_named'",
            (run,),
        ):
            try:
                obj = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            did = obj.get("delta_id") if isinstance(obj, dict) else None
            if did:
                named_paths.add(str(did))

    deltas = cur.execute(
        "SELECT * FROM delta_ledger WHERE run=? ORDER BY delta_id",
        (run,),
    ).fetchall()

    # scar across runs: (node_id, emo_tag) seen in other runs' ledger
    scar_keys_seen: set[tuple[str, str]] = set()
    for r in cur.execute(
        "SELECT node_id, emo_tag FROM delta_ledger WHERE run<>?",
        (run,),
    ):
        scar_keys_seen.add((str(r[0] or ""), str(r[1] or "untagged")))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proposed: list[dict] = []
    rejected: list[dict] = []

    for row in deltas:
        node_id = str(row["node_id"] or "")
        kind = classify_delta(row, scar_keys_seen=scar_keys_seen, named_paths=named_paths)
        if kind is None:
            continue
        if node_id in fixed:
            rejected.append(
                {
                    "delta_id": row["delta_id"],
                    "node_id": node_id,
                    "reason": "fixed_bottom_gate",
                }
            )
            continue
        weight = float(KIND_WEIGHT.get(kind, 0.0))
        payload = {
            "description": row["description"],
            "emo_tag": row["emo_tag"],
            "src_event": row["src_event"],
            "converged": int(row["converged"] or 0),
        }
        proposed.append(
            {
                "node_id": node_id,
                "kind": kind,
                "payload": json.dumps(payload, ensure_ascii=False),
                "cons_id": None,
                "weight": weight,
                "src_run": run,
                "src_delta": str(row["delta_id"]),
                "revoked": 0,
                "created_at": now,
            }
        )

    summary = {
        "run": run,
        "n_delta": len(deltas),
        "n_sediment": len(proposed),
        "n_rejected_fixed": len(rejected),
        "rejected": rejected,
        "sediment": proposed,
    }

    if apply:
        # idempotent re-settle: drop prior rows from this src_run then rewrite
        cur.execute("DELETE FROM delta_sediment WHERE src_run=?", (run,))
        for row in proposed:
            cur.execute(
                """
                INSERT INTO delta_sediment
                  (node_id, kind, payload, cons_id, weight, src_run, src_delta, revoked, created_at)
                VALUES
                  (:node_id, :kind, :payload, :cons_id, :weight, :src_run, :src_delta, :revoked, :created_at)
                """,
                row,
            )
        cur.execute(
            "UPDATE run_meta SET closed_at=?, final_delta_summary=? WHERE run=?",
            (now, json.dumps(summary, ensure_ascii=False), run),
        )
        con.commit()
        summary["applied"] = True
    else:
        summary["applied"] = False

    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=str(DB_DEFAULT))
    args = ap.parse_args()
    if args.run < 1:
        raise SystemExit("[FAIL] run must be >= 1")

    con = sqlite3.connect(args.db)
    try:
        out = settle(con, args.run, apply=args.apply)
    finally:
        con.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
