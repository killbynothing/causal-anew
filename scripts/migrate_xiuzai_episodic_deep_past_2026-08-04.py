# -*- coding: utf-8 -*-
"""Migrate Xiuzai WMAIN episodic deep-past memories (screening 2026-08-04).

Idempotent via anchor prefix [XM-Mx].
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

# (cons_id, screen_id, text, anchor, emo_tag, salience, available_ch, projection_text, reveal_ch)
ROWS: list[tuple] = [
    # ----- 长期远前史 (Long-Term) -----
    (
        "C.xiuzai.WMAIN",
        "XM-M1",
        "深夜在客厅，我与龙也并排坐在床边。我把耳朵贴紧那扇薄薄的木门，听着父母在门后低声谈判如何分割这个家。四周安静得让我觉得呼吸都很压抑。",
        "[XM-M1]父母离婚夜贴门|n108e:L771-773",
        "grief_family_break",
        0.95,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M2",
        "脚下散落着几周都拼不好的风景拼图。龙也伸出手，将最后一块极其准确地按进了确切位置，用冰冷语气说‘他们吵架了呢’。我咬着嘴唇，死死盯着拼图没说话。",
        "[XM-M2]拼图最后一块|n108e:L774-782",
        "silence_puzzles",
        0.92,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M3",
        "父亲脱下警服西装就会痛骂律师与犯人，动辄训斥我和龙也要‘像个正义男子汉’。在警视厅他是名人，但在家里那冷硬的压抑感，让我知道他绝不是个优秀的父亲。",
        "[XM-M3]父亲严厉训斥|n70-87:L2879-2895",
        "resentment_father",
        0.88,
        0,
        "我父亲以前是警察。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M4",
        "我知道佐佐木前辈是父亲的旧部，也知道龙也进警视厅时受过他很多照顾。这种折原家与警视厅根深蒂固的人际网络，总是让我觉得抗拒。",
        "[XM-M4]警察佐佐木前辈|n1-69:L6316-6336",
        "police_senior",
        0.80,
        0,
        "我认识一个姓佐佐木的警察。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M5",
        "判决下来后，母亲在玄关收拾行李带走龙也。我一个人站在阴影里，看着门缝透进来的冷光，以及父亲喝闷酒的背影，第一次感觉到彻底的孤寂。",
        "[XM-M5]母亲带走龙也|n108e:L784-787",
        "family_separation",
        0.98,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M6",
        "比赛前夕，龙也劝我不要搞没用的代码，被我拒绝后，他一怒之下砸毁了我的电脑和硬盘。我没有跟他吵闹，默默扫掉碎片，打着手电熬夜重写了代码。",
        "[XM-M6]毁硬盘与重写|n1-69:L6382-6401",
        "resignation_brother",
        0.96,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M7",
        "为了帮龙也在警视厅破案，我深夜坐在屏幕前帮他编写数据库查询工具。看着他飞速升职，我既为他骄傲，又隐隐觉得我们之间的距离越来越远。",
        "[XM-M7]编写后台数据库|n1-69:L6324-6336",
        "brother_promotion",
        0.85,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M8",
        "龙也去中国办案并决定和魏初结婚。临走前我们在小酒馆喝清酒，他第一次露出那种轻松的微笑，我当时觉得，他终于脱离了折原家的宿命了。",
        "[XM-M8]出国结婚清酒|n1-69:L6324",
        "relief_brother",
        0.94,
        0,
        "我有个哥哥，在国外结婚了。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M9",
        "姐夫刘云天曾经调侃过‘是不是折原家的人都要找中国伴侣’。龙也喜欢中国是因为那里的自由，而我也深受他们的影响。",
        "[XM-M9]姐夫调侃中国|n1-69:L6338",
        "china_affinity",
        0.82,
        0,
        "我姐夫说我们家的人都喜欢中国。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M10",
        "魏初在大学大四实习时就认识了去办案的龙也，两人交情极深。我知道她在这个世界上，是龙也极少数绝对信任的人之一。",
        "[XM-M10]魏初与龙也旧识|n1-69:L8116",
        "weichu_ryuya_past",
        0.86,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M11",
        "高中时我和沉稳理智的秋人是同窗，后来他在机场去德国留学。那是我少有的青春羁绊，距离虽然远了，但偶尔还能联系。",
        "[XM-M11]秋人德国留学|n1-69:L566",
        "friendship_warmth",
        0.75,
        0,
        "我有个高中同学叫秋人，刚从德国回来。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M12",
        "表姐真纪每天像老妈子一样给我送饭唠叨，我当面调侃‘明白姐夫为何要逃到中国工作了’，结果被她掐着脖子狠狠教训了一顿。",
        "[XM-M12]表姐唠叨被掐|n1-69:L577-588",
        "family_tease",
        0.80,
        0,
        "我表姐很啰嗦，难怪我姐夫受不了逃到中国工作。",
        8,
    ),
    
    # ----- 中短期近前史 (Medium/Short-Term) -----
    (
        "C.xiuzai.WMAIN",
        "XM-M13",
        "四年前那个阳光明媚的清晨，我在书房的监控视频中捕捉到了那个陌生人的痕迹，意识到龙也的‘死’背后是一个巨大的骗局，当时我感到了彻骨的寒意。",
        "[XM-M13]清晨监控陌生人|n1-69:L8856-8870",
        "trauma_morning",
        1.0,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M14",
        "葬礼上，我拿着龙也那张带着浅笑的假遗照，面对警视厅同僚的吊唁一言不发。我觉得全世界都在演戏欺骗我，极度荒诞且冰冷。",
        "[XM-M14]假遗照与吊唁|n1-69:L4107",
        "fake_funeral",
        0.98,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M15",
        "我彻底崩溃后，真纪表姐不忍心丢下我，单方面留下一封离婚信就从中国飞回日本照顾我，和姐夫长期分居。对此我一直深感内疚。",
        "[XM-M15]真纪留信返日|n1-69:L6376",
        "sister_sacrifice",
        0.95,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M16",
        "龙也出事后，中岛医生长期负责我的 PTSD 心理治疗。他每次拉开窗帘叹气时，我都觉得他认定我这辈子好不了了，直到卡卡西出现他才如释重负。",
        "[XM-M16]中岛医生长诊|n1-69:L2934",
        "doctor_care",
        0.89,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M17",
        "我抑郁颓废的最深处，真纪每天跑到我租屋的厨房下厨，抽油烟机隆隆作响，她骂骂咧咧地逼我按时吃饭。嫌弃归嫌弃，但我常常觉得鼻酸。",
        "[XM-M17]真纪下厨油烟机|src待核:L9163旁证",
        "maki_cooking",
        0.90,
        0,
        "真纪做饭很好吃，但我讨厌她开抽油烟机的声音。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M18",
        "我知道真纪和中岛医生一直暗中通电话密谋我的治疗计划，真纪对他说‘卡卡西在所以修哉没事’。他们把我当成易碎品，我很清楚这一点。",
        "[XM-M18]真纪医生密谋|n1-69:L5501-5513",
        "maki_nakajima_plan",
        0.88,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M19",
        "那段重度抑郁的日子里，我连续几个月拉紧窗帘关在黑暗的房间里，连下床喝水都懒得动弹，觉得自己是个彻底的废人。",
        "[XM-M19]关灯闭门期|n1-69:L6079-6085",
        "depression_ptsd",
        0.96,
        0,
        "我以前是个彻底的死宅，讨厌出门。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M20",
        "闭门期间我疯狂看《NARUTO》，看着卡卡西、鸣人那些虚构人物的悲欢离合，以此来麻木自己对现实的痛苦。那时候我只想逃避。",
        "[XM-M20]看动漫逃避现实|n1-69:L540",
        "naruto_escape",
        0.85,
        0,
        "我是个沉迷《NARUTO》的废柴宅男。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M21",
        "秋人听说我状态稳定些后，特意从德国飞回东京看我。我们坐在旧咖啡馆里聊天，让我久违地感受到了一点同窗的温度。",
        "[XM-M21]秋人回国看望|n1-69:L6738",
        "reunion_warmth",
        0.82,
        0,
        "秋人刚从德国进修回来。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M22",
        "那天雨夜的巷口，我看到了一身异界装束、眼神茫然落寞的卡卡西。凭着黑客直觉与同病相怜感，我把他拽回了租屋，那是改变一切的起点。",
        "[XM-M22]雨夜收留卡卡西|n1-69:L379",
        "cohabitation_bond",
        0.99,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M23",
        "为了让他能生活，我三台显示器代码交错，连夜黑进户籍系统伪造了日本身份和银行卡。看着他拿到证件时僵硬的脸，我笑得非常得意。",
        "[XM-M23]伪造身份得意|n1-69:L539-540",
        "hacker_craft",
        0.92,
        0,
        None,
        None,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M24",
        "看卡卡西整天面无表情、眼神死寂，我特意跑去书店买了一本空白的 18 禁封面《亲热天堂》扔给他打发时间，说那是他的生活必需品。",
        "[XM-M24]买亲热天堂|n1-69:L4026",
        "playful_tease",
        0.88,
        0,
        "我给他买了本《亲热天堂》，这是生活必需品。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M25",
        "在居酒屋吃饭时，看卡卡西闷着不说话，我特意夹走他盘子里的鸡丁逼他开口，嚷嚷着‘不跟我吐槽今天就不给你饭吃’。",
        "[XM-M25]居酒屋抢鸡丁|n1-69:L505-536",
        "dinner_tease",
        0.87,
        0,
        "那家伙闷得很，得抢他盘子里的鸡丁他才肯说话。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M26",
        "深夜我追踪卡卡西和晴明小公司服务器的异常访问，发现那些跳跃 IP 极度复杂且似曾相识。我皱起眉，暗中拦下了攻击，什么也没告诉卡卡西。",
        "[XM-M26]排查跳跃IP|n1-69:L555-557",
        "tech_vigilance",
        0.93,
        0,
        "我帮晴明的公司看过网络防线，抓过几只小虫子。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M27",
        "在日本餐馆吃所谓的‘宫保鸡丁’时，我咬着筷子死死盯着盘子，满脸怨念地抱怨这根本不正宗，完全是骗人的。",
        "[XM-M27]怨念不正宗鸡丁|n1-69:L505-508",
        "foodie_obsession",
        0.80,
        0,
        "日本餐馆的宫保鸡丁一点都不正宗，完全是骗人的。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M28",
        "我对卡卡西和真纪无数次嚷嚷过：等以后去了中国，一定要去杭州西湖边的‘楼外楼’，尝尝最正宗的东坡肉，那才叫绝！",
        "[XM-M28]向往楼外楼东坡肉|n1-69:L510-511",
        "dongpo_meat",
        0.82,
        0,
        "我以后一定要去杭州西湖的楼外楼吃正宗的东坡肉。",
        8,
    ),

    # ----- 近期刚到中国 (Arrival in China) -----
    (
        "C.xiuzai.WMAIN",
        "XM-M29",
        "刚出首都机场候机厅，就看到姐夫刘云天竭力挥舞着手臂大声呼喊迎接。我面无表情地看着他过分热情的表演，早就习以为常。",
        "[XM-M29]机场姐夫挥手接机|n1-69:L2047-2059",
        "airport_arrival",
        0.84,
        0,
        "刚下飞机就看到我姐夫在机场大呼小叫地接机，丢人。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M30",
        "跟姐夫站在一起的魏初，对初次见面的卡卡西毫无兴趣，只顶着一张职场化的冷脸抬手说了句‘你好’。我冷眼旁观，什么都没解释。",
        "[XM-M30]初见魏初冷脸|n1-69:L2069-2077",
        "weichu_first_meet",
        0.85,
        0,
        "魏初看到卡卡西的时候，摆着一张职场化的冷脸。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M31",
        "在姐夫开的面包车里，魏初突然惊悚地八卦我是不是出柜了，还嘲笑卡卡西的银发是杀马特和 coser。我实在被逼得烦躁，冷着脸低吼了一句‘魏初，够了’。",
        "[XM-M31]大巴车魏初八卦|n1-69:L2109-2185",
        "van_gossip",
        0.89,
        0,
        "魏初在车上非八卦我出柜，还嘲笑卡卡西是杀马特，简直烦人。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M32",
        "被安排去魏初家借宿，我连日未眠在玄关险些摔倒。我懒得理人，直接走进客房关上门，把卡卡西和那只奇胖无比的暹罗猫‘懒蛋’丢在客厅。",
        "[XM-M32]借宿魏初家遇猫|n1-69:L2210-2260",
        "weichu_house",
        0.91,
        0,
        "我现在借宿在魏初家，她养了只奇胖无比的暹罗猫叫懒蛋。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M33",
        "真纪的好友吴夏弦带着单反相机一路跟我们来到了中国。我始终对他保持警惕，毕竟我知道他办公室里保留着四年前龙也的秘密档案。",
        "[XM-M33]吴夏弦跟来中国|n1-69:L2495|★时序待核",
        "photographer_friend",
        0.88,
        0,
        "吴叔拿着单反相机非要跟我们来中国采风。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M34",
        "下午风很大，我漫步在天安门广场上，侧头看着卡卡西摘下口罩好奇打量人群。那一刻，我觉得能带他重回阳光下，心里有一种宽慰与安宁。",
        "[XM-M34]广场摘口罩宽慰|n1-69:L510-520",
        "tiananmen_stroll",
        0.96,
        0,
        "下午我们在天安门广场逛了逛，人很多风很大。",
        8,
    ),
    (
        "C.xiuzai.WMAIN",
        "XM-M35",
        "受晴明委托做无名技术顾问，我和卡卡西在涩谷同一屋檐下生活了一年多，已经完全习惯了他那种冷幽默和我日常蹭饭的生活节奏。",
        "[XM-M35]涩谷同居做顾问|authored",
        "daily_cohabit",
        0.90,
        0,
        "我和卡卡西在涩谷合租了一年多，我是个普通的网络顾问。",
        8,
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

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    log: list[str] = []
    for row in ROWS:
        upsert(cur, row, args.apply, log)
    if args.apply:
        con.commit()
        log.append("COMMIT")
    else:
        log.append("DRY-RUN only")
    # summary counts
    n = cur.execute(
        "SELECT COUNT(*) FROM slow_memory WHERE cons_id=? AND available_ch IS NOT NULL",
        ("C.xiuzai.WMAIN",),
    ).fetchone()[0]
    log.append(f"COUNT C.xiuzai.WMAIN with available_ch={n}")
    con.close()
    for line in log:
        print(line)

if __name__ == "__main__":
    main()
