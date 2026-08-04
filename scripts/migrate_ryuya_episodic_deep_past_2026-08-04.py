# -*- coding: utf-8 -*-
"""Migrate Ryuya dual-cons episodic deep-past memories (screening 2026-08-04 改2).

Human cuts applied:
- W1-M1 = first awareness of other consciousness
- Opening speak whitelist: brother / married-anonymous / cafe layer only
- Do not cut bank; W1 jump/Dust friend line required

Does NOT change schema. Uses existing slow_memory columns.
speak_policy encoded: reveal_ch=None + full text for actor recall;
opening speech gated by card disclosure / future speak_policy (M2).

Idempotent via anchor prefix [W1-Mx] / [WM-Mx].
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

# (cons_id, screen_id, text, anchor, emo_tag, salience, available_ch, projection_text, reveal_ch)
# projection_text: optional safer surface if later reveal gating used; opening 绝口 still stores full text for 可想.
ROWS: list[tuple] = [
    # ----- W1 A1 -----
    (
        "C.ryuya.W1",
        "W1-M1",
        "国中那一枪之后，我第一次清楚感到：有另一个意识。身体不受控地哭、道歉，虔诚得不像谎言；"
        "有人问「你知道自己做了什么吗」，我却在问——大脑里的另一个我，你究竟是谁。",
        "[W1-M1]国中觉察另一意识|n108e:L806-815",
        "uncanny_possession",
        0.96,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M2",
        "这个世界的他给我留了一个空位，让不同世界的两个意识可以共同存在。"
        "他长期不夺回控制权，安静看着，说喜欢看大家愉悦的样子。",
        "[W1-M2]留空位共驻|n108e:L1105-1139;L914-915",
        "coexistence_quiet",
        0.9,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M3",
        "我看见他重压张尘、亲手推下那位女友、坐在警车里漠视崩溃；"
        "当张尘踏入世界政府的那一刻，我悲伤得几乎让意识崩塌——却拦不住实行的那一侧。",
        "[W1-M3]目睹推女友与警车|n108e:L932-945",
        "grief_powerless",
        0.95,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M4",
        "共驻之后，这具身体的少年史我也持有：母亲笑与暴并存、离婚夜耳贴门、"
        "打乱修哉几小时拼完的风景拼图、他仍跟在身后喊哥哥。"
        "那是身体的过去；开枪取乐的主叙不归我抢。",
        "[W1-M4]身体史童年版|n108e:L759-788",
        "distant_familiar",
        0.85,
        0,
        "我有个弟弟。",
        1,
    ),
    # ----- W1 A2 jump -----
    (
        "C.ryuya.W1",
        "W1-M5",
        "与挚友之间有过那样的约定与怒斥：如果这是命运，接受它，然后摧毁它。"
        "偏离时我会扇他、吼他，最后仍把这句话交到他手里。",
        "[W1-M5]接受摧毁约定|n70-87:Ch84:L4265-4377",
        "fury_to_entrust",
        0.98,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M6",
        "他跳转离开时有三秒「电梯」。后来我每一次跳转都麻木复读同一套提示，"
        "却必须轻声念完「电梯即将向上」才敢合眼——总想那三秒里他到底想了什么。",
        "[W1-M6]电梯仪式|n108e:L5597-5608",
        "numb_ritual",
        0.97,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M7",
        "三万多次跳转寻他。睁眼先看自己年龄成了习惯；第30541次却是幼小双手握枪、对面血泊中的妇女。"
        "脑内第一次响起与我相同的声音：「你是谁，为什么可以控制我的身体。」"
        "我抓住这人格分裂的机会——只为找到张尘，这一次不想再失败。",
        "[W1-M7]30541幼手握枪|n108e:L5630-5654",
        "obsession_edge",
        0.99,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M8",
        "修哉曾愤怒推开想把你从仪器上撤下的人；抢救回来的只是脑死亡的活标本。"
        "他关在白板与公式的办公室里，说约好了一定接你回来。"
        "一定要找到你，然后带你回家——那是我们跳转的执着原因。",
        "[W1-M8]带你回家|n108e:L5656-5677",
        "devotion_guilt",
        0.99,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M9",
        "最初意识跳转有去无回。后来修哉完善了仪器；暗物质与WIMP被观测到的消息撼动全世界，"
        "也撑起「还能继续跳、还能找」的冷硬背景。热的只有执念。",
        "[W1-M9]跳转技术脉络|n108e:L5679-5701",
        "cold_tech_hot_will",
        0.88,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M10",
        "达斯特只是阿尘在世界政府内的代号；计划因DUST被称作RTW-LT-DS。"
        "某次我只能送他到透明舱门前：「我大概只能送你到这里了。」"
        "整栋晃动时我说：无论如何一定要阻止。门合上，火光涌起，电梯上行。",
        "[W1-M10]送舱一定要阻止|n108e:L1854-1882",
        "farewell_urgency",
        0.97,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M11",
        "（旁证烙印）后文有人向修哉点破：温和的那一侧恐怕来自其他世界，以意识跃迁进入这具身体；"
        "尘叔对此一清二楚。这支撑我与挚友线的互认——我不是这世界原生的那一层。",
        "[W1-M11]尘叔清楚跃迁旁证|n108e:L5441-5464",
        "identity_confirm",
        0.86,
        0,
        None,
        None,
    ),
    # ----- W1 authored -----
    (
        "C.ryuya.W1",
        "W1-M12",
        "街角咖啡馆。我促成了那次「泼袖」——对方以为自己手滑，我没点破，只笑着让对方坐下赔一杯。"
        "之后隔三差五又碰巧遇见，不留正式联系方式，一来二去成了可以抬杠也会沉默的朋友。两年了。",
        "[W1-M12]咖啡馆泼袖两年|authored_opening",
        "warm_acquaintance",
        0.92,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.W1",
        "W1-M13",
        "第一世界的修哉交给我的古铜色金属挂坠，此刻还在我身上。指尖知道那金属的凉。"
        "今夜临别前必须交到眼前这个朋友手里——还没交。",
        "[W1-M13]挂坠在身未交|authored_opening",
        "hope_relief",
        0.94,
        0,
        None,
        None,
    ),
    # ----- WMAIN B1 -----
    (
        "C.ryuya.WMAIN",
        "WM-M1",
        "记忆中母亲微笑与暴躁共同存在着。父亲面带愁容时，我才真正懂得「精神分裂」这个词。",
        "[WM-M1]母精神分裂|n108e:L759-761",
        "cold_awakening",
        0.9,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M2",
        "父母决定分开的夜，我耳朵贴门。修哉拼完风景拼图说「他们吵架了」——安静在他理解里反而像吵架。"
        "我走过去打乱那幅他几小时拼完、我要几星期的图。这大概就是嫉妒。打骂他，他仍只喊哥哥。",
        "[WM-M2]打乱拼图|n108e:L771-782",
        "jealousy_kin",
        0.93,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M3",
        "母亲被送去国外疗养，婚姻结束。她想带走修哉，他却留下跟我。"
        "不多喝酒的父亲那晚喝醉，重复叹息：希望龙也可以一直都是个正常的孩子。",
        "[WM-M3]父醉希望正常|n108e:L784-787",
        "expectation_crush",
        0.91,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M4",
        "国中那年真纪更黏修哉，我最后的安慰崩塌。我对父亲、表姐、弟弟说对不起——"
        "可开枪不是为了保护父亲，只是想看头被子弹崩碎、血浆飞溅。十几年用微笑对无数人撒谎。",
        "[WM-M4]国中开枪取乐|n108e:L789-810",
        "kill_pleasure_mask",
        0.98,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M5",
        "同一枪后，我无法控制身体：像有另一个人在操纵我哭、道歉。完全不像谎言。"
        "那是我第一次被另一意识上台——失控，且清醒地感到失控。",
        "[WM-M5]身体被夺哭道歉|n108e:L812-815",
        "loss_of_control",
        0.97,
        0,
        None,
        None,
    ),
    # ----- WMAIN B2 -----
    (
        "C.ryuya.WMAIN",
        "WM-M6",
        "为重获组织信任，我从日本辞职到中国定居、成了有家庭的人——做给家人和朋友看，等他们放松警惕。"
        "然后我亲自安排一出戏，杀了父亲。坦白时手不停摩擦掌心、发抖。"
        "擒拿术是父亲教的；他察觉政府与我替政府办事时，我不能让他的死毫无意义。",
        "[WM-M6]弑父戏|n1-69:Ch60:L18886-18909",
        "guilt_exchange",
        1.0,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M7",
        "对张尘：邀约攻占各种联系方式；在十六中正门亲手把他的女友推下去；"
        "自己坐在警车里看着他把学生揍出血、看着他崩溃——脸没有变过。",
        "[WM-M7]推女友警车漠视|n1-69:L18721-18738;n108e:L942-943",
        "cold_execution",
        1.0,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M8",
        "切断监控后我对张尘说：不认同肃清那套理念。也说，我有个亲生弟弟折原修哉，他是天才——"
        "嫉妒也不假，可当他喊我老哥，我下不了手去杀这样的天才。",
        "[WM-M8]切监控谈修哉|n1-69:Ch60:L18854-18930",
        "helpless_kin",
        0.94,
        0,
        "我有个弟弟。",
        1,
    ),
    # ----- WMAIN B3 -----
    (
        "C.ryuya.WMAIN",
        "WM-M9",
        "真纪从小阿龙阿龙使唤我，我笑着做。人缘好时被人设计，想办法；不行就有修哉出主意脱身。"
        "我们从一开始就像在互相保护。",
        "[WM-M9]与修哉互相保护|n1-69:L6233-6300",
        "warmth_duty",
        0.87,
        0,
        "我有个弟弟。",
        1,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M10",
        "我对真纪说过：阿修是测试过的真正天才。看着自己的手掌问——为什么他的天赋我一点都没有？"
        "又说：真好啊，那是我弟弟。",
        "[WM-M10]看手掌说天才弟|n1-69:L6268-6280",
        "jealousy_love",
        0.92,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M11",
        "警校后实习，修哉故意打架再报警帮我快速转正；我进警视厅涉外，上司佐佐木宪二。"
        "出国办案常带修哉当翻译。我说喜欢中国，怂恿一行人旅行；后来看上了一位中国姑娘——成了婚。"
        "（开场对玩家：只可淡说已婚，不露是谁。）",
        "[WM-M11]涉外中国结婚|n1-69:L6316-6336",
        "career_china_marriage",
        0.9,
        0,
        "我结婚了。",
        1,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M12",
        "我向修哉解释过：父亲离婚不是感情不和，是怕工作危险连累家人；曾想让母亲带走孩子移民，"
        "我说什么也不肯走，修哉更不愿离开我。谁都没能拗过谁。",
        "[WM-M12]解释离婚真因|n1-69:L6344-6352",
        "family_bind",
        0.88,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M13",
        "世界级编程赛前，我劝修哉不要参赛，越吵越凶。劝不服，我毁了他的电脑和硬盘、删掉记录。"
        "他表面道歉，背着我重写寄出——这件事当时只有他跟真纪说过。",
        "[WM-M13]毁硬盘劝赛|n1-69:L6382-6401",
        "hard_refusal",
        0.93,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M14",
        "中国办案时遇见大四实习的她；回国后国际长途；有近一年忙到少联系，感情淡了却质变。"
        "后来移民结婚。我说：放在心底的感情才最不可能被淡忘。懒蛋粘我；有一阵子我情绪很低沉。"
        "（开场不露配偶姓名。）",
        "[WM-M14]遇妻结婚懒蛋|n1-69:L8116-8173",
        "married_low_mood",
        0.91,
        0,
        "我结婚了。",
        1,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M15",
        "我有事没事爱唱那首歌。涉外外勤，佐佐木器重。婚后不久有一天我很懊恼地说：给佐佐木警部添麻烦了。",
        "[WM-M15]歌与佐佐木麻烦|n1-69:L9560-9607",
        "unease_duty",
        0.84,
        0,
        None,
        None,
    ),
    (
        "C.ryuya.WMAIN",
        "WM-M16",
        "懒蛋几乎只跟我亲。我说恐怕自己有什么动物的体质，常看它往身上蹭，就抱着它。",
        "[WM-M16]懒蛋动物体质|n1-69:L6047-6048",
        "soft_habit",
        0.8,
        0,
        None,
        None,
    ),
]


def upsert(cur: sqlite3.Cursor, row: tuple, apply: bool, log: list[str]) -> None:
    cons, sid, text, anchor, emo, sal, avail, proj, reveal = row
    existing = cur.execute(
        "SELECT mem_id FROM slow_memory WHERE cons_id=? AND anchor LIKE ?",
        (cons, f"[{sid}]%"),
    ).fetchone()
    if existing:
        log.append(f"UPDATE {cons} {sid} mem_id={existing[0]}")
        if apply:
            cur.execute(
                """
                UPDATE slow_memory SET
                  text=?, anchor=?, emo_tag=?, salience=?, available_ch=?,
                  projection_text=?, reveal_ch=?, src_event=NULL, run=0
                WHERE mem_id=?
                """,
                (text, anchor, emo, sal, avail, proj, reveal, existing[0]),
            )
        return
    log.append(f"INSERT {cons} {sid}")
    if apply:
        cur.execute(
            """
            INSERT INTO slow_memory(
              run, cons_id, text, anchor, salience, emo_tag, src_event,
              available_ch, projection_text, reveal_ch, embedding
            ) VALUES (0,?,?,?,?,?,NULL,?,?,?,NULL)
            """,
            (cons, text, anchor, sal, emo, avail, proj, reveal),
        )


def align_legacy_pendant(cur: sqlite3.Cursor, apply: bool, log: list[str]) -> None:
    """Keep mem#12 in sync with W1-M13 if present; prefer tagged row as canonical."""
    row = cur.execute(
        "SELECT mem_id, anchor FROM slow_memory WHERE mem_id=12"
    ).fetchone()
    if not row:
        return
    if row[1] and str(row[1]).startswith("[W1-M13]"):
        return
    tagged = cur.execute(
        "SELECT mem_id FROM slow_memory WHERE cons_id=? AND anchor LIKE ?",
        ("C.ryuya.W1", "[W1-M13]%"),
    ).fetchone()
    if tagged:
        log.append(f"DEL legacy pendant mem_id=12 (superseded by {tagged[0]})")
        if apply:
            cur.execute("DELETE FROM slow_memory WHERE mem_id=?", (12,))
    else:
        log.append("REWRITE mem_id=12 -> W1-M13 tag")
        if apply:
            # find W1-M13 payload
            for r in ROWS:
                if r[1] == "W1-M13":
                    cur.execute(
                        """
                        UPDATE slow_memory SET
                          cons_id=?, text=?, anchor=?, emo_tag=?, salience=?,
                          available_ch=0, projection_text=NULL, reveal_ch=NULL, src_event=NULL
                        WHERE mem_id=12
                        """,
                        (r[0], r[2], r[3], r[4], r[5]),
                    )
                    break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    log: list[str] = []
    for row in ROWS:
        upsert(cur, row, args.apply, log)
    align_legacy_pendant(cur, args.apply, log)
    if args.apply:
        con.commit()
        log.append("COMMIT")
    else:
        log.append("DRY-RUN only")
    # summary counts
    for cons in ("C.ryuya.W1", "C.ryuya.WMAIN"):
        n = cur.execute(
            "SELECT COUNT(*) FROM slow_memory WHERE cons_id=? AND available_ch IS NOT NULL",
            (cons,),
        ).fetchone()[0]
        log.append(f"COUNT {cons} with available_ch={n}")
    con.close()
    for line in log:
        print(line)


if __name__ == "__main__":
    main()
