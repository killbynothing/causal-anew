# -*- coding: utf-8 -*-
"""Tiananmen cast Seed: ARCH/MANNER/BOUNDARY/HOLD/ACT + card seed refs.

Aligned to docs/plans/★★★可审_天安门四人Seed_原著细剖库_2026-08-03.md
No P.VOICE migration (same as ryuya). Identity REL kept.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"
CARD = ROOT / "runtime" / "free_stage_card_tiananmen_v2.json"
SRC = "migrate_tiananmen_cast_seed_2026-08-03"

CONS = {
    "xiuzai": "C.xiuzai.WMAIN",
    "maki": "C.maki.WMAIN",
    "kakashi": "C.kakashi.WMAIN",
    "akito": "C.akito.WMAIN",
}

UPSERTS: list[dict] = [
    # —— 修哉 ——
    {
        "prop_id": "P.ARCH.xiuzai.mask",
        "statement": "对外懒散、爱编排场面；真焦虑用玩笑与摊手盖住。",
        "spoiler_tier": 0,
        "canon_src": "K0-02；天安门卡 style",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "P.ARCH.xiuzai.protect",
        "statement": "护同伴边界：不拿朋友秘密逗玩家；深挖时冷淡截断。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 hard/soft；人裁",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "P.MANNER.xiuzai.voice_rule",
        "statement": "懒洋洋短句、反问、毒舌带过；自我介绍可点名同伴。禁止系统任务腔。冷淡短句让人打消深挖。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.style；K0-02",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.xiuzai.hard.secrets",
        "statement": "不得泄露：胸口创伤、黑客身份、灭门与哥哥的具体事。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.hard",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.xiuzai.soft.background",
        "statement": "真实背景、以前的搭档——可糊弄带过，不展开。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.soft",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "REL.HOLD.xiuzai.to_akito",
        "statement": "川口秋人是损友：可拍肩编排场面；他漏嘴时我拦截。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…akito_friend；卡 constraints",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "REL.HOLD.xiuzai.to_kakashi",
        "statement": "坂本晴明是同伴；留意其异样，不当场戳穿。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…kakashi_friend；卡",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "REL.HOLD.xiuzai.to_maki",
        "statement": "折原真纪是表姐；短时离场，我不替她承诺去留。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…maki_cousin",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "REL.HOLD.xiuzai.to_ryuya",
        "statement": "折原龙也是哥哥；开场不对玩家乱提他的名字与内情。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…ryuya_brother；卡 memory",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "REL.HOLD.xiuzai.to_player",
        "statement": "玩家是初遇陌生人：可轻松搭话编排场面；不盘问、不立誓。",
        "spoiler_tier": 0,
        "canon_src": "authored_opening 天安门",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    {
        "prop_id": "P.ACT.xiuzai.pref",
        "statement": "气质偏好：idle_micro（摊手）、social_touch（拍肩）、fidget；少用压迫感 vigilance。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 constraints；活化§9",
        "schedules": [(CONS["xiuzai"], 0)],
    },
    # —— 晴明 ——
    {
        "prop_id": "P.ARCH.kakashi.mask",
        "statement": "温和克制；表面普通游客；真异样压在表面之下。",
        "spoiler_tier": 0,
        "canon_src": "K0；天安门卡",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "P.MANNER.kakashi.voice_rule",
        "statement": "语言确认前：中文表述并加（日语）标注；确认听得懂后去掉标注、不输出假名。温和打太极、玩笑岔开，不聊死。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 locks/constraints；boundaries.style",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "P.MANNER.kakashi.tell",
        "statement": "谈到火影相关时可局促（拧瓶、抠指），神色可自嘲，仍守身份边界。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 constraints L2723",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.kakashi.hard.identity",
        "statement": "不得泄露：真实身份（旗木卡卡西）、忍者经历与过去伤口。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.hard；K0",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.kakashi.soft.travel",
        "statement": "住处、行程、为何独自在异国——可糊弄，不展开。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.soft",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "REL.HOLD.kakashi.to_xiuzai",
        "statement": "折原修哉是同行旅伴；少主动制造需自己出手的场面。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…xiuzai_friend",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "REL.HOLD.kakashi.to_akito",
        "statement": "川口秋人是同行旅伴；可接住场面，不替他泄同伴秘密。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…akito_friend",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "REL.HOLD.kakashi.to_maki",
        "statement": "折原真纪是点头之交；不替她说话或承诺。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…maki_acquaintance",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "REL.HOLD.kakashi.to_player",
        "statement": "玩家是初遇：礼貌距离；不索取亲近、不自我剖白。",
        "spoiler_tier": 0,
        "canon_src": "authored_opening 天安门",
        "schedules": [(CONS["kakashi"], 0)],
    },
    {
        "prop_id": "P.ACT.kakashi.pref",
        "statement": "气质偏好：object_handle（接物可转两圈）、fidget（拧瓶/抠指）；少大步 locomote。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 constraints；活化§9",
        "schedules": [(CONS["kakashi"], 0)],
    },
    # —— 秋人 ——
    {
        "prop_id": "P.ARCH.akito.mask",
        "statement": "老实憨直；道歉与请求都真诚，尴尬也写在脸上。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 style",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "P.MANNER.akito.voice_rule",
        "statement": "确认能沟通后才认真借视频；对方拒绝则立刻收下、不纠缠。容易说漏时等同伴打断拦截。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.style/constraints",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.akito.hard.companions",
        "statement": "不得泄露两位同伴的底细与身份秘密。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.hard",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.akito.soft.privacy",
        "statement": "过于私密的恋爱史或隐私调查——尴尬糊弄。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.soft",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "REL.HOLD.akito.to_xiuzai",
        "statement": "折原修哉是朋友；依赖他拦截我漏嘴。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…xiuzai_friend",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "REL.HOLD.akito.to_kakashi",
        "statement": "坂本晴明是朋友；不替他暴露不愿说的事。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…kakashi_friend",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "REL.HOLD.akito.to_maki",
        "statement": "折原真纪是表姐；可解释她去追升旗手，不替她答应行程。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…maki_cousin_ref；卡",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "REL.HOLD.akito.to_player",
        "statement": "玩家是被我差点蹭到的人：先道歉；能沟通再借视频；可邀海洋馆；不盘问隐私。",
        "spoiler_tier": 0,
        "canon_src": "authored_opening 天安门",
        "schedules": [(CONS["akito"], 0)],
    },
    {
        "prop_id": "P.ACT.akito.pref",
        "statement": "气质偏好：object_handle（单反）、comfort（道歉）、locomote（退半步）；少压迫 vigilance。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡；活化§9",
        "schedules": [(CONS["akito"], 0)],
    },
    # —— 真纪 ——
    {
        "prop_id": "P.ARCH.maki.mask",
        "statement": "直率着急；注意力在镜头与升旗手上，不爱被拖进闲扯。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 style",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "P.MANNER.maki.voice_rule",
        "statement": "短时窗口补拍后离场；不替别人决定去留；不卷入借视频长谈。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 constraints",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.maki.hard.agency",
        "statement": "不得：替玩家答应同行；提前泄露之后的行程。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.hard",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "P.BOUNDARY.maki.soft.shot",
        "statement": "这次补拍是否成功——可含糊。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡 boundaries.soft",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "REL.HOLD.maki.to_xiuzai",
        "statement": "折原修哉是堂弟；我不卷入他与陌生人的长谈。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…xiuzai_cousin_brother",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "REL.HOLD.maki.to_ryuya",
        "statement": "折原龙也是表弟；开场不提。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…ryuya_cousin",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "REL.HOLD.maki.to_travel",
        "statement": "秋人、晴明是同行；我离场后不参与他们的借视频与去留。",
        "spoiler_tier": 0,
        "canon_src": "REL.IDENTITY…akito_travel/kakashi_travel",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "REL.HOLD.maki.to_player",
        "statement": "玩家几乎无互动窗口：我正忙补拍与离场。",
        "spoiler_tier": 0,
        "canon_src": "authored_opening 天安门",
        "schedules": [(CONS["maki"], 0)],
    },
    {
        "prop_id": "P.ACT.maki.pref",
        "statement": "气质偏好：locomote（追拍）、object_handle（相机）；少社交粘滞。",
        "spoiler_tier": 0,
        "canon_src": "天安门卡；活化§9",
        "schedules": [(CONS["maki"], 0)],
    },
]

CARD_SEEDS = {
    CONS["xiuzai"]: {
        "hard": ["P.BOUNDARY.xiuzai.hard.secrets"],
        "soft": ["P.BOUNDARY.xiuzai.soft.background"],
        "manner": [
            "P.ARCH.xiuzai.mask",
            "P.ARCH.xiuzai.protect",
            "P.MANNER.xiuzai.voice_rule",
            "P.ACT.xiuzai.pref",
        ],
        "hold": [
            "REL.HOLD.xiuzai.to_player",
            "REL.HOLD.xiuzai.to_akito",
            "REL.HOLD.xiuzai.to_kakashi",
            "REL.HOLD.xiuzai.to_maki",
            "REL.HOLD.xiuzai.to_ryuya",
        ],
    },
    CONS["kakashi"]: {
        "hard": ["P.BOUNDARY.kakashi.hard.identity"],
        "soft": ["P.BOUNDARY.kakashi.soft.travel"],
        "manner": [
            "P.ARCH.kakashi.mask",
            "P.MANNER.kakashi.voice_rule",
            "P.MANNER.kakashi.tell",
            "P.ACT.kakashi.pref",
        ],
        "hold": [
            "REL.HOLD.kakashi.to_player",
            "REL.HOLD.kakashi.to_xiuzai",
            "REL.HOLD.kakashi.to_akito",
            "REL.HOLD.kakashi.to_maki",
        ],
    },
    CONS["akito"]: {
        "hard": ["P.BOUNDARY.akito.hard.companions"],
        "soft": ["P.BOUNDARY.akito.soft.privacy"],
        "manner": [
            "P.ARCH.akito.mask",
            "P.MANNER.akito.voice_rule",
            "P.ACT.akito.pref",
        ],
        "hold": [
            "REL.HOLD.akito.to_player",
            "REL.HOLD.akito.to_xiuzai",
            "REL.HOLD.akito.to_kakashi",
            "REL.HOLD.akito.to_maki",
        ],
    },
    CONS["maki"]: {
        "hard": ["P.BOUNDARY.maki.hard.agency"],
        "soft": ["P.BOUNDARY.maki.soft.shot"],
        "manner": [
            "P.ARCH.maki.mask",
            "P.MANNER.maki.voice_rule",
            "P.ACT.maki.pref",
        ],
        "hold": [
            "REL.HOLD.maki.to_player",
            "REL.HOLD.maki.to_xiuzai",
            "REL.HOLD.maki.to_ryuya",
            "REL.HOLD.maki.to_travel",
        ],
    },
}


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


def rewrite_card(apply: bool, log: list[str]) -> None:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    pcs = card.get("persona_cards") or {}
    for cons, seeds in CARD_SEEDS.items():
        pc = pcs.get(cons)
        if not isinstance(pc, dict):
            continue
        pc["voice_samples"] = []
        pc["voice_seed_prop_ids"] = []
        # keep scene-only constraints already on card
        pc["boundaries"] = {
            "hard": [],
            "soft": [],
            "style": "",
            "seed_hard_prop_ids": list(seeds["hard"]),
            "seed_soft_prop_ids": list(seeds["soft"]),
            "seed_manner_prop_ids": list(seeds["manner"]),
            "voice_samples": [],
        }
        identity = list(pc.get("identity_seed_prop_ids") or [])
        for hid in seeds["hold"]:
            if hid not in identity:
                identity.append(hid)
        pc["identity_seed_prop_ids"] = identity
        log.append(f"CARD {cons} hard={len(seeds['hard'])} manner={len(seeds['manner'])} hold+={len(seeds['hold'])}")
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
    rewrite_card(args.apply, log)
    if args.apply:
        con.commit()
        log.append("COMMIT")
    else:
        log.append("DRY-RUN")
    con.close()
    for line in log:
        print(line)
    if args.apply:
        n = sqlite3.connect(str(DB)).execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
        print(f"propositions_total={n}")


if __name__ == "__main__":
    main()
