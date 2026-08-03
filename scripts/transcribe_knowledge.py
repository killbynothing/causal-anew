#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# transcribe_knowledge.py —— M-6: 细剖知识变动列转录至 SQLite 数据库的 propositions 与 knowledge_schedule 表脚本

import os
import re
import sqlite3
import sys

DB_FILE = os.path.join("data", "world_truth.db")
INPUT_FILE = os.path.join("analysis", "细剖事件表", "Ch.8-12细剖事件表.md")

ALIAS_MAP = {
    # 8个老角色及其同位体/别名映射
    "~张尘": "C.zhangchen.WMAIN",
    "~修哉": "C.xiuzai.WMAIN",
    "~折原修哉": "C.xiuzai.WMAIN",
    "~折原龙也": "C.ryuya.WMAIN",
    "~卡卡西": "C.kakashi.WMAIN",
    "~魏初": "C.weichu.WMAIN",
    "~刘云天": "C.liuyuntian.WMAIN",
    "~吴夏弦": "C.wuxiaxian.WMAIN",
    "~川口秋人": "C.akito.WMAIN",
    
    # 辅助建档角色（中岛、老郭、罗洁、柳絮等）
    "~中岛": "C.nakajima.WMAIN",
    "~中岛医生": "C.nakajima.WMAIN",
    "~中岛今朝": "C.nakajima.WMAIN",
    "~郭家政": "C.guojiazheng.WMAIN",
    "~罗洁": "C.luojie.WMAIN",
    "~老罗": "C.luojie.WMAIN",
    "~柳絮": "C.liuxu.WMAIN",
    
    # 新建档角色及其别名映射
    "~斑驳": "C.banbo.WMAIN",
    "~敖斑驳": "C.banbo.WMAIN",
    "~雨璇": "C.yuxuan.WMAIN",
    "~徐雨璇": "C.yuxuan.WMAIN",
    "~潘雨璇": "C.yuxuan.WMAIN",
    "~真纪": "C.maki.WMAIN",
    "~折原真纪": "C.maki.WMAIN",
    "~佐助": "C.sasuke.WMAIN",
    "~宇智波佐助": "C.sasuke.WMAIN",
    "~小樱": "C.sakura.WMAIN",
    "~樱": "C.sakura.WMAIN",
    "~鸣人": "C.naruto.WMAIN",
    "~漩涡鸣人": "C.naruto.WMAIN",
    "~大和": "C.yamato.WMAIN",
    "~大和天藏": "C.yamato.WMAIN",
    "~折原达也": "C.itachi.WMAIN",
    "~鼬": "C.itachi.WMAIN",
    "~宇智波鼬": "C.itachi.WMAIN",
    "~佐井": "C.sai.WMAIN",
    "~山本澈": "C.yamamoto_che.WMAIN",
    "~源晃": "C.minamoto.WMAIN",
    "~源": "C.minamoto.WMAIN",
    "~Leonard": "C.leonard.WMAIN",
    "~莱纳德": "C.leonard.WMAIN",
    "~费恩": "C.fein.WMAIN",
    "~费恩·考夫曼": "C.fein.WMAIN",
    "~周泽": "C.zhouze.WMAIN",

    # 特殊同位体与跨世界线别名
    "~张尘(异世界)": "C.dust.W1",
    "~折原龙也(异世界)": "C.ryuya.W1",
    "~折原达也(新身体)": "C.itachi.WMAIN",
    "~卡卡西(坂本晴明)": "C.kakashi.WMAIN",
}

DISCARD_WITNESSES = {
    "~硬套路柳絮", "~一身黑", "~量产人造人", "~无人机", "~黑客", "~医生", 
    "~警员", "~化学老师", "~老机机长", "~老机长", "~军长", "~老婆婆", 
    "~风骚女经理", "~源晃秘书", "~老罗丈夫", "~卡布"
}

def normalize_alias(w):
    if not w.startswith('~'):
        return w
    if w in DISCARD_WITNESSES:
        return None
    # 1. 先尝试完整匹配（比如带括号的同位体）
    if w in ALIAS_MAP:
        return ALIAS_MAP[w]
    # 2. 如果不匹配，再脱去括号匹配
    base = re.sub(r'\(.*?\)|（.*?）', '', w).strip()
    if base in DISCARD_WITNESSES:
        return None
    if base in ALIAS_MAP:
        return ALIAS_MAP[base]
    return w

def parse_legacy_knowledge(kb_change, witnesses_raw, existing_cons):
    # witnesses 转换为正式 ID 列表
    witnesses = []
    for w in witnesses_raw:
        norm = normalize_alias(w)
        if norm:
            witnesses.append(norm)
    
    # 找出在 witnesses 中的已建档原生角色
    local_cons = [w for w in witnesses if w in existing_cons]
    if not local_cons:
        return []
        
    matched = []
    # 检查文本中是否包含了这些在场者的简短显示名字（如“张尘”、“修哉”等）
    id_to_name = {
        "C.zhangchen.WMAIN": ["张尘", "尘叔"],
        "C.dust.W1": ["张尘", "尘叔"],
        "C.xiuzai.WMAIN": ["修哉", "折原修哉"],
        "C.xiuzai.W3": ["修哉", "晴明", "黑发卡卡西"],
        "C.ryuya.WMAIN": ["龙也", "折原龙也"],
        "C.ryuya.W1": ["龙也", "折原龙也"],
        "C.kakashi.WMAIN": ["卡卡西", "坂本晴明"],
        "C.weichu.WMAIN": ["魏初"],
        "C.liuyuntian.WMAIN": ["刘云天", "云天"],
        "C.wuxiaxian.WMAIN": ["吴夏弦", "夏弦"],
        "C.akito.WMAIN": ["川口秋人", "秋人"],
        "C.akito.W3": ["川口秋人", "秋人"],
        "C.banbo.WMAIN": ["斑驳", "敖斑驳"],
        "C.yuxuan.WMAIN": ["雨璇", "徐雨璇", "潘雨璇"],
        "C.maki.WMAIN": ["真纪", "折原真纪"],
        "C.sasuke.WMAIN": ["佐助", "宇智波佐助"],
        "C.sakura.WMAIN": ["小樱", "春野樱", "樱"],
        "C.naruto.WMAIN": ["鸣人", "漩涡鸣人"],
        "C.yamato.WMAIN": ["大和", "大和天藏"],
        "C.liuxu.WMAIN": ["柳絮"],
        "C.itachi.WMAIN": ["鼬", "宇智波鼬", "折原达也", "达也"],
        "C.sai.WMAIN": ["佐井"],
        "C.yamamoto_che.WMAIN": ["山本澈", "山本总经理"],
        "C.minamoto.WMAIN": ["源晃", "源先生"],
        "C.leonard.WMAIN": ["莱纳德", "Leonard"],
        "C.fein.WMAIN": ["费恩"],
        "C.zhouze.WMAIN": ["周泽"]
    }
    
    for cid in local_cons:
        names = id_to_name.get(cid, [])
        if any(n in kb_change for n in names):
            matched.append(cid)
            
    # 如果有“等”字或“众人”等复数代词，或者没有任何在场者名字出现在文本中
    if any(x in kb_change for x in ["等", "俩", "两人", "三人", "大家", "众人", "我们"]):
        return local_cons
        
    # 如果在场者中有人的名字被提到了，就仅返回这些人
    if matched:
        return matched
        
    # 如果都没有被提到，且不包含全局词，就返回全部在场的已注册角色
    if any(x in kb_change for x in ["全人类", "读者", "观众"]):
        return []
        
    return local_cons

def parse_markdown_table(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")
        
    rows = []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    header = None
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
        
        # 分割并剥离首尾空串
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if not parts:
            continue
            
        # 跳过 Markdown 表格分割行 (如 |---|---|)
        if all(re.match(r'^[-:]+$', p) for p in parts if p):
            continue
            
        if header is None:
            header = parts
            continue
            
        # 补齐长度对齐
        if len(parts) < len(header):
            parts += [''] * (len(header) - len(parts))
        elif len(parts) > len(header):
            parts = parts[:len(header)]
            
        row_dict = dict(zip(header, parts))
        rows.append(row_dict)
        
    return rows

def process_and_validate(rows_data, conn):
    cur = conn.cursor()
    
    # 查出已建档的意识 ID
    cur.execute("SELECT cons_id FROM consciousnesses")
    existing_cons = {r[0] for r in cur.fetchall()}
    
    propositions_to_insert = []
    schedule_to_insert = []
    
    for row in rows_data:
        uid = row.get('event_uid', '').strip()
        if not uid or uid == 'event_uid':
            continue
            
        # 校验 event_uid 格式并得出章号
        match_uid = re.match(r'^E(\d{3})-(\d{2})$', uid)
        if not match_uid:
            raise ValueError(f"[Error] Invalid event_uid format: '{uid}'")
            
        ch = int(match_uid.group(1))
        
        # 读取知识变动列
        kb_change = row.get('知识变动', '').strip()
        if not kb_change or kb_change in ['无', '-', '暂无']:
            continue
            
        # 按照分号切分多个命题项
        items = [item.strip() for item in kb_change.split(';') if item.strip()]
        for idx, item in enumerate(items, start=1):
            prop_id = f"TEMP_{uid.replace('-', '_')}_{idx}"
            canon_src = row.get('canon_src', '').strip()
            
            if '←' in item:
                parts = [p.strip() for p in item.split('←', 1)]
                cons_ids_str = parts[0]
                statement = parts[1]
                
                # 支持逗号拆分多个意识 ID
                cons_ids_raw = [c.strip() for c in cons_ids_str.split(',') if c.strip()]
                cons_ids = []
                for c_id in cons_ids_raw:
                    norm = normalize_alias(c_id)
                    if norm:
                        cons_ids.append(norm)
            else:
                statement = item
                witnesses_str = row.get('在场者', '').strip()
                witnesses_raw = [w.strip() for w in witnesses_str.split(',') if w.strip()]
                cons_ids = parse_legacy_knowledge(statement, witnesses_raw, existing_cons)
            
            # 无论意识是否建档，都将临时命题记录存入 propositions
            propositions_to_insert.append((
                prop_id,
                statement,
                0,  # spoiler_tier
                f"{uid} ({canon_src})" if canon_src else uid
            ))
            
            for cons_id in cons_ids:
                # 校验意识 ID
                if cons_id.startswith('~'):
                    # 未建档角色，跳过插入 knowledge_schedule (防止外键约束报错)
                    print(f"[Skip Unregistered] Skip schedule insert for unregistered: '{cons_id}' in event {uid}")
                    continue
                    
                if cons_id not in existing_cons:
                    # 既不以 ~ 开头，又不在意识表里，警告并跳过
                    print(f"[Warning] Skip schedule insert for unrecognized: '{cons_id}' in event {uid}", file=sys.stderr)
                    continue
                    
                # 插入已建档的意识 ID
                schedule_to_insert.append((
                    cons_id,
                    prop_id,
                    ch,  # learn_ch
                    uid  # source_desc
                ))
            
    return propositions_to_insert, schedule_to_insert

def insert_to_db(props, schedules, conn):
    cur = conn.cursor()
    
    # 写入 propositions 表
    prop_count = 0
    for p in props:
        cur.execute("""
            INSERT OR REPLACE INTO propositions (prop_id, statement, spoiler_tier, canon_src)
            VALUES (?, ?, ?, ?)
        """, p)
        prop_count += 1
        
    # 写入 knowledge_schedule 表
    sched_count = 0
    for s in schedules:
        cur.execute("""
            INSERT OR REPLACE INTO knowledge_schedule (cons_id, prop_id, learn_ch, source_desc)
            VALUES (?, ?, ?, ?)
        """, s)
        sched_count += 1
        
    conn.commit()
    print(f"Successfully transcribed {prop_count} propositions and {sched_count} schedule entries into database.")

def main():
    if not os.path.exists(DB_FILE):
        print(f"Error: Database {DB_FILE} not found.", file=sys.stderr)
        sys.exit(1)
        
    input_paths = []
    if len(sys.argv) > 1:
        input_paths = [sys.argv[1]]
    else:
        # 自动扫描 analysis/细剖事件表 目录下的所有细剖事件表
        files_dir = os.path.join("analysis", "细剖事件表")
        for filename in sorted(os.listdir(files_dir)):
            if filename.endswith("细剖事件表.md"):
                input_paths.append(os.path.join(files_dir, filename))
                
    if not input_paths:
        print("Error: No event files found.", file=sys.stderr)
        sys.exit(1)
        
    print(f"Using input files: {input_paths}")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON;")
    
    try:
        all_raw_rows = []
        for path in input_paths:
            print(f"Parsing input file: {path}")
            raw_rows = parse_markdown_table(path)
            print(f"  Parsed {len(raw_rows)} raw rows.")
            all_raw_rows.extend(raw_rows)
            
        props, schedules = process_and_validate(all_raw_rows, conn)
        insert_to_db(props, schedules, conn)
    except Exception as e:
        print(f"Transcription failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
