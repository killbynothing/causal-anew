#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe_character_timelines.py
=================================
解析根目录下的 8 个角色时间线 Markdown 草案文件，并将它们灌入世界真值库 `world_truth.db`
的 `propositions` 与 `knowledge_schedule` 表中。
"""

import os
import re
import sqlite3
import sys

DB_FILE = os.path.join("data", "world_truth.db")

# 8个时间线文件与意识 ID 的映射
FILE_TO_CONS = {
    "_archive/角色时间线弃用系列/角色知识时间线_尘叔_试写版.md": "C.dust.W1",
    "_archive/角色时间线弃用系列/角色知识时间线_卡卡西_试写版.md": "C.kakashi.WMAIN",
    "_archive/角色时间线弃用系列/角色知识时间线_魏初_试写版.md": "C.weichu.WMAIN",
    "analysis/时间线/异世界魏初_真值事件与心智觉醒时间轴_整合版.md": "C.weichu.W1",
    "_archive/角色时间线弃用系列/角色知识时间线_张尘_试写版.md": "C.zhangchen.WMAIN",
    "_archive/角色时间线弃用系列/角色知识时间线_修哉_试写版.md": "C.xiuzai.WMAIN",
    # 龙也和秋人需要根据表格内的倾向面或段落做更细致的拆分
}

# 全局语义命题映射表，用来将角色时间线中的 ID 映射到正典定义的 P.* 命题
MAP_SEMANTIC = {
    # 卡卡西 C.kakashi.WMAIN
    ("C.kakashi.WMAIN", "K3-01"): "P.GF_DEATH_TRUTH",
    ("C.kakashi.WMAIN", "K3-02"): "P.RYUYA_DEATH_TRUTH",
    ("C.kakashi.WMAIN", "K3-04"): "P.RTW131_IDENTITY",
    ("C.kakashi.WMAIN", "K3-05"): "P.RTW_EXISTS",
    ("C.kakashi.WMAIN", "K4-01"): "P.SEIMEI_MACHINE",

    # 修哉 C.xiuzai.WMAIN
    ("C.xiuzai.WMAIN", "K3-01"): "P.GF_DEATH_TRUTH",
    ("C.xiuzai.WMAIN", "K3-02"): "P.RYUYA_DEATH_TRUTH",
    ("C.xiuzai.WMAIN", "K4-01"): "P.SEIMEI_MACHINE",

    # 张尘 C.zhangchen.WMAIN
    ("C.zhangchen.WMAIN", "K0-02"): "P.GF_DEATH_TRUTH",
    ("C.zhangchen.WMAIN", "K3-01"): "P.GF_DEATH_TRUTH",
    ("C.zhangchen.WMAIN", "K3-04"): "P.BLACKOUT_SECRET",
    ("C.zhangchen.WMAIN", "K0-05"): "P.DS_PUPPET",

    # 魏初 C.weichu.WMAIN
    ("C.weichu.WMAIN", "W0-01"): "P.WEICHU_WIDOW",
    ("C.weichu.WMAIN", "W1-03"): "P.RTW_EXISTS",
    ("C.weichu.WMAIN", "W2-01"): "P.GF_DEATH_TRUTH",

    # 尘叔 C.dust.W1
    ("C.dust.W1", "D0-02"): "P.DUST_CREATOR",
    ("C.dust.W1", "D0-04"): "P.FIRST_WORLD_PROMISE",
    ("C.dust.W1", "D0-05"): "P.GF_DEATH_TRUTH",

    # 龙也 C.ryuya.WMAIN / C.ryuya.W1
    ("C.ryuya.WMAIN", "R-WM-01"): "P.RTW_EXISTS",
    ("C.ryuya.W1", "R-WM-01"): "P.RTW_EXISTS",
    ("C.ryuya.WMAIN", "R-W1-01"): "P.DUST_CREATOR",
    ("C.ryuya.W1", "R-W1-01"): "P.DUST_CREATOR",
    ("C.ryuya.WMAIN", "R0-03"): "P.GF_DEATH_TRUTH",
    ("C.ryuya.W1", "R0-03"): "P.GF_DEATH_TRUTH",
    
    # 异世界魏初 C.weichu.W1
    ("C.weichu.W1", "W1-01"): "P.GF_DEATH_TRUTH", # 异世界张尘自杀
}

def parse_md_tables(filepath):
    """
    解析 Markdown 文件中的标题和表格行。
    返回一个 list of dict, 每个 dict 包含段落信息和行字典。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    current_h2 = ""
    current_h3 = ""
    table_headers = None
    in_table = False
    
    parsed_items = []
    
    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("## "):
            current_h2 = line_strip
            current_h3 = ""
            in_table = False
        elif line_strip.startswith("### "):
            current_h3 = line_strip
            in_table = False
            
        if line_strip.startswith("|"):
            parts = [p.strip() for p in line_strip.split("|")[1:-1]]
            if not parts:
                continue
            # 跳过 Markdown 表格的分隔符行 (---|---|)
            if all(re.match(r'^[-:]+$', p) for p in parts if p):
                continue
            
            if not in_table:
                table_headers = parts
                in_table = True
            else:
                row_dict = dict(zip(table_headers, parts))
                parsed_items.append({
                    "h2": current_h2,
                    "h3": current_h3,
                    "row": row_dict
                })
        else:
            in_table = False
            
    return parsed_items

def get_statement(row):
    for k, v in row.items():
        if any(x in k for x in ["命题", "事件"]):
            return v
    return ""

def get_nature(row):
    return row.get("性质", "").strip()

def get_canon_src(row):
    return row.get("原文对应", "").strip()

def extract_chapter(row, active_headings):
    """
    从行文本中提炼 learn_ch。
    """
    # 1. 检查是不是阶段 0 / 出场自带 / 共性层
    h_str = " ".join(active_headings).lower()
    if any(x in h_str for x in ["阶段 0", "阶段0", "自带", "共性"]):
        return 1
        
    # 2. 从“原文对应”或“节点”列匹配 Ch.X
    for col_val in row.values():
        m = re.search(r'Ch\.?\s*(\d+)', col_val)
        if m:
            return int(m.group(1))
            
    # 3. 从标题匹配 Ch.X
    for h in reversed(active_headings):
        m = re.search(r'Ch\.?\s*(\d+)', h)
        if m:
            return int(m.group(1))
            
    # 默认回退值为 1
    return 1

def main():
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file {DB_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

    # 获取数据库中所有存在的意识 ID，做校验用
    cur.execute("SELECT cons_id FROM consciousnesses")
    existing_cons = {r[0] for r in cur.fetchall()}

    # 准备写入数据库的记录列表
    props_to_insert = []
    schedules_to_insert = []

    # 清空这几个目标角色的旧知识调度表 (保留其它无关角色的，如 liuyuntian / wuxiaxian / banbo 等)
    target_cons_to_clear = {
        "C.dust.W1", "C.kakashi.WMAIN", "C.weichu.WMAIN", "C.weichu.W1",
        "C.zhangchen.WMAIN", "C.xiuzai.WMAIN", "C.xiuzai.W3",
        "C.ryuya.WMAIN", "C.ryuya.W1", "C.akito.WMAIN", "C.akito.W3"
    }
    
    for cid in target_cons_to_clear:
        cur.execute("DELETE FROM knowledge_schedule WHERE cons_id=?", (cid,))
    conn.commit()

    # 1. 遍历标准映射文件
    for filename, cons_id in FILE_TO_CONS.items():
        if not os.path.exists(filename):
            print(f"Warning: File {filename} not found, skip.")
            continue
            
        print(f"Processing timeline file: {filename} -> {cons_id}")
        items = parse_md_tables(filename)
        
        for item in items:
            row = item["row"]
            orig_id = row.get("#", "").strip()
            if not orig_id:
                continue
                
            statement = get_statement(row)
            nature = get_nature(row)
            canon_src = get_canon_src(row)
            
            # 计算 learn_ch
            learn_ch = extract_chapter(row, [item["h2"], item["h3"]])
            
            # 判断是否为未知 GAP，若为未知且没有显式标明终局解锁的，不在 schedule 中解锁
            if "未知GAP" in nature and "解锁" not in statement and "解锁" not in canon_src:
                # 仅作为 proposition 入账，但不加入任何人的 schedule
                prop_id = f"K.{cons_id}.{orig_id}"
                props_to_insert.append((prop_id, statement, 0, canon_src))
                continue
            
            # 命题语义 ID 归一化
            prop_key = (cons_id, orig_id)
            if prop_key in MAP_SEMANTIC:
                prop_id = MAP_SEMANTIC[prop_key]
                # 全局命题不需要重复写 propositions，它们由 import_db 初始化，我们只写入其 schedule 关系
            else:
                prop_id = f"K.{cons_id}.{orig_id}"
                props_to_insert.append((prop_id, statement, 0, canon_src))
                
            schedules_to_insert.append((cons_id, prop_id, learn_ch, f"性质:{nature} | 出处:{canon_src}"))

    # 2. 处理特殊的多意识文件：折原龙也
    ryuya_file = "_archive/角色时间线弃用系列/角色知识时间线_龙也_试写版.md"
    if os.path.exists(ryuya_file):
        print(f"Processing multi-persona file: {ryuya_file}")
        items = parse_md_tables(ryuya_file)
        for item in items:
            row = item["row"]
            # 龙也时间线第一列可能是 “节点” 或 “#”
            orig_id = (row.get("#") or row.get("节点") or "").strip()
            if not orig_id:
                continue
                
            statement = get_statement(row)
            nature = get_nature(row)
            canon_src = get_canon_src(row)
            倾向面 = row.get("倾向面", "").strip()
            
            # 计算 learn_ch
            learn_ch = extract_chapter(row, [item["h2"], item["h3"]])
            
            # 如果是未知 GAP 且没提解锁，不入 schedule
            if "未知GAP" in nature and "解锁" not in statement and "解锁" not in canon_src:
                props_to_insert.append((f"K.C.ryuya.WMAIN.{orig_id}", statement, 0, canon_src))
                continue

            # 龙也的倾向面决定它进入哪个意识的 schedule
            target_ids = []
            if "本体" in 倾向面 or "WM" in 倾向面:
                target_ids = ["C.ryuya.WMAIN"]
            elif "W1" in 倾向面:
                target_ids = ["C.ryuya.W1"]
            else:
                # 默认双方共有
                target_ids = ["C.ryuya.WMAIN", "C.ryuya.W1"]
                
            for cid in target_ids:
                prop_key = (cid, orig_id)
                if prop_key in MAP_SEMANTIC:
                    prop_id = MAP_SEMANTIC[prop_key]
                else:
                    prop_id = f"K.{cid}.{orig_id}"
                    props_to_insert.append((prop_id, statement, 0, canon_src))
                    
                schedules_to_insert.append((cid, prop_id, learn_ch, f"倾向:{倾向面} | 性质:{nature} | 出处:{canon_src}"))

    # 3. 处理特殊的多意识文件：川口秋人
    akito_file = "_archive/角色时间线弃用系列/角色知识时间线_秋人_试写版.md"
    if os.path.exists(akito_file):
        print(f"Processing multi-persona file: {akito_file}")
        items = parse_md_tables(akito_file)
        for item in items:
            row = item["row"]
            orig_id = row.get("#", "").strip()
            if not orig_id:
                continue
                
            statement = get_statement(row)
            nature = get_nature(row)
            canon_src = get_canon_src(row)
            
            # 区分本体和 W3 记录者
            h_str = " ".join([item["h2"], item["h3"]])
            if "W3" in h_str or "异世界记录者" in h_str:
                cid = "C.akito.W3"
                learn_ch = 1 # W3出场即全知
            else:
                cid = "C.akito.WMAIN"
                learn_ch = extract_chapter(row, [item["h2"], item["h3"]])
                
            if "未知GAP" in nature and "解锁" not in statement and "解锁" not in canon_src:
                props_to_insert.append((f"K.{cid}.{orig_id}", statement, 0, canon_src))
                continue

            prop_key = (cid, orig_id)
            if prop_key in MAP_SEMANTIC:
                prop_id = MAP_SEMANTIC[prop_key]
            else:
                prop_id = f"K.{cid}.{orig_id}"
                props_to_insert.append((prop_id, statement, 0, canon_src))
                
            schedules_to_insert.append((cid, prop_id, learn_ch, f"性质:{nature} | 出处:{canon_src}"))

    # 4. 特殊补充：修哉文件附录B提及的 C.xiuzai.W3
    # 我们可以手动将 C.xiuzai.W3 的 6 个全知命题补回 schedule，因为在 md 里它们被严格隔离在本体外，只有段落提醒。
    w3_xiuzai_schedules = [
        ('C.xiuzai.W3', 'P.RTW_EXISTS', 1, '参与早期开发计划并有记录'),
        ('C.xiuzai.W3', 'P.GF_DEATH_TRUTH', 1, '异世界历史常识'),
        ('C.xiuzai.W3', 'P.RYUYA_DEATH_TRUTH', 1, '参与第一世界因果设定'),
        ('C.xiuzai.W3', 'P.SEIMEI_MACHINE', 1, '机体自知本身即是机体'),
        ('C.xiuzai.W3', 'P.DUST_CREATOR', 1, '与尘叔深度合作'),
        ('C.xiuzai.W3', 'P.FIRST_WORLD_PROMISE', 1, '斯德哥尔摩约定的一方'),
    ]
    schedules_to_insert.extend(w3_xiuzai_schedules)

    # 写入 propositions
    props_count = 0
    for prop in props_to_insert:
        cur.execute("""
            INSERT OR REPLACE INTO propositions (prop_id, statement, spoiler_tier, canon_src)
            VALUES (?, ?, ?, ?)
        """, prop)
        props_count += 1
        
    # 写入 knowledge_schedule
    sched_count = 0
    for sched in schedules_to_insert:
        # 确保 consciousness 在意识表里已建档 (防止外键约束报错)
        if sched[0] not in existing_cons:
            print(f"[Warning] Skip schedule insert for unrecognized conscious ID: '{sched[0]}'")
            continue
            
        cur.execute("""
            INSERT OR REPLACE INTO knowledge_schedule (cons_id, prop_id, learn_ch, source_desc)
            VALUES (?, ?, ?, ?)
        """, sched)
        sched_count += 1

    conn.commit()
    conn.close()
    
    print(f"Successfully transcribed {props_count} custom propositions and {sched_count} schedules from timeline markdown files.")

if __name__ == "__main__":
    main()
