# -*- coding: utf-8 -*-
"""Supplement Ryuya W1 cafe-register voice + soft married disclosure.

Human OK 2026-08-08 (session): 补声纹从原著；可提结婚了不提妻名；不扩共史硬闸。
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
SRC = "migrate_ryuya_voice_cafe_2026-08-08"

UPSERTS: list[dict] = [
    {
        "prop_id": "P.VOICE.ryuya.W1.cadence",
        "statement": (
            "咖啡馆/熟人闲聊优先：口语短接、可抬杠、可留白；认真托付时仍像对人说话，"
            "不换系统任务腔、不念清单。朋友沉默或一次拒绝后换玩笑/换话题，不纠缠。"
            "共史只谈已有锚点（雨、旧桌、泼袖赔咖啡、两年偶遇），不补宿舍楼等没写过的细节。"
        ),
        "spoiler_tier": 0,
        "canon_src": "P.MANNER.ryuya.W1.voice_rule；序幕卡；人裁2026-08-08",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.ex_casual",
        "statement": (
            "金标（平常接话）：「不知道呢。」／"
            "「不无道理来着……照你的意思就是说……」／"
            "「是啊，同样身为不知道内情的我们，也就只能静待事变了。」"
            "——语气平常，轻描淡写挡开，不审讯腔。"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69.md:L14633；L14639；L14650",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.ex_married_soft",
        "statement": (
            "金标（已婚触碰·不点名）：「是个好女孩儿，没有遇到我也会遇到更好的人吧，不巧就被我遇到了。」"
            "对玩家可淡提「我结婚了」，不说妻名；被调侃定情/信物时可心下一顿再玩笑拨开，不卖惨。"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_chapters_70_87.md:L1728；筛查白名单·已婚不露是谁；人裁2026-08-08",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "REL.HOLD.ryuya.to_weichu",
        "statement": (
            "魏初是妻子：婚姻锚。对玩家可淡提「我结婚了/已婚」，不提妻名、不展开婚姻史、不卖惨；"
            "被调侃定情/信物时可轻挡。日常对亲人的温柔声口多由 W1 前台；"
            "本体脏手与组织面不对妻表演。"
        ),
        "spoiler_tier": 0,
        "canon_src": "圣经；fc1；人裁2026-08-08放宽淡提已婚",
        "schedules": [(CONS_W1, 0), ("C.ryuya.WMAIN", 0)],
    },
]

VOICE_SEED_IDS_EXTRA = [
    "P.VOICE.ryuya.W1.ex_casual",
    "P.VOICE.ryuya.W1.ex_married_soft",
]


def upsert_prop(cur: sqlite3.Cursor, row: dict, apply: bool, log: list[str]) -> None:
    log.append(f"UPSERT {row['prop_id']}")
    if not apply:
        return
    cur.execute(
        """
        INSERT INTO propositions(prop_id, statement, spoiler_tier, canon_src)
        VALUES(?,?,?,?)
        ON CONFLICT(prop_id) DO UPDATE SET
          statement=excluded.statement,
          spoiler_tier=excluded.spoiler_tier,
          canon_src=excluded.canon_src
        """,
        (row["prop_id"], row["statement"], row["spoiler_tier"], row["canon_src"]),
    )
    for cons, ch in row.get("schedules") or []:
        cur.execute(
            """
            INSERT INTO knowledge_schedule(cons_id, prop_id, learn_ch, source_desc)
            VALUES(?,?,?,?)
            ON CONFLICT(cons_id, prop_id) DO UPDATE SET
              learn_ch=excluded.learn_ch,
              source_desc=excluded.source_desc
            """,
            (cons, row["prop_id"], ch, SRC),
        )


def patch_card(apply: bool, log: list[str]) -> None:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    personas = card.get("persona_cards") or {}
    w1 = personas.get("C.ryuya.W1") or {}
    ids = list(w1.get("voice_seed_prop_ids") or [])
    for pid in VOICE_SEED_IDS_EXTRA:
        if pid not in ids:
            ids.append(pid)
            log.append(f"CARD+ {pid}")
    w1["voice_seed_prop_ids"] = ids
    # keep empty inline samples; projection from DB
    w1["voice_samples"] = []
    personas["C.ryuya.W1"] = w1
    card["persona_cards"] = personas
    if apply:
        CARD.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    log: list[str] = []
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    for row in UPSERTS:
        upsert_prop(cur, row, args.apply, log)
    patch_card(args.apply, log)
    if args.apply:
        con.commit()
        # dump sql
        with SQL_DUMP.open("w", encoding="utf-8") as f:
            for line in con.iterdump():
                f.write(f"{line}\n")
        log.append(f"DUMP {SQL_DUMP.name}")
    con.close()
    print("\n".join(log))
    print("OK apply" if args.apply else "OK dry-run")


if __name__ == "__main__":
    main()
