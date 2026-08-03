# -*- coding: utf-8 -*-
"""Fix ryuya Seed rows in NEW repo world_truth.db per 2026-08-03 human cuts.

- Delete wrong/poetic slow_memory anchors (incl. cabin heat-glass on W1)
- Rewrite pendant memory as authored foundational (no quantum lore)
- Drop W1 schedule for K.C.ryuya.W1.Ch.112 (other-line cabin send)
- Upsert: Dust挚友+跳转动机, 接受摧毁 already exists, dual patricide guilt,
  player-as-variable, hold edges
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

DELETE_MEM_IDS = (8, 9, 10, 11)  # poetic / wrong-cabin
KEEP_REWRITE_MEM = 12

NEW_PROPS = [
    {
        "prop_id": "K.C.ryuya.W1.DUST_FRIEND_JUMP",
        "statement": "张尘（尘叔）是我在第一世界的挚友。我跨越无数世界线跳转，是为了找到他、带他回家。",
        "canon_src": "source/novel_108-end.md ~L5656-5677; 细剖 E121-01/E122-02（跳转寻尘）",
        "spoiler_tier": 1,
    },
    {
        "prop_id": "K.C.ryuya.W1.FATE_DESTROY",
        "statement": "我与挚友之间的核心信念：如果这是命运，接受它，然后摧毁它。",
        "canon_src": "source/novel_chapters_70_87.md Ch.84 ~L4232-4249; 人裁：本意识信念",
        "spoiler_tier": 1,
    },
    {
        "prop_id": "K.C.ryuya.W1.PLAYER_VARIABLE",
        "statement": "只有我清楚：眼前这个朋友可能是改变一切的变数。我设计了相遇与相识，成为朋友，把挂坠交给对方，盼这变数去关爱折原修哉与张尘。",
        "canon_src": "authored_opening+human_cut 2026-08-03（私设基础；挂坠原著无）",
        "spoiler_tier": 0,
    },
    {
        "prop_id": "K.C.ryuya.W1.PATRICIDE_GUILT",
        "statement": "这具身体亲手安排杀了父亲折原正义；我对这弑父负有罪感。",
        "canon_src": "Ch.60 弑父坦白；人裁：两意识皆有负罪感",
        "spoiler_tier": 1,
    },
    {
        "prop_id": "K.C.ryuya.WMAIN.PATRICIDE_GUILT",
        "statement": "我亲手安排杀了父亲折原正义；我对这弑父负有罪感。",
        "canon_src": "Ch.60；人裁：两意识皆有负罪感",
        "spoiler_tier": 1,
    },
    {
        "prop_id": "REL.HOLD.ryuya.W1.to_dust",
        "statement": "尘叔是第一世界挚友；我跳转寻他。赴死之夜他到场与我告别。",
        "canon_src": "novel_108-end L5656-5677; B5 赴死夜告别",
        "spoiler_tier": 1,
    },
    {
        "prop_id": "REL.HOLD.ryuya.W1.to_player",
        "statement": "对方是我设计相遇并结为朋友的人；可能是一切的变数。我把挂坠交给对方，盼对方关爱修哉与张尘。",
        "canon_src": "authored+human_cut 2026-08-03",
        "spoiler_tier": 0,
    },
    {
        "prop_id": "I.PENDANT_ANCHOR.SEED_NOTE",
        "statement": "古铜色金属挂坠：开场私设基础物件（原著无此物）。由第一世界修哉交予龙也，龙也临别交予玩家线友人。物定义在 Seed；持有在 Run。",
        "canon_src": "human_cut 私设可入库 2026-08-03",
        "spoiler_tier": 0,
    },
]

SCHEDULES = [
    ("C.ryuya.W1", "K.C.ryuya.W1.DUST_FRIEND_JUMP", 1),
    ("C.ryuya.W1", "K.C.ryuya.W1.FATE_DESTROY", 1),
    ("C.ryuya.W1", "K.C.ryuya.W1.PLAYER_VARIABLE", 0),
    ("C.ryuya.W1", "K.C.ryuya.W1.PATRICIDE_GUILT", 1),
    ("C.ryuya.WMAIN", "K.C.ryuya.WMAIN.PATRICIDE_GUILT", 1),
    ("C.ryuya.W1", "REL.HOLD.ryuya.W1.to_dust", 1),
    ("C.ryuya.W1", "REL.HOLD.ryuya.W1.to_player", 0),
    # alias: keep R-W1-02 in sync conceptually; FATE_DESTROY is cleaner statement
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    log: list[str] = []

    # delete bad memories
    for mid in DELETE_MEM_IDS:
        row = cur.execute("SELECT anchor FROM slow_memory WHERE mem_id=?", (mid,)).fetchone()
        if row:
            log.append(f"DEL slow_memory#{mid} ({row[0]})")
            if args.apply:
                cur.execute("DELETE FROM slow_memory WHERE mem_id=?", (mid,))

    # rewrite pendant memory
    new_text = (
        "临别把古铜色金属挂坠交到朋友手上时，指尖触到金属的凉。"
        "（开场私设：挂坠；原著无此物。）"
    )
    log.append(f"REWRITE slow_memory#{KEEP_REWRITE_MEM} pendant")
    if args.apply:
        cur.execute(
            """
            UPDATE slow_memory
            SET text=?, anchor=?, emo_tag=?, salience=?, available_ch=0,
                projection_text=NULL, src_event=NULL
            WHERE mem_id=?
            """,
            (new_text, "临别交坠/金属凉", "hope_relief", 0.9, KEEP_REWRITE_MEM),
        )

    # drop wrong Ch.112 schedule on W1
    log.append("UNSCHED C.ryuya.W1 <- K.C.ryuya.W1.Ch.112")
    if args.apply:
        cur.execute(
            "DELETE FROM knowledge_schedule WHERE cons_id=? AND prop_id=?",
            ("C.ryuya.W1", "K.C.ryuya.W1.Ch.112"),
        )

    for p in NEW_PROPS:
        log.append(f"UPSERT prop {p['prop_id']}")
        if args.apply:
            cur.execute(
                """
                INSERT INTO propositions(prop_id, statement, spoiler_tier, canon_src)
                VALUES (?,?,?,?)
                ON CONFLICT(prop_id) DO UPDATE SET
                  statement=excluded.statement,
                  spoiler_tier=excluded.spoiler_tier,
                  canon_src=excluded.canon_src
                """,
                (p["prop_id"], p["statement"], p["spoiler_tier"], p["canon_src"]),
            )

    for cons, pid, ch in SCHEDULES:
        log.append(f"SCHED {cons} <- {pid} @{ch}")
        if args.apply:
            cur.execute(
                """
                INSERT INTO knowledge_schedule(cons_id, prop_id, learn_ch, source_desc)
                VALUES (?,?,?,?)
                ON CONFLICT(cons_id, prop_id) DO UPDATE SET
                  learn_ch=excluded.learn_ch,
                  source_desc=excluded.source_desc
                """,
                (cons, pid, ch, "migrate_ryuya_seed_fix_2026-08-03"),
            )

    # align existing R-W1-02 statement to fate belief (keep id)
    log.append("UPDATE K.C.ryuya.W1.R-W1-02 statement")
    if args.apply:
        cur.execute(
            """
            UPDATE propositions SET statement=?, canon_src=?
            WHERE prop_id=?
            """,
            (
                "我与挚友张尘/尘之间有核心信念：如果这是命运，接受它，然后摧毁它。",
                "Ch.84; 人裁：本意识信念 2026-08-03",
                "K.C.ryuya.W1.R-W1-02",
            ),
        )

    # update pendant identity statement lightly
    log.append("UPDATE REL.IDENTITY.ryuya.pendant_from_xiuzai")
    if args.apply:
        cur.execute(
            """
            UPDATE propositions SET statement=?, canon_src=?
            WHERE prop_id=?
            """,
            (
                "这枚古铜色挂坠是第一世界的修哉交给我的；临别要当面交给眼前这个朋友。（开场私设物件，原著无。）",
                "authored_opening+human_cut 私设可入库 2026-08-03",
                "REL.IDENTITY.ryuya.pendant_from_xiuzai",
            ),
        )

    if args.apply:
        con.commit()
        log.append("COMMIT")
    else:
        log.append("DRY-RUN only")
    con.close()
    for line in log:
        print(line)


if __name__ == "__main__":
    main()
