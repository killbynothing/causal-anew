# -*- coding: utf-8 -*-
"""β soft-field parameters (human-cut 2026-08-03 draft weights).

S(node) = min(S_max, 1 − Π_i (1 − w_i))
Fixed-bottom nodes force S ≡ 0 (never accumulate sediment).

Director threshold (β v0.2):
  threshold = floor + (init − floor) · (1 − S(node))
Within-run δ count softening still applies on top when per_delta is set.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

W_PRECEDENT = 0.25
W_SCAR = 0.10
S_MAX_DEFAULT = 0.6

KIND_WEIGHT = {
    "precedent": W_PRECEDENT,
    "scar": W_SCAR,
    "unlock": 0.0,  # unlock opens affordance; does not soften threshold
    "witness": 0.0,  # observer memory; never softens world
}

_SOFTENING_KINDS = frozenset({"precedent", "scar"})


def soft_field(weights: list[float], s_max: float = S_MAX_DEFAULT) -> float:
    acc = 1.0
    for w in weights:
        acc *= 1.0 - float(w)
    return min(float(s_max), 1.0 - acc)


def threshold_from_S(init: float, floor: float, S: float) -> float:
    """Cross-run soft threshold. S=0 → init; S→1 → floor."""
    init_f = float(init)
    floor_f = float(floor)
    s = max(0.0, min(1.0, float(S)))
    return floor_f + (init_f - floor_f) * (1.0 - s)


def sediment_weights_for_node(
    db_path: str | Path,
    node_id: str,
) -> list[float]:
    path = Path(db_path)
    node = str(node_id or "").strip()
    if not node or not path.is_file():
        return []
    try:
        con = sqlite3.connect(str(path))
        rows = con.execute(
            "SELECT weight, kind FROM delta_sediment "
            "WHERE node_id=? AND IFNULL(revoked,0)=0",
            (node,),
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return []
    out: list[float] = []
    for weight, kind in rows:
        if str(kind or "") not in _SOFTENING_KINDS:
            continue
        try:
            out.append(float(weight))
        except (TypeError, ValueError):
            continue
    return out


def compute_S(
    db_path: str | Path | None,
    node_id: str,
    *,
    s_max: float = S_MAX_DEFAULT,
    fixed_bottom_nodes: set[str] | None = None,
) -> float:
    """S(node) from non-revoked sediment; fixed-bottom → 0; empty → 0 (run=1)."""
    node = str(node_id or "").strip()
    if not node:
        return 0.0
    if fixed_bottom_nodes and node in fixed_bottom_nodes:
        return 0.0
    if not db_path:
        return 0.0
    weights = sediment_weights_for_node(db_path, node)
    if not weights:
        return 0.0
    return soft_field(weights, s_max=s_max)


def effective_combine_threshold(
    contract: dict[str, Any],
    delta_count: int,
    *,
    node_id: str | None = None,
    db_path: str | Path | None = None,
    sediment_S: float | None = None,
    fixed_bottom_nodes: set[str] | None = None,
) -> float:
    """Director combine threshold: β S soft + within-run per_delta, floored.

    Empty sediment ⇒ S≡0 ⇒ cross-run term equals base (run=1 safe).
    """
    base = float(contract.get("combine_threshold", 2) or 2)
    soft = contract.get("softening", {}) or {}
    floor = float(soft.get("floor", 1) or 1)
    per = int(soft.get("per_delta", 3) or 0)
    node = str(node_id or contract.get("node_id") or "").strip()
    if sediment_S is None:
        sediment_S = compute_S(
            db_path,
            node,
            fixed_bottom_nodes=fixed_bottom_nodes,
        )
    cross = threshold_from_S(base, floor, float(sediment_S or 0.0))
    within = (int(delta_count) // per) if per else 0
    eff = cross - within
    # Path-count thresholds are whole numbers; softening must not go below floor.
    return max(floor, float(math.floor(eff + 1e-9)))
