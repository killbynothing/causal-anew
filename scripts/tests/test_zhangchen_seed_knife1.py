# -*- coding: utf-8 -*-
"""Zhang Chen knife-1 Seed + knowledge idle-fill guard (zero LLM)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime import actor_context_v2 as acv2  # noqa: E402

DB = ROOT / "data" / "world_truth.db"
CONS = "C.zhangchen.WMAIN"

REQUIRED_PROPS = {
    "P.ARCH.zhangchen.core_thin",
    "P.ARCH.zhangchen.onion.L0_surface",
    "P.ARCH.zhangchen.onion.L1_resist_wg",
    "P.ARCH.zhangchen.onion.L2_ds_wg_net",
    "P.ARCH.zhangchen.onion.L3_dust_lt",
    "P.MANNER.zhangchen.voice_rule",
    "P.BOUNDARY.zhangchen.hard.load_bearing",
    "P.ACT.zhangchen.body.allow",
    "P.ACT.zhangchen.pref",
    "REL.IDENTITY.zhangchen.weichu_boss",
    "REL.IDENTITY.zhangchen.ryuya",
    "REL.HOLD.zhangchen.to_weichu",
    "REL.HOLD.zhangchen.to_ryuya",
}


def test_zhangchen_knife1_seed_scheduled():
    assert DB.exists()
    con = sqlite3.connect(str(DB))
    rows = {
        r[0]
        for r in con.execute(
            "SELECT prop_id FROM knowledge_schedule WHERE cons_id=? AND learn_ch<=9",
            (CONS,),
        )
    }
    con.close()
    missing = sorted(REQUIRED_PROPS - rows)
    assert not missing, f"missing scheduled props: {missing}"


def test_zhangchen_persona_core_from_seed():
    core = acv2.resolve_persona_core(CONS, ch_anchor=9)
    assert core.get("origin") == "seed"
    assert core.get("manners"), "expected ARCH/MANNER facets"
    assert core.get("boundaries"), "expected BOUNDARY facets"
    manners = "\n".join(core.get("manners") or [])
    assert "哥哥" not in manners, "Zhang Chen seed must not claim 龙也 as brother"
    ryuya_rel = acv2.fetch_identity_relations(CONS, 9)
    facts = " ".join(r.get("fact", "") for r in ryuya_rel)
    assert "带进世府" in facts
    assert "哥哥" not in facts


def test_knowledge_idle_no_deep_flood():
    """Hire-scene idle query must not dump captivity/DS/pact into Top-K."""
    rows = acv2.fetch_relevant_knowledge(
        CONS, ch_anchor=9, query_text="应聘 填表 轻松", top_k=8
    )
    ids = [r["prop_id"] for r in rows]
    assert len(rows) <= 2, f"idle flood: {ids}"
    banned = {
        "K.C.zhangchen.WMAIN.K0-03",
        "K.C.zhangchen.WMAIN.K0-07",
        "K.C.zhangchen.WMAIN.K0-08",
        "P.DS_PUPPET",
    }
    assert not (banned & set(ids)), f"deep K in idle Top-K: {ids}"


def test_knowledge_cue_can_still_hit():
    rows = acv2.fetch_relevant_knowledge(
        CONS, ch_anchor=9, query_text="龙也 约定 摧毁", top_k=8
    )
    ids = [r["prop_id"] for r in rows]
    assert "K.C.zhangchen.WMAIN.K0-07" in ids, f"cue should surface pact knowledge, got {ids}"
    assert all(r["relevance"] > 0 for r in rows)


if __name__ == "__main__":
    test_zhangchen_knife1_seed_scheduled()
    test_zhangchen_persona_core_from_seed()
    test_knowledge_idle_no_deep_flood()
    test_knowledge_cue_can_still_hit()
    print("OK test_zhangchen_seed_knife1")
