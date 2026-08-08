# -*- coding: utf-8 -*-
"""Migrate Ryuya P.VOICE (W1+WMAIN) — human OK 2026-08-08.

Source: docs/plans/★★★可审_龙也声纹VOICE_原著细抽_2026-08-08.md §4
Does NOT migrate §5.1 authored_style chat (not approved as canon lines).
Keeps P.MANNER.*.voice_rule unchanged.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"
CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"
SQL_DUMP = ROOT / "data" / "world_truth.sql"
CONS_W1 = "C.ryuya.W1"
CONS_WM = "C.ryuya.WMAIN"
SRC = "migrate_ryuya_voice_2026-08-08"

VOICE_SEED_IDS = [
    "P.VOICE.ryuya.W1.cadence",
    "P.VOICE.ryuya.W1.address",
    "P.VOICE.ryuya.W1.ex_belief",
    "P.VOICE.ryuya.W1.ex_farewell",
]

UPSERTS: list[dict] = [
    {
        "prop_id": "P.VOICE.ryuya.W1.cadence",
        "statement": (
            "口语自然、熟络可抬杠；短接话常见。认真托付时仍像对人说话，"
            "不换系统任务腔、不念清单。朋友沉默或一次拒绝后可换玩笑/换话题，不纠缠。"
        ),
        "spoiler_tier": 0,
        "canon_src": "P.MANNER.ryuya.W1.voice_rule；序幕卡",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.address",
        "statement": (
            "亲昵称呼：阿修、阿秋、初初、阿尘；决别可直呼张尘。"
            "不用公文「先生」腔对朋友。"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69:L9547；novel_108-end:L1662；L1868",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.ex_belief",
        "statement": (
            "金标（信念落地）：「如果这是命运的话，接受就好了。」／「接受它，然后摧毁它。」"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_chapters_70_87:L4232-4236",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.ex_farewell",
        "statement": (
            "金标（决别）：「我大概只能送你到这里了……」"
            "「张尘，请你务必记住，无论如何一定要阻止。」"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_108-end:L1857-1869",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.WMAIN.cadence",
        "statement": (
            "组织面：礼貌、平淡、解释干瘪；可重复「自愿」「明事理」施压。"
            "坦白面：可极平静陈述极狠事实；少表演性崩溃；致歉不等于求原谅。"
            "禁止咖啡馆玩笑腔。"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69:L18529-18608；L18854-18934",
        "schedules": [(CONS_WM, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.WMAIN.address",
        "statement": (
            "公事：「张尘先生」「山本先生」+ 自报全名职务。对弟：「阿修」。家中可「初初」。"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69:L18541；novel_chapters_70_87:L3402；novel_1-69:L6344；novel_108-end:L5555",
        "schedules": [(CONS_WM, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.WMAIN.ex_org",
        "statement": (
            "金标（招募）：「街上不方便，我们不如车上谈。」"
            "「这次好好介绍一下，我是折原龙也……请多指教，张尘先生。」"
            "「希望你可以自愿加入世界政府……」"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69:L18529-18548",
        "schedules": [(CONS_WM, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.WMAIN.ex_confess",
        "statement": (
            "金标（坦白）：「对于你的恋人，我很抱歉。」"
            "「我亲自安排一出戏，杀了我的父亲。」"
            "「折原修哉是个天才这一点不假……可当他喊我一声老哥的时候……」"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69:L18855；L18892；L18930-18932",
        "schedules": [(CONS_WM, 0)],
    },
]


def upsert_prop(cur: sqlite3.Cursor, row: dict, apply: bool, log: list[str]) -> None:
    log.append(f"UPSERT {row['prop_id']}")
    if not apply:
        return
    cur.execute(
        """
        INSERT INTO propositions(prop_id, statement, spoiler_tier, canon_src)
        VALUES (?,?,?,?)
        ON CONFLICT(prop_id) DO UPDATE SET
          statement=excluded.statement,
          spoiler_tier=excluded.spoiler_tier,
          canon_src=excluded.canon_src
        """,
        (row["prop_id"], row["statement"], row["spoiler_tier"], row["canon_src"]),
    )
    for cons, ch in row["schedules"]:
        cur.execute(
            """
            INSERT INTO knowledge_schedule(cons_id, prop_id, learn_ch, source_desc)
            VALUES (?,?,?,?)
            ON CONFLICT(cons_id, prop_id) DO UPDATE SET
              learn_ch=excluded.learn_ch,
              source_desc=excluded.source_desc
            """,
            (cons, row["prop_id"], ch, SRC),
        )
        log.append(f"  SCHED {cons} <- {row['prop_id']} @{ch}")


def rewrite_card(apply: bool, log: list[str]) -> None:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pc = card["persona_cards"][CONS_W1]
    pc["voice_samples"] = []
    pc["voice_seed_prop_ids"] = list(VOICE_SEED_IDS)
    log.append(f"CARD voice_seed_prop_ids={VOICE_SEED_IDS}")
    if apply:
        CARD.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_sql(apply: bool, log: list[str]) -> None:
    if not apply:
        return
    import subprocess

    subprocess.check_call(
        ["sqlite3", str(DB), f".output {SQL_DUMP}", ".dump"],
        cwd=str(ROOT),
    )
    log.append(f"DUMP {SQL_DUMP.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-dump", action="store_true")
    args = ap.parse_args()
    log: list[str] = []
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    for row in UPSERTS:
        upsert_prop(cur, row, args.apply, log)
    rewrite_card(args.apply, log)
    if args.apply:
        con.commit()
        if not args.no_dump:
            try:
                dump_sql(True, log)
            except Exception as e:
                # Windows may lack sqlite3 CLI; Python dump fallback
                log.append(f"DUMP_CLI_FAIL {e}; using python dump")
                with SQL_DUMP.open("w", encoding="utf-8") as f:
                    for line in con.iterdump():
                        f.write(line + "\n")
                log.append(f"DUMP {SQL_DUMP.name}")
    con.close()
    print("\n".join(log))
    print("OK", "APPLY" if args.apply else "DRY")


if __name__ == "__main__":
    main()
