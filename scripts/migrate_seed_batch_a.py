#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 batch A: migrate opening identity relations + clean items.note run-domain facts.

★★★ content: statements migrated from free_stage cards (authored_opening / canon cites).
No new plot invented. Report any residual authorship in STATUS.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "world_truth.db"

# Opening 5 consciousnesses — learn_ch=0 so ch_anchor=0 projects them.
# Sources: card identity_relations + existing novel cites where family canon.
RELATIONS = (
    # --- 龙也 W1 (prologue) ---
    {
        "cons_id": "C.ryuya.W1",
        "prop_id": "REL.IDENTITY.ryuya.xiuzai_brother",
        "statement": "折原修哉是我亲弟弟。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_ryuya_prologue.json; canon family (cf. source/novel_1-69.md maki/weichu cites)",
    },
    {
        "cons_id": "C.ryuya.W1",
        "prop_id": "REL.IDENTITY.ryuya.maki_cousin",
        "statement": "折原真纪是我表姐。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_ryuya_prologue.json; canon family",
    },
    {
        "cons_id": "C.ryuya.W1",
        "prop_id": "REL.IDENTITY.ryuya.weichu_wife",
        "statement": "魏初是我的妻子。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_ryuya_prologue.json; canon marriage",
    },
    {
        "cons_id": "C.ryuya.W1",
        "prop_id": "REL.IDENTITY.ryuya.zhangchen_entrust",
        "statement": "张尘不是家人；是我托对方日后若碰巧遇见可以照顾一下的人。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_ryuya_prologue.json (authored_opening)",
    },
    {
        "cons_id": "C.ryuya.W1",
        "prop_id": "REL.IDENTITY.ryuya.pendant_from_xiuzai",
        "statement": "这枚古铜色挂坠是第一世界的修哉交给我的；临别要当面交给眼前这个朋友。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_ryuya_prologue.json (authored_opening+human_cut 2026-08-01)",
    },
    # --- 修哉 ---
    {
        "cons_id": "C.xiuzai.WMAIN",
        "prop_id": "REL.IDENTITY.xiuzai.maki_cousin",
        "statement": "折原真纪是我表姐。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json; canon family",
    },
    {
        "cons_id": "C.xiuzai.WMAIN",
        "prop_id": "REL.IDENTITY.xiuzai.ryuya_brother",
        "statement": "折原龙也是我哥哥；眼下不对生人展开。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json; canon family",
    },
    {
        "cons_id": "C.xiuzai.WMAIN",
        "prop_id": "REL.IDENTITY.xiuzai.kakashi_friend",
        "statement": "坂本晴明是同学同旅，很安静，话很少。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    {
        "cons_id": "C.xiuzai.WMAIN",
        "prop_id": "REL.IDENTITY.xiuzai.akito_friend",
        "statement": "川口秋人是同学；相机跟得很勤。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    # --- 真纪（learn_ch=0 增补同行；已有 maki.ryuya_xiuzai @ learn_ch=1 保留）---
    {
        "cons_id": "C.maki.WMAIN",
        "prop_id": "REL.IDENTITY.maki.xiuzai_cousin_brother",
        "statement": "折原修哉是我表弟，我把他当弟弟看。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json; canon family",
    },
    {
        "cons_id": "C.maki.WMAIN",
        "prop_id": "REL.IDENTITY.maki.ryuya_cousin",
        "statement": "折原龙也是我表弟、修哉的亲哥哥；眼下不对外人展开。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json; canon family",
    },
    {
        "cons_id": "C.maki.WMAIN",
        "prop_id": "REL.IDENTITY.maki.akito_travel",
        "statement": "川口秋人是这次同行的人。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    {
        "cons_id": "C.maki.WMAIN",
        "prop_id": "REL.IDENTITY.maki.kakashi_travel",
        "statement": "坂本晴明是这次同行的人。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    # --- 晴明 ---
    {
        "cons_id": "C.kakashi.WMAIN",
        "prop_id": "REL.IDENTITY.kakashi.xiuzai_friend",
        "statement": "折原修哉是这次同旅的同学；话散、不太住嘴。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    {
        "cons_id": "C.kakashi.WMAIN",
        "prop_id": "REL.IDENTITY.kakashi.akito_friend",
        "statement": "川口秋人是同学；爱拍、有时太实诚。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    {
        "cons_id": "C.kakashi.WMAIN",
        "prop_id": "REL.IDENTITY.kakashi.maki_acquaintance",
        "statement": "折原真纪是修哉的表姐，过去追着拍升旗的。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    # --- 秋人 ---
    {
        "cons_id": "C.akito.WMAIN",
        "prop_id": "REL.IDENTITY.akito.maki_cousin_ref",
        "statement": "折原真纪是修哉的表姐，我叫她表姐；过去追着拍升旗。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    {
        "cons_id": "C.akito.WMAIN",
        "prop_id": "REL.IDENTITY.akito.xiuzai_friend",
        "statement": "折原修哉是同学，爱摊开话题。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
    {
        "cons_id": "C.akito.WMAIN",
        "prop_id": "REL.IDENTITY.akito.kakashi_friend",
        "statement": "坂本晴明是同学，很安静。",
        "learn_ch": 0,
        "source": "runtime/free_stage_card_tiananmen_v2.json (authored_tiananmen)",
    },
)

ITEM_NOTE_UPDATES = {
    # before → after (strip run-domain「玩家持有」类)
    "I.PENDANT_ANCHOR": (
        "玩家持有；龙也(W1前台)交付",
        "LT_ANCHOR 信物挂坠；物定义在 Seed；持有关系由 run/item_custody 记载，不在 Seed note。来历：第一世界折原修哉交予龙也(W1)。",
    ),
}

# Card rewrite: remove duplicated identity_relations / body_props text; point to Seed IDs.
CARD_SEED_REFS = {
    "runtime/free_stage_card_ryuya_prologue.json": {
        "cons": "C.ryuya.W1",
        "identity_seed_ids": [
            "REL.IDENTITY.ryuya.xiuzai_brother",
            "REL.IDENTITY.ryuya.maki_cousin",
            "REL.IDENTITY.ryuya.weichu_wife",
            "REL.IDENTITY.ryuya.zhangchen_entrust",
            "REL.IDENTITY.ryuya.pendant_from_xiuzai",
        ],
        "body_prop_seed_ids": ["I.PENDANT_ANCHOR"],
    },
    "runtime/free_stage_card_tiananmen_v2.json": {
        "C.maki.WMAIN": [
            "REL.IDENTITY.maki.xiuzai_cousin_brother",
            "REL.IDENTITY.maki.ryuya_cousin",
            "REL.IDENTITY.maki.akito_travel",
            "REL.IDENTITY.maki.kakashi_travel",
        ],
        "C.kakashi.WMAIN": [
            "REL.IDENTITY.kakashi.xiuzai_friend",
            "REL.IDENTITY.kakashi.akito_friend",
            "REL.IDENTITY.kakashi.maki_acquaintance",
        ],
        "C.xiuzai.WMAIN": [
            "REL.IDENTITY.xiuzai.maki_cousin",
            "REL.IDENTITY.xiuzai.ryuya_brother",
            "REL.IDENTITY.xiuzai.kakashi_friend",
            "REL.IDENTITY.xiuzai.akito_friend",
        ],
        "C.akito.WMAIN": [
            "REL.IDENTITY.akito.maki_cousin_ref",
            "REL.IDENTITY.akito.xiuzai_friend",
            "REL.IDENTITY.akito.kakashi_friend",
        ],
    },
}


def apply_db(db_path: Path, dry_run: bool = False) -> list[str]:
    diff: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        before_items = {
            r[0]: r[1]
            for r in conn.execute("SELECT item_id, note FROM items")
        }
        for row in RELATIONS:
            diff.append(f"+PROP {row['prop_id']} @ {row['cons_id']} learn_ch={row['learn_ch']}: {row['statement']}")
            if dry_run:
                continue
            conn.execute(
                """
                INSERT INTO propositions (prop_id, statement, spoiler_tier, canon_src)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(prop_id) DO UPDATE SET
                    statement=excluded.statement,
                    spoiler_tier=excluded.spoiler_tier,
                    canon_src=excluded.canon_src
                """,
                (row["prop_id"], row["statement"], row["source"]),
            )
            conn.execute(
                """
                INSERT INTO knowledge_schedule (cons_id, prop_id, learn_ch, source_desc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cons_id, prop_id) DO UPDATE SET
                    learn_ch=excluded.learn_ch,
                    source_desc=excluded.source_desc
                """,
                (row["cons_id"], row["prop_id"], row["learn_ch"], row["source"]),
            )

        # Clean pendant note: match current note loosely
        cur = conn.execute(
            "SELECT item_id, note FROM items WHERE item_id='I.PENDANT_ANCHOR'"
        ).fetchone()
        if cur:
            old_note = cur[1] or ""
            new_note = ITEM_NOTE_UPDATES["I.PENDANT_ANCHOR"][1]
            if old_note != new_note:
                diff.append(f"~ITEM I.PENDANT_ANCHOR note:\n  BEFORE: {old_note}\n  AFTER:  {new_note}")
                if not dry_run:
                    conn.execute(
                        "UPDATE items SET note=? WHERE item_id=?",
                        (new_note, "I.PENDANT_ANCHOR"),
                    )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return diff


def rewrite_cards(dry_run: bool = False) -> list[str]:
    """Remove duplicated authored facts from cards; DB projection becomes sole source.

    identity_relations → empty list (runtime fetch_identity_relations fills from Seed).
    body_props → keep display string pointing at Seed item id (runtime expects strings).
    """
    changes: list[str] = []
    path = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
    card = json.loads(path.read_text(encoding="utf-8"))
    pc = card["persona_cards"]["C.ryuya.W1"]
    n_ir = len(pc.get("identity_relations") or [])
    pc["identity_relations"] = []
    pc["identity_seed_prop_ids"] = CARD_SEED_REFS["runtime/free_stage_card_ryuya_prologue.json"][
        "identity_seed_ids"
    ]
    pc["body_props"] = [
        "古铜色金属挂坠（Seed item: I.PENDANT_ANCHOR；持有关系在 Run/item_custody）"
    ]
    changes.append(f"rewrite {path.name} C.ryuya.W1 identity_relations {n_ir}→0 (+identity_seed_prop_ids)")
    changes.append(f"rewrite {path.name} C.ryuya.W1 body_props → seed-pointing display string")
    if not dry_run:
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    path = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
    card = json.loads(path.read_text(encoding="utf-8"))
    mapping = CARD_SEED_REFS["runtime/free_stage_card_tiananmen_v2.json"]
    for cons, ids in mapping.items():
        pc = card["persona_cards"][cons]
        n = len(pc.get("identity_relations") or [])
        pc["identity_relations"] = []
        pc["identity_seed_prop_ids"] = ids
        changes.append(f"rewrite {path.name} {cons} identity_relations {n}→0 (+identity_seed_prop_ids)")
    if not dry_run:
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db-only", action="store_true")
    ap.add_argument("--cards-only", action="store_true")
    args = ap.parse_args()
    if not args.cards_only:
        for line in apply_db(Path(args.db), dry_run=args.dry_run):
            print(line)
    if not args.db_only:
        for line in rewrite_cards(dry_run=args.dry_run):
            print(line)
    print("DRY_RUN" if args.dry_run else "APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
