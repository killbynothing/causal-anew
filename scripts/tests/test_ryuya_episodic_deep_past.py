# -*- coding: utf-8 -*-
"""Ryuya episodic deep-past bank + candidate/activation separation (zero LLM)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime import actor_context_v2 as acv2  # noqa: E402

DB = ROOT / "data" / "world_truth.db"

W1_REQUIRED = {f"W1-M{i}" for i in range(1, 14)}
WM_REQUIRED = {f"WM-M{i}" for i in range(1, 17)}


def _ids_for(cons: str) -> set[str]:
    con = sqlite3.connect(str(DB))
    rows = con.execute(
        "SELECT anchor FROM slow_memory WHERE cons_id=? AND available_ch IS NOT NULL",
        (cons,),
    ).fetchall()
    con.close()
    out: set[str] = set()
    for (anchor,) in rows:
        a = str(anchor or "")
        if a.startswith("[") and "]" in a:
            out.add(a[1 : a.index("]")])
    return out


def test_ryuya_episodic_bank_complete():
    assert DB.exists(), "world_truth.db missing"
    w1 = _ids_for("C.ryuya.W1")
    wm = _ids_for("C.ryuya.WMAIN")
    missing_w1 = sorted(W1_REQUIRED - w1)
    missing_wm = sorted(WM_REQUIRED - wm)
    assert not missing_w1, f"W1 missing {missing_w1}"
    assert not missing_wm, f"WMAIN missing {missing_wm}"
    # no orphans on ryuya
    con = sqlite3.connect(str(DB))
    orphans = con.execute(
        """
        SELECT mem_id, anchor FROM slow_memory
        WHERE cons_id IN ('C.ryuya.W1','C.ryuya.WMAIN')
          AND available_ch IS NULL AND (src_event IS NULL OR src_event='')
        """
    ).fetchall()
    con.close()
    assert not orphans, f"ryuya orphan slow_memory: {orphans}"


def test_fetch_candidate_pool_not_tiny():
    rows = acv2.fetch_slow_memory("C.ryuya.W1", ch_anchor=0, run_no=1, top_k=64, include_anchor=True)
    assert len(rows) >= 13, f"expected full W1 pool, got {len(rows)}"
    # activation still narrows
    act = acv2.activate_memory_candidates(
        [],
        rows,
        "电梯 跳转 张尘 带你回家",
        slow_activation_cues={},
    )
    # without cues, cue-activation may be empty; cos+emo path is caller-side
    assert "slow_memory_activated" in act
    assert "slow_memory_withheld" in act


def test_opening_whitelist_projections_present():
    """Married/brother surface lines exist for gated speak (projection_text)."""
    con = sqlite3.connect(str(DB))
    married = con.execute(
        """
        SELECT COUNT(*) FROM slow_memory
        WHERE cons_id='C.ryuya.WMAIN' AND projection_text LIKE '%结婚%'
        """
    ).fetchone()[0]
    brother = con.execute(
        """
        SELECT COUNT(*) FROM slow_memory
        WHERE cons_id IN ('C.ryuya.W1','C.ryuya.WMAIN')
          AND projection_text LIKE '%弟弟%'
        """
    ).fetchone()[0]
    con.close()
    assert married >= 1
    assert brother >= 1


if __name__ == "__main__":
    test_ryuya_episodic_bank_complete()
    test_fetch_candidate_pool_not_tiny()
    test_opening_whitelist_projections_present()
    print("OK test_ryuya_episodic_deep_past")
