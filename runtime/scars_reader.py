"""Knife 5: Read Scars ? cross-run sediment & softening for next run.

Principles:
1. run=1 reads 0 scars (S?0).
2. run>1 reads delta_sediment with src_run < current_run and IFNULL(revoked,0)=0.
3. Fixed-bottom nodes force S?0 (Red line 3: never soften).
4. Subtle ambient scar is strictly sensory/physical (H4: zero system/run/spoiler leak).
5. Actor mental packet never imports previous run facts (zero cross-run contamination).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from runtime.softening_params import (
    KIND_WEIGHT,
    S_MAX_DEFAULT,
    compute_S,
    effective_combine_threshold,
    soft_field,
)
from scripts.settle_run import load_fixed_bottom_nodes


_AMBIENT_SCAR_TEXTURES = [
    "\u7a7a\u6c14\u91cc\u6b8b\u7559\u7740\u4e00\u4e1d\u96be\u4ee5\u8a00\u8bf4\u7684\u6ede\u91cd\uff0c\u65e7\u6728\u684c\u89d2\u8fb9\u7f18\u9690\u7ea6\u6709\u88ab\u53cd\u590d\u6469\u6332\u7684\u6d45\u75d5\u3002",
    "\u96e8\u58f0\u64e6\u8fc7\u7a97\u6a90\u7684\u8282\u594f\u6c89\u95f7\uff0c\u5468\u56f4\u7684\u6c1b\u56f4\u5e26\u7740\u4e00\u79cd\u82e5\u6709\u82e5\u65e0\u7684\u5fae\u5f31\u65e2\u89c6\u611f\u3002",
    "\u7a97\u5916\u5149\u7ebf\u5728\u6c34\u6d3c\u91cc\u6d6e\u6c89\uff0c\u7a7a\u6c14\u4e2d\u5f25\u6f2b\u7740\u65e7\u7eb8\u4e0e\u6f6e\u6e7f\u6ce5\u571f\u4ea4\u7ec7\u7684\u9648\u65e7\u6c14\u606f\u3002",
]


def read_run_scars(
    db_path: Path | str | None,
    node_id: str,
    *,
    current_run: int = 1,
    s_max: float = S_MAX_DEFAULT,
) -> dict[str, Any]:
    """Read sediment from prior runs (< current_run) for node_id."""
    current_run = int(current_run)
    node = str(node_id or "").strip()

    empty_res: dict[str, Any] = {
        "run": current_run,
        "node_id": node,
        "S": 0.0,
        "n_scars": 0,
        "n_precedents": 0,
        "is_fixed_bottom": False,
        "has_scars": False,
        "ambient_scar": None,
        "weights": [],
    }

    if current_run <= 1 or not node or not db_path:
        return empty_res

    path = Path(db_path)
    if not path.is_file():
        return empty_res

    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(str(path))
        cur = con.cursor()
        fixed_bottom = load_fixed_bottom_nodes(cur)
        if node in fixed_bottom:
            empty_res["is_fixed_bottom"] = True
            return empty_res

        rows = cur.execute(
            "SELECT weight, kind FROM delta_sediment "
            "WHERE node_id=? AND src_run < ? AND IFNULL(revoked,0)=0",
            (node, current_run),
        ).fetchall()
    except sqlite3.Error:
        return empty_res
    finally:
        if con is not None:
            con.close()

    if not rows:
        return empty_res

    weights: list[float] = []
    n_scars = 0
    n_precedents = 0

    for weight, kind in rows:
        k = str(kind or "")
        if k == "scar":
            n_scars += 1
            weights.append(float(weight if weight is not None else KIND_WEIGHT.get("scar", 0.10)))
        elif k == "precedent":
            n_precedents += 1
            weights.append(float(weight if weight is not None else KIND_WEIGHT.get("precedent", 0.25)))

    if not weights:
        return empty_res

    s_val = soft_field(weights, s_max=s_max)
    idx = (abs(hash(node)) + current_run) % len(_AMBIENT_SCAR_TEXTURES)
    ambient_scar = _AMBIENT_SCAR_TEXTURES[idx] if s_val > 0.0 else None

    return {
        "run": current_run,
        "node_id": node,
        "S": round(s_val, 4),
        "n_scars": n_scars,
        "n_precedents": n_precedents,
        "is_fixed_bottom": False,
        "has_scars": (n_scars + n_precedents) > 0,
        "ambient_scar": ambient_scar,
        "weights": weights,
    }


def compute_node_effective_threshold(
    contract: dict[str, Any],
    delta_count: int,
    *,
    node_id: str | None = None,
    db_path: Path | str | None = None,
    current_run: int = 1,
) -> float:
    """Convenience helper computing effective threshold with prior run scars."""
    node = str(node_id or (contract or {}).get("node_id", "")).strip()
    scar_info = read_run_scars(db_path, node, current_run=current_run)
    return effective_combine_threshold(
        contract,
        delta_count,
        node_id=node,
        sediment_S=scar_info["S"],
    )
