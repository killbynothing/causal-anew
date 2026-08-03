#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the human-approved B2 identity-relation facts to world truth.

Identity facts remain ordinary, source-bound propositions plus scheduled
knowledge.  The runtime projects the ``REL.IDENTITY.*`` namespace separately;
this migration therefore creates no new table and grants no disclosure right.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "world_truth.db"


RELATIONS = (
    {
        "cons_id": "C.weichu.WMAIN",
        "prop_id": "REL.IDENTITY.weichu.xiuzai",
        "statement": "修哉是我亡夫龙也的弟弟。",
        "learn_ch": 1,
        "source": "source/novel_1-69.md:L8095-L8099；魏初自述“我是修哉的嫂子……这是他的哥哥……他是龙也，折原龙也”。",
    },
    {
        "cons_id": "C.maki.WMAIN",
        "prop_id": "REL.IDENTITY.maki.ryuya_xiuzai",
        "statement": "龙也是我的表弟，修哉是龙也的亲弟弟；我把修哉当作弟弟。",
        "learn_ch": 1,
        "source": "source/novel_1-69.md:L6035-L6037,L6464-L6469；真纪自述“龙也是我的表弟，修哉的亲哥哥”，并称修哉为“如今唯一的弟弟”。",
    },
)


def apply(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for row in RELATIONS:
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

        for row in RELATIONS:
            fact = conn.execute(
                "SELECT statement FROM propositions WHERE prop_id=?", (row["prop_id"],)
            ).fetchone()
            schedule = conn.execute(
                """SELECT learn_ch, source_desc FROM knowledge_schedule
                   WHERE cons_id=? AND prop_id=?""",
                (row["cons_id"], row["prop_id"]),
            ).fetchone()
            if not fact or fact[0] != row["statement"]:
                raise RuntimeError(f"identity proposition mismatch: {row['prop_id']}")
            if not schedule or schedule[0] != row["learn_ch"] or schedule[1] != row["source"]:
                raise RuntimeError(f"identity schedule mismatch: {row['cons_id']} / {row['prop_id']}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"[FAIL] database does not exist: {db_path}")
    apply(db_path)
    print(f"[OK] applied {len(RELATIONS)} approved identity relations to {db_path}")


if __name__ == "__main__":
    main()
