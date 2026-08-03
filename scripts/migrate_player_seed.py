#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 batch E: register B.player / C.player + baseline P.PLAYER.* props.

Opening name/age/job stay in run-domain player_profile (not Seed).
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "world_truth.db"

PLAYER_ARCH = ("player", "玩家（可扮演壳）")
PLAYER_BODY = (
    "B.player",
    "W-MAIN",
    "player",
    "human",
    None,
    "玩家可扮演身体壳（Seed 基线；姓名等开档设定在 run.player_profile）",
)
PLAYER_CONS = (
    "C.player",
    "W-MAIN",
    "player",
    0,
    "玩家意识（jump_capable=0；非正典跳线者）",
)
PLAYER_PROPS = (
    {
        "prop_id": "P.PLAYER.ORDINARY_SHELL",
        "statement": "玩家以普通人壳进入世界：无跳线能力，不是正典跳线者。",
        "source": "docs/plans/初始库重建×全投影_详细计划_2026-08-01.md 批E；周目世界实例§6",
    },
    {
        "prop_id": "P.PLAYER.RUN_PROFILE_NOT_SEED",
        "statement": "开档姓名/称呼/年龄/身份/软特长只存在于本周目 player_profile（run 域），不写入 Seed 命题。",
        "source": "2026-08-02 Q3 人裁；周目世界实例§6 开档设定",
    },
    {
        "prop_id": "P.PLAYER.BODY_CONS_PAIR",
        "statement": "Seed 注册对：body_id=B.player 与 cons_id=C.player；持有与身体帧在 run 账本演化。",
        "source": "docs/plans/初始库重建×全投影_详细计划_2026-08-01.md G3/批E",
    },
)


def apply(db_path: Path, dry_run: bool = False) -> list[str]:
    diff: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        arch = conn.execute("SELECT arch_id FROM archetypes WHERE arch_id=?", ("player",)).fetchone()
        if not arch:
            diff.append("+ARCH player")
            if not dry_run:
                conn.execute(
                    "INSERT INTO archetypes(arch_id, display_name) VALUES (?,?)",
                    PLAYER_ARCH,
                )
        body = conn.execute("SELECT body_id FROM bodies WHERE body_id=?", ("B.player",)).fetchone()
        if not body:
            diff.append("+BODY B.player")
            if not dry_run:
                conn.execute(
                    "INSERT INTO bodies(body_id, origin_wl, arch_id, body_type, rtw_code, note) VALUES (?,?,?,?,?,?)",
                    PLAYER_BODY,
                )
        cons = conn.execute(
            "SELECT cons_id, jump_capable FROM consciousnesses WHERE cons_id=?",
            ("C.player",),
        ).fetchone()
        if not cons:
            diff.append("+CONS C.player jump_capable=0")
            if not dry_run:
                conn.execute(
                    "INSERT INTO consciousnesses(cons_id, native_wl, arch_id, jump_capable, note) VALUES (?,?,?,?,?)",
                    PLAYER_CONS,
                )
        elif int(cons[1] or 0) != 0:
            diff.append("~CONS C.player jump_capable → 0")
            if not dry_run:
                conn.execute(
                    "UPDATE consciousnesses SET jump_capable=0 WHERE cons_id='C.player'"
                )

        occ = conn.execute(
            "SELECT 1 FROM occupancy WHERE body_id='B.player' AND cons_id='C.player' AND occ_mode='native'"
        ).fetchone()
        if not occ:
            diff.append("+OCC B.player×C.player native")
            if not dry_run:
                conn.execute(
                    """
                    INSERT INTO occupancy(body_id, cons_id, from_event, to_event, occ_mode, canon_src)
                    VALUES ('B.player','C.player',NULL,NULL,'native','S2 batch E player shell registration 2026-08-03')
                    """
                )

        for row in PLAYER_PROPS:
            diff.append(f"+PROP {row['prop_id']}: {row['statement']}")
            if dry_run:
                continue
            conn.execute(
                """
                INSERT INTO propositions(prop_id, statement, spoiler_tier, canon_src)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(prop_id) DO UPDATE SET
                    statement=excluded.statement,
                    canon_src=excluded.canon_src
                """,
                (row["prop_id"], row["statement"], row["source"]),
            )
            conn.execute(
                """
                INSERT INTO knowledge_schedule(cons_id, prop_id, learn_ch, source_desc)
                VALUES ('C.player', ?, 0, ?)
                ON CONFLICT(cons_id, prop_id) DO UPDATE SET
                    learn_ch=excluded.learn_ch,
                    source_desc=excluded.source_desc
                """,
                (row["prop_id"], row["source"]),
            )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return diff


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for line in apply(Path(args.db), dry_run=args.dry_run):
        print(line)
    print("DRY_RUN" if args.dry_run else "APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
