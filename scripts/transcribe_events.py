#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe_events.py —— M-4: 细剖事件行转录至 SQLite 数据库 events 表脚本
支持 Markdown 表格解析，字段映射校验，意识 ID 外键约束，以及引文长度核验。
"""
import os
import re
import json
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

def parse_markdown_table(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")
        
    events = []
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
        events.append(row_dict)
        
    return events

def process_and_validate(events_data, conn):
    cur = conn.cursor()
    
    # 查出已建档的意识 ID
    cur.execute("SELECT cons_id FROM consciousnesses")
    existing_cons = {r[0] for r in cur.fetchall()}
    
    # 查出已存在的 worldlines
    cur.execute("SELECT wl_id FROM worldlines")
    existing_wls = {r[0] for r in cur.fetchall()}
    
    processed_events = {}
    child_to_parent = {}  # succ_id -> parent_id
    
    for row in events_data:
        uid = row.get('event_uid', '').strip()
        if not uid or uid == 'event_uid':
            continue
            
        # 1. 校验 event_uid 格式 (E{章:03d}-{序:02d})
        match_uid = re.match(r'^E(\d{3})-(\d{2})$', uid)
        if not match_uid:
            raise ValueError(f"[Error] Invalid event_uid format: '{uid}'")
            
        ch = int(match_uid.group(1))
        seq = int(match_uid.group(2))
        event_id = ch * 100 + seq
        
        # 2. 校验章号
        ch_anchor = int(row.get('ch', ch))
        
        # 3. 校验场景 (限制长度 <= 12)
        scene = row.get('场景', '').strip()
        if len(scene) > 12:
            raise ValueError(f"[Error] Scene length exceeds 12 characters: '{scene}' in event {uid}")
        location_id = scene.split('·')[0] if '·' in scene else scene
        
        # 4. 校验在场者外键
        witnesses_str = row.get('在场者', '').strip()
        witnesses_raw = [w.strip() for w in witnesses_str.split(',') if w.strip()]
        witnesses = []
        for w in witnesses_raw:
            norm = normalize_alias(w)
            if norm:
                witnesses.append(norm)
        for w in witnesses:
            if not w.startswith('~') and w not in existing_cons:
                raise ValueError(f"[Error] Unregistered consciousness ID: '{w}' in event {uid}. Must start with '~' if unregistered.")
                
        # 5. 校验 canon_src 引文长度限制 (引文 <= 15字)
        canon_src = row.get('canon_src', '').strip()
        quotes = re.findall(r'["“](.*?)[”"]', canon_src)
        for q in quotes:
            if len(q) > 15:
                raise ValueError(f"[Error] Canon quotation exceeds 15 characters limit: '{q}' in event {uid}")
                
        # 6. 处理因果链接映射 (解析 →E008-01 建立 parent_event)
        causality = row.get('因果后果', '').strip()
        successors = re.findall(r'→(E\d{3}-\d{2})', causality)
        for succ in successors:
            m_succ = re.match(r'^E(\d{3})-(\d{2})$', succ)
            if m_succ:
                succ_ch = int(m_succ.group(1))
                succ_seq = int(m_succ.group(2))
                succ_id = succ_ch * 100 + succ_seq
                child_to_parent[succ_id] = event_id
                
        # 7. 构建 payload
        payload = {
            "event_uid": uid,
            "witnesses": witnesses,
            "action": row.get('动作', '').strip(),
            "motive": row.get('动机', '').strip(),
            "causality": causality,
            "knowledge_change": row.get('知识变动', '').strip(),
            "items": row.get('物权/物件', '').strip(),
            "intervention_flag": row.get('干涉点候选', '').strip(),
            "canon_src": canon_src
        }
        
        processed_events[event_id] = {
            "event_id": event_id,
            "run": 0,
            "wl_id": "W-MAIN",
            "t_game": 0,
            "ch_anchor": ch_anchor,
            "location_id": location_id,
            "etype": "action",
            "payload": payload,
            "parent_event": None
        }
        
    # 第二遍遍历，挂载 parent_event
    for event_id, ev in processed_events.items():
        parent_id = child_to_parent.get(event_id)
        ev["parent_event"] = parent_id
        
    return processed_events

def insert_to_db(processed_events, conn):
    cur = conn.cursor()
    inserted_count = 0
    for event_id, ev in processed_events.items():
        cur.execute("""
            INSERT OR REPLACE INTO events (event_id, run, wl_id, t_game, ch_anchor, location_id, etype, payload, parent_event)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ev["event_id"],
            ev["run"],
            ev["wl_id"],
            ev["t_game"],
            ev["ch_anchor"],
            ev["location_id"],
            ev["etype"],
            json.dumps(ev["payload"], ensure_ascii=False),
            ev["parent_event"]
        ))
        inserted_count += 1
    conn.commit()
    print(f"Successfully transcribed {inserted_count} events into database '{DB_FILE}'.")

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
        all_raw_events = []
        for path in input_paths:
            print(f"Parsing input file: {path}")
            raw_events = parse_markdown_table(path)
            print(f"  Parsed {len(raw_events)} raw rows.")
            all_raw_events.extend(raw_events)
            
        processed = process_and_validate(all_raw_events, conn)
        insert_to_db(processed, conn)
    except Exception as e:
        print(f"Transcription failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
