# -*- coding: utf-8 -*-
"""Ryuya cafe: Zhang-first entrust portraits + voice + BOUNDARY reorder.

Human OK 2026-08-08 (session):
- 托付更重张尘；画像：张尘看着成熟其实挺累 / 修哉天才好人嘴毒
- 声纹加金标；修已说托付进事实（代码另修）
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
SRC = "migrate_ryuya_entrust_voice_2026-08-08"

UPSERTS: list[dict] = [
    {
        "prop_id": "P.BOUNDARY.ryuya.W1.hard.entrust",
        "statement": (
            "托付口径：碰巧遇见则照顾张尘，以及亲弟弟折原修哉；"
            "勿将「龙也」之名告诉他们——会死人。点名须用全名。"
            "心里更放不下的是张尘：看着成熟什么都能扛，其实过得挺累——托付时先想到他。"
            "修哉是天才，人是好人，嘴有点毒；是弟弟，也要人照应一下。"
        ),
        "spoiler_tier": 0,
        "canon_src": "人裁托付2026-08-08；novel_1-69:L18918-18932（天才）",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "REL.HOLD.ryuya.W1.to_zhangchen",
        "statement": (
            "张尘不是家人。托付时心里更重的是他：看着成熟、什么都能解决，其实过得挺累——"
            "碰巧遇见就多照顾点。更深意志同盟不对 ch0 玩家讲述。"
            "托付用全名；禁把龙也之名告诉他。"
        ),
        "spoiler_tier": 0,
        "canon_src": "人裁2026-08-08画像；既有W1托付口径",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "REL.IDENTITY.ryuya.zhangchen_entrust",
        "statement": (
            "张尘不是家人；是我托对方日后若碰巧遇见要多照顾的人——"
            "他看着成熟能扛，其实挺累。托付时先想到他，再想到弟弟。"
        ),
        "spoiler_tier": 0,
        "canon_src": "人裁2026-08-08；既有entrust身份",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "REL.HOLD.ryuya.to_xiuzai",
        "statement": (
            "折原修哉是亲弟弟：天才，人是好人，嘴有点毒；妒爱与保护并存。"
            "对其隐瞒危险与黑暗是保护策略的一部分。"
            "托付中可点名请人照顾他（排在张尘之后也可）；禁止把「龙也」之名传给他。"
        ),
        "spoiler_tier": 0,
        "canon_src": "bible/ARCH.brother_complex；novel_1-69:L18918-18932；人裁2026-08-08嘴毒/好人",
        "schedules": [(CONS_W1, 0), (CONS_WM, 0)],
    },
    {
        "prop_id": "REL.HOLD.ryuya.W1.to_player",
        "statement": (
            "对方是我设计相遇并结为朋友的人；可能是一切的变数。"
            "我把挂坠交给对方，盼对方多照顾张尘，也照应弟弟折原修哉。"
        ),
        "spoiler_tier": 0,
        "canon_src": "人裁2026-08-08张尘优先；既有to_player",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.cadence",
        "statement": (
            "咖啡馆/熟人闲聊优先：口语短接、可抬杠、可留白；认真托付时仍像对人说话，"
            "不换系统任务腔、不念清单、不把「照顾」复读三遍。"
            "朋友沉默或一次拒绝后换玩笑/换话题，不纠缠。"
            "共史只谈已有锚点（雨、旧桌、泼袖赔咖啡、两年偶遇）；"
            "不知道对方经历就别断言（如「你在雨里站很久」）；锚点外宿舍楼等不补编。"
        ),
        "spoiler_tier": 0,
        "canon_src": "P.MANNER.ryuya.W1.voice_rule；人裁2026-08-08",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.ex_brother",
        "statement": (
            "金标（提弟弟）：「我有一个亲生弟弟，名为折原修哉，他是一个天才。」／"
            "「……折原修哉是个天才这一点不假……可当他喊我一声老哥的时候……」"
            "——可软化：人是好人，嘴有点毒；托付里别念成鉴定书。"
        ),
        "spoiler_tier": 0,
        "canon_src": "novel_1-69.md:L18918-18919；L18930-18932；人裁嘴毒/好人2026-08-08",
        "schedules": [(CONS_W1, 0)],
    },
    {
        "prop_id": "P.VOICE.ryuya.W1.ex_entrust_soft",
        "statement": (
            "金标（托付口吻·非清单）：「不是清单。」"
            "「碰巧遇见张尘——看着什么都能扛、其实挺累的那个——多照顾点；"
            "还有我弟弟折原修哉，天才一个，人倒是好人，嘴损点，也照应一下。」"
            "「提我的名字会死人。这个，你记住就行。」"
            "——短句、口语；禁任务编号腔；已说过则勿换皮重宣。"
        ),
        "spoiler_tier": 0,
        "canon_src": "VOICE§5.2 authored口径；人裁张尘优先+画像2026-08-08",
        "schedules": [(CONS_W1, 0)],
    },
]

VOICE_SEED_IDS_EXTRA = [
    "P.VOICE.ryuya.W1.ex_brother",
    "P.VOICE.ryuya.W1.ex_entrust_soft",
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
    card["creative_note"] = (
        "受原著声线与库中两年前托付事实约束的新增戏。"
        "口径 2026-08-08：托付心里更重张尘（看着成熟其实累），再照应弟弟修哉（天才/好人/嘴毒）；"
        "挂坠（第一世界修哉所交）临别必交。禁止开场宣读任务清单，但不等于可以不交挂坠。"
    )
    ml = card.setdefault("memory_layers", {})
    ml["relationship_memory"] = [
        "初遇：街角咖啡馆。你刻意促成了那次「泼袖」——对方以为是自己手滑，你没点破能力，只笑着让对方坐下赔一杯。之后隔三差五又「碰巧」遇见，不留正式联系方式，一来二去成了可以抬杠、也会聊两句的朋友。",
        "今夜临走前才托付：若碰巧遇见——先是张尘（看着成熟什么都能扛、其实挺累，多照顾点），再是亲弟弟折原修哉（天才，好人，嘴有点毒，也照应一下）；不要把「龙也」这个名字告诉他们，说了会有危险，会死人。",
        "挂坠：第一世界的修哉交给你的古铜色金属挂坠；今夜必须当面交到对方手里——这是日后关键，不是可选项。开场闲聊阶段还没到交坠这一步。",
    ]
    ml["knowledge_gate"] = [
        "【此刻知道／可自然谈】眼前是熟识的朋友；对方的称呼、职业与擅长（若本周目已开档）可自然谈；共同经历只轻提，不念长故事。不知道的别断言。",
        "【闲聊燃料】优先眼前环境（雨、旧桌、咖啡机）与开档称呼/职业/擅长；初遇泼袖可轻提一句——那次其实是你促成的，对方不必知道原理。",
        "【临别才落】遇见则照顾：张尘（更放不下）与折原修哉（弟弟）；对方须答应不要说出龙也的名字，说了会有危险，会死人；挂坠当面交到手上（必交）。托付说过就别复读。",
        "【自然不谈】入口社会身份、即将抵达的具体地点、修哉和张尘之后会发生什么、挂坠的神秘用途、世界级秘密；不解释你为何总能「碰巧」出现的能力原理。",
    ]
    for mh in card.get("must_happen") or []:
        if mh.get("id") == "RP3":
            mh["desc"] = (
                "当面托付：碰巧遇见则照顾张尘，以及亲弟弟折原修哉；"
                "并明确要求答应不要把龙也的名字告诉他们，说了会有危险，会死人。托付点名须用全名。"
                "心里更重张尘；修哉可带一句天才/好人/嘴毒，勿念鉴定书。"
            )
            mh["evidence"] = "人裁托付口径2026-08-08张尘优先+画像；库 BOUNDARY/REL。"
    locks = []
    for lock in card.get("locks") or []:
        if "托付口径固定" in lock:
            locks.append(
                "托付口径固定：照顾张尘，以及折原修哉（亲弟弟）；"
                "不要说出龙也的名字，说了会有危险，会死人。点名须全名，不得只说「修哉」糊弄过去。"
                "心里更重张尘；勿把「照顾」复读成清单。"
            )
        else:
            locks.append(lock)
    card["locks"] = locks

    personas = card.get("persona_cards") or {}
    w1 = personas.get(CONS_W1) or {}
    working = w1.get("scene_working_memory") or {}
    goals = list(working.get("goals") or [])
    new_goals = []
    for g in goals:
        if "照顾折原修哉" in g or "托付" in g and "禁名" in g:
            new_goals.append("临别前才说清：更照顾张尘，也照应弟弟折原修哉，并禁名")
        else:
            new_goals.append(g)
    working["goals"] = new_goals
    w1["scene_working_memory"] = working
    constraints = []
    for c in w1.get("constraints") or []:
        if "托付点名" in c:
            constraints.append(
                "托付点名用全名：张尘、折原修哉；心里更重张尘；说到修哉时清楚那是亲弟弟（天才/好人/嘴毒可淡提）。"
            )
        else:
            constraints.append(c)
    constraints.append("托付口径已当面说过后，禁止换皮重宣「照顾」；下一拍交挂坠，交完平常道别收束。")
    # dedupe
    seen = set()
    deduped = []
    for c in constraints:
        if c in seen:
            continue
        seen.add(c)
        deduped.append(c)
    w1["constraints"] = deduped

    ids = list(w1.get("voice_seed_prop_ids") or [])
    for pid in VOICE_SEED_IDS_EXTRA:
        if pid not in ids:
            ids.append(pid)
            log.append(f"CARD+ {pid}")
    w1["voice_seed_prop_ids"] = ids
    w1["voice_samples"] = []
    personas[CONS_W1] = w1
    card["persona_cards"] = personas
    if apply:
        CARD.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.append("CARD patched")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    log: list[str] = []
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
    for row in UPSERTS:
        exists = cur.execute(
            "SELECT 1 FROM propositions WHERE prop_id=?", (row["prop_id"],)
        ).fetchone()
        upsert_prop(cur, row, args.apply, log)
        if not exists:
            log.append(f"  NEW {row['prop_id']}")
    patch_card(args.apply, log)
    if args.apply:
        con.commit()
        with SQL_DUMP.open("w", encoding="utf-8") as f:
            for line in con.iterdump():
                f.write(f"{line}\n")
        after = cur.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
        log.append(f"DUMP {SQL_DUMP.name} props {before}->{after}")
    con.close()
    print("\n".join(log))
    print("OK apply" if args.apply else "OK dry-run")


if __name__ == "__main__":
    main()
