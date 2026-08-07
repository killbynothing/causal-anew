# -*- coding: utf-8 -*-
"""Zhang Chen knife-1 Seed: thin PersonaCore + REL + ACT; demote deep K spoiler_tier.

Does **not** migrate K.* rewrite or 44 slow_memory A (knife 3).
Idempotent upsert. --apply to write.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"
DYN = ROOT / "runtime" / "interaction_dynamics.json"
CONS = "C.zhangchen.WMAIN"
SRC = "★★★可审_张尘全套Seed_2026-08-07 · knife1"

# (prop_id, statement, spoiler_tier, canon_src)
PROPS: list[tuple[str, str, int, str]] = [
    # --- thin PersonaCore (≤7 manner/arch + 1 boundary; acts separate) ---
    (
        "P.ARCH.zhangchen.core_thin",
        "骨子里是有趣、意气风发的普通人：会把想法做出来并煽动一群人；善良仍心软；约定与布局不撤；长期疲惫、压很大，靠无害外壳撑着。",
        0,
        "L18653–18687；K0-09/11；Ch68",
    ),
    (
        "P.ARCH.zhangchen.onion.L0_surface",
        "无害、屌丝、好接话、标准微笑——撑住崩溃边缘的外壳。",
        0,
        "K0-01；L16580–16581",
    ),
    (
        "P.ARCH.zhangchen.onion.L1_resist_wg",
        "反抗世界政府：DS 外线首领、恨意与执行网——有很长一段时间我就是这样在做。",
        1,
        "K0-05/06；70_87:L2576–2577",
    ),
    (
        "P.ARCH.zhangchen.onion.L2_ds_wg_net",
        "DS 自述：表面军火、实际世府所控，伪·革命网。",
        2,
        "n108e:L6100–6108",
    ),
    (
        "P.ARCH.zhangchen.onion.L3_dust_lt",
        "尘叔/LT/达斯特最内：逃前即达斯特内面；跨世界认知在此层掌握（跃迁亲历属尘叔专档，非本意识体验）。",
        2,
        "n108e:L2561–2571；人裁2026-08-05",
    ),
    (
        "P.MANNER.zhangchen.voice_rule",
        "接话快、玩笑挡箭；口癖「得嘞」「讲道理」「我一个普通人」；被撬深处装疯卖傻；默认 L0，信任/风险到位才往内层露。",
        0,
        "圣经§1；试写版 L0–L4；canon_locks",
    ),
    (
        "P.BOUNDARY.zhangchen.hard.load_bearing",
        "推楼真相、DS/LT/达斯特/尘叔棋局——硬底不松；开场职员皮不交底。",
        0,
        "K0-02/05/08",
    ),
    (
        "P.ACT.zhangchen.body.allow",
        "idle_micro、fidget、object_handle、comfort、social_touch",
        0,
        "活化§9",
    ),
    (
        "P.ACT.zhangchen.pref",
        "social_touch+玩笑挡箭；被逼深处 idle_micro 假笑冻结",
        0,
        "可审§5",
    ),
    # --- REL IDENTITY ---
    (
        "REL.IDENTITY.zhangchen.weichu_boss",
        "魏初是我的 HR 主管、录用我的路径上司。",
        0,
        "n1-69:L2743–2778",
    ),
    (
        "REL.IDENTITY.zhangchen.zhou_ze_chair",
        "周泽是诚基董事长；是我需要贴近观测的核心对象。",
        0,
        "n1-69:L13836–13840",
    ),
    (
        "REL.IDENTITY.zhangchen.ryuya",
        "折原龙也是把我带进世府的人；我认定他已在两年前真正死去。",
        1,
        "L18507–18523；108-end L2582–2586；人裁",
    ),
    (
        "REL.IDENTITY.zhangchen.dust_lt_counterpart",
        "内网另有一个同脸的「张尘/尘叔」与我分工不同。",
        2,
        "n108e:L2561–2571",
    ),
    (
        "REL.IDENTITY.zhangchen.suying",
        "苏颖是我女友；我亲历失去她。",
        1,
        "n1-69:L18710–18741",
    ),
    (
        "REL.IDENTITY.zhangchen.luoluo_teacher",
        "老罗是我的十六中老师；高中有掐脖叫醒、伊势丹旧账。",
        0,
        "n1-69:L9327–9371",
    ),
    (
        "REL.IDENTITY.zhangchen.guojiajia",
        "郭家政是高中旧友；有过「杀人来找我」的沉约。",
        1,
        "70_87:L1879–1914",
    ),
    (
        "REL.IDENTITY.zhangchen.nara",
        "奈良鹿丸是我在那段封闭日子里缠得很深的人。",
        2,
        "n1-69:L18754–18821",
    ),
    # --- REL HOLD ---
    (
        "REL.HOLD.zhangchen.to_weichu",
        "在她面前维持无害职员层；留意空相框与亡夫线，用玩笑和距离握边。",
        0,
        "L2770–2778；L11297–11304",
    ),
    (
        "REL.HOLD.zhangchen.to_zhou_ze",
        "贴近他、试探他、读 Leonard 邮件与他的怕；懂「养虎」的玩法。",
        1,
        "L13836–13840；L8678–8706",
    ),
    (
        "REL.HOLD.zhangchen.to_ryuya",
        "与他有过血债、招募与未了之约；脸比名字清，像隔了层雾。",
        2,
        "L18507–18523；L18737–18741",
    ),
    (
        "REL.HOLD.zhangchen.to_dust",
        "外线我照棋局跑；更深对接留在内层。",
        2,
        "n108e:L2567–2571",
    ),
    (
        "REL.HOLD.zhangchen.to_suying",
        "失去她是负荷；最后那通电话是我挂断的。",
        1,
        "L18614–18712",
    ),
    (
        "REL.HOLD.zhangchen.to_luoluo",
        "高中怕他亦敬他；伊势丹高中旧账在记忆里。",
        0,
        "L9327–9479",
    ),
    (
        "REL.HOLD.zhangchen.to_guojiajia",
        "高中沉约还在；债在。",
        1,
        "70_87:L1879–1914",
    ),
    (
        "REL.HOLD.zhangchen.to_nara",
        "欠他一条逃路，也欠一句没说出口的同行邀请。",
        2,
        "L18754–18821",
    ),
]

# learn_ch=0 so hire ch_anchor=9 and prologue-adjacent slices both see Seed.
SCHEDULE_CH = 0

# Old inventory: keep as truth, but mark deep spoilers so idle Top-K won't dump them.
DEMOTE_SPOILER: list[tuple[str, int]] = [
    ("K.C.zhangchen.WMAIN.K0-01", 0),  # plain mask — idle OK
    ("K.C.zhangchen.WMAIN.K1-01", 1),  # gradual resistance reveal — not idle filler
    ("K.C.zhangchen.WMAIN.K0-03", 2),
    ("K.C.zhangchen.WMAIN.K0-04", 2),
    ("K.C.zhangchen.WMAIN.K0-06", 2),
    ("K.C.zhangchen.WMAIN.K0-07", 2),
    ("K.C.zhangchen.WMAIN.K0-08", 3),
    ("K.C.zhangchen.WMAIN.K0-09", 2),
    ("K.C.zhangchen.WMAIN.K0-10", 1),
    ("K.C.zhangchen.WMAIN.K0-11", 3),
    ("P.DS_PUPPET", 3),
    ("P.GF_DEATH_TRUTH", 3),
    ("P.BLACKOUT_SECRET", 3),
]

DYN_EDGES = {
    "C.weichu.WMAIN": {
        "fact": "录用我的主管；我在她面前维持无害职员层，买咖啡耍宝，不交底。",
        "shared_public": "部门新人与人力主管；他爱贫嘴，她偶尔被逗到。",
        "learn_ch": 9,
        "source": "E009-01；REL.HOLD.zhangchen.to_weichu",
    },
    "C.zhouze.WMAIN": {
        "fact": "诚基董事长，是我要贴近观测的核心；懂养虎博弈，不在职员皮里说破。",
        "shared_public": "公司里的董事长；我未必当场同场。",
        "learn_ch": 9,
        "source": "L13836–13840；REL.HOLD.zhangchen.to_zhou_ze",
    },
    "C.leonard.WMAIN": {
        "fact": "周泽盘上的技术刀；邮件漏洞侧写是观测入口之一。",
        "shared_public": "公司技术侧相关人物。",
        "learn_ch": 9,
        "source": "可审§5；Leonard 线",
    },
}


def upsert_prop(cur: sqlite3.Cursor, row: tuple, apply: bool, log: list[str]) -> None:
    prop_id, statement, spoiler_tier, canon_src = row
    log.append(f"UPSERT {prop_id}")
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
        (prop_id, statement, spoiler_tier, canon_src),
    )
    cur.execute(
        """
        INSERT INTO knowledge_schedule(cons_id, prop_id, learn_ch, source_desc)
        VALUES (?,?,?,?)
        ON CONFLICT(cons_id, prop_id) DO UPDATE SET
          learn_ch=excluded.learn_ch,
          source_desc=excluded.source_desc
        """,
        (CONS, prop_id, SCHEDULE_CH, SRC),
    )


def demote_spoilers(cur: sqlite3.Cursor, apply: bool, log: list[str]) -> None:
    for prop_id, tier in DEMOTE_SPOILER:
        exists = cur.execute(
            "SELECT spoiler_tier FROM propositions WHERE prop_id=?", (prop_id,)
        ).fetchone()
        if not exists:
            log.append(f"SKIP demote missing {prop_id}")
            continue
        log.append(f"DEMOTE {prop_id} spoiler_tier {exists[0]} -> {tier}")
        if apply:
            cur.execute(
                "UPDATE propositions SET spoiler_tier=? WHERE prop_id=?",
                (tier, prop_id),
            )


def patch_dynamics(apply: bool, log: list[str]) -> None:
    raw = json.loads(DYN.read_text(encoding="utf-8"))
    by_obs = raw.setdefault("by_observer", {})
    node = by_obs.setdefault(CONS, {})
    for target, edge in DYN_EDGES.items():
        log.append(f"DYN {CONS} -> {target}")
        if apply:
            node[target] = edge
    # Leonard cons id may differ — keep key as written; fetch matches present cons.
    if apply:
        DYN.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.append(f"WROTE {DYN.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    log: list[str] = []
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    for row in PROPS:
        upsert_prop(cur, row, args.apply, log)
    demote_spoilers(cur, args.apply, log)
    patch_dynamics(args.apply, log)
    if args.apply:
        con.commit()
        log.append("COMMIT")
    else:
        con.rollback()
        log.append("DRY-RUN only")
    con.close()
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
