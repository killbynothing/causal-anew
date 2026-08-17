# -*- coding: utf-8 -*-
"""Migrate Xiuzai relationships and social habits (affect_state, propositions)."""

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "world_truth.db"

# (run, cons_id, target, trust, intimacy, alert, fsm_state)
AFFECT_ROWS = [
    (0, "C.xiuzai.WMAIN", "C.ryuya.WMAIN", 10, 10, 0, "open"),
    (0, "C.xiuzai.WMAIN", "C.kakashi.WMAIN", 10, 8, 0, "open"),
    (0, "C.xiuzai.WMAIN", "weichu", 8, 7, 2, "open"),
    (0, "C.xiuzai.WMAIN", "liu_yuntian", 7, 6, 2, "probing"),
    (0, "C.xiuzai.WMAIN", "maki", 9, 8, 1, "open"),
    (0, "C.xiuzai.WMAIN", "nakajima", 6, 4, 8, "guarded"),
    (0, "C.xiuzai.WMAIN", "sasaki", 5, 3, 7, "guarded"),
    (0, "C.xiuzai.WMAIN", "wu_xiaxuan", 8, 6, 6, "guarded"),
    (0, "C.xiuzai.WMAIN", "akito", 7, 7, 1, "open"),
]

# (prop_id, statement, spoiler_tier, canon_src)
PROP_ROWS = [
    ("P.SHUYA_BROTHER_RYUYA", "修哉是龙也的亲弟弟", 0, "n108e"),
    ("P.MAKI_COUSIN_SHUYA", "真纪是修哉的表姐", 0, "n1-69"),
    ("P.LIU_HUSBAND_MAKI", "刘云天是真纪的丈夫", 0, "n1-69"),
    ("P.NAKAJIMA_DOCTOR_SHUYA", "中岛是修哉的主治医师", 0, "n1-69"),
    ("P.REL.SHUYA_RYUYA", "修哉对待龙也的社交模式：无法割舍的牵绊与抛弃创伤", 0, "authored"),
    ("P.REL.SHUYA_KAKASHI", "修哉对待卡卡西的社交模式：绝对安全区、唯一的例外、相互依赖", 0, "authored"),
    ("P.REL.SHUYA_WEICHU", "修哉对待魏初的社交模式：毫无边界感的损友、托底的长姐", 0, "authored"),
    ("P.REL.SHUYA_LIU", "修哉对待刘云天的社交模式：强势的保护伞、长兄的代偿", 0, "authored"),
    ("P.REL.SHUYA_MAKI", "修哉对待真纪的社交模式：愧疚与感激、烦人的母性羁绊", 0, "authored"),
    ("P.REL.SHUYA_NAKAJIMA", "修哉对待中岛的社交模式：防备且话中有话、克制的医患羁绊", 0, "authored"),
    ("P.REL.SHUYA_SASAKI", "修哉对待佐佐木的社交模式：警视厅的阴影、痛苦真相的传递者", 0, "authored"),
    ("P.REL.SHUYA_WU", "修哉对待吴夏弦的社交模式：利益同盟外衣下的默契与隐晦关怀", 0, "authored"),
    ("P.REL.SHUYA_AKITO", "修哉对待秋人的社交模式：正常社会的锚点、久违的同窗", 0, "authored"),
]

def upsert_affect(cur, row, apply, log):
    run, cons_id, target, trust, intimacy, alert, fsm_state = row
    existing = cur.execute(
        "SELECT rowid FROM affect_state WHERE run=? AND cons_id=? AND target=?",
        (run, cons_id, target)
    ).fetchone()
    if existing:
        log.append(f"UPDATE affect_state {cons_id} -> {target}")
        if apply:
            cur.execute(
                "UPDATE affect_state SET trust=?, intimacy=?, alert=?, fsm_state=? WHERE rowid=?",
                (trust, intimacy, alert, fsm_state, existing[0])
            )
    else:
        log.append(f"INSERT affect_state {cons_id} -> {target}")
        if apply:
            cur.execute(
                "INSERT INTO affect_state(run, cons_id, target, trust, intimacy, alert, fsm_state) VALUES (?,?,?,?,?,?,?)",
                row
            )

def upsert_prop(cur, row, apply, log):
    prop_id, statement, spoiler_tier, canon_src = row
    existing = cur.execute("SELECT prop_id FROM propositions WHERE prop_id=?", (prop_id,)).fetchone()
    if existing:
        log.append(f"UPDATE proposition {prop_id}")
        if apply:
            cur.execute(
                "UPDATE propositions SET statement=?, spoiler_tier=?, canon_src=? WHERE prop_id=?",
                (statement, spoiler_tier, canon_src, prop_id)
            )
    else:
        log.append(f"INSERT proposition {prop_id}")
        if apply:
            cur.execute(
                "INSERT INTO propositions(prop_id, statement, spoiler_tier, canon_src) VALUES (?,?,?,?)",
                row
            )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    log = []
    
    for row in AFFECT_ROWS:
        upsert_affect(cur, row, args.apply, log)
        
    for row in PROP_ROWS:
        upsert_prop(cur, row, args.apply, log)
        
    if args.apply:
        con.commit()
        log.append("COMMIT")
    else:
        log.append("DRY-RUN only")
        
    con.close()
    for line in log:
        print(line)

if __name__ == "__main__":
    main()
