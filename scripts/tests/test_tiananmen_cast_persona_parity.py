#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiananmen cast Seed parity: ARCH/BOUNDARY/MANNER scheduled + card seed ids resolve."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "world_truth.db"
CARD = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
CONS = [
    "C.xiuzai.WMAIN",
    "C.maki.WMAIN",
    "C.kakashi.WMAIN",
    "C.akito.WMAIN",
]


def main() -> int:
    fails: list[str] = []
    conn = sqlite3.connect(str(DB))
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pcs = card["persona_cards"]
    for cons in CONS:
        pc = pcs[cons]
        # no thin inline boundaries text
        b = pc.get("boundaries") or {}
        if b.get("hard") or b.get("soft") or b.get("style"):
            fails.append(f"{cons} still has inline boundaries text")
        if pc.get("voice_samples"):
            fails.append(f"{cons} still has voice_samples")
        for key in ("seed_hard_prop_ids", "seed_soft_prop_ids", "seed_manner_prop_ids"):
            for pid in b.get(key) or []:
                row = conn.execute(
                    "SELECT statement FROM propositions WHERE prop_id=?", (pid,)
                ).fetchone()
                if not row or not str(row[0] or "").strip():
                    fails.append(f"{cons} missing {pid}")
                sched = conn.execute(
                    "SELECT 1 FROM knowledge_schedule WHERE cons_id=? AND prop_id=? AND learn_ch<=0",
                    (cons, pid),
                ).fetchone()
                if not sched:
                    fails.append(f"{cons} unscheduled {pid}")
        for pid in pc.get("identity_seed_prop_ids") or []:
            row = conn.execute(
                "SELECT statement FROM propositions WHERE prop_id=?", (pid,)
            ).fetchone()
            if not row or not str(row[0] or "").strip():
                fails.append(f"{cons} identity missing {pid}")
        # must have ARCH + HOLD
        arch_n = conn.execute(
            "SELECT COUNT(*) FROM knowledge_schedule WHERE cons_id=? AND prop_id LIKE 'P.ARCH.%' AND learn_ch<=0",
            (cons,),
        ).fetchone()[0]
        hold_n = conn.execute(
            "SELECT COUNT(*) FROM knowledge_schedule WHERE cons_id=? AND prop_id LIKE 'REL.HOLD.%' AND learn_ch<=0",
            (cons,),
        ).fetchone()[0]
        if arch_n < 1:
            fails.append(f"{cons} no P.ARCH")
        if hold_n < 1:
            fails.append(f"{cons} no REL.HOLD")
        print(f"[ok] {cons} arch={arch_n} hold={hold_n}")
    conn.close()
    if fails:
        print("[FAIL]")
        for f in fails:
            print(" -", f)
        return 1
    print("[PASS] tiananmen_cast_persona_parity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
