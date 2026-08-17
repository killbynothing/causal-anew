import sqlite3
import re
import os
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = str(ROOT / "data" / "world_truth.db")
MD_DIR = str(ROOT / "docs" / "plans") + os.sep

def get_character_id_from_filename(filename):
    # e.g., ★★★筛查_akito_开场前深过去_2026-08-04.md -> akito
    m = re.search(r'★★★筛查_([a-zA-Z0-9_]+)_开场前深过去', filename)
    return m.group(1) if m else None

def parse_md_file(filepath):
    memories = []
    edges = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Extract Facets (Slow Memory / Propositions)
    # Regex to match the markdown table rows in the Facet section
    facet_section = re.search(r'## 2\. 人格核区.*?(?=## 3\.)', content, re.DOTALL)
    if facet_section:
        rows = re.findall(r'\|\s*(Mem_[a-zA-Z0-9_]+)\s*\|\s*\*\*([^\*]+)\*\*\s*\[(情景记忆 slow_memory|事实记忆 propositions)\]：(.*?)\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|', facet_section.group(0))
        for row in rows:
            mem_id, title, mem_type, desc, evidence, disclose = [x.strip() for x in row]
            memories.append({
                'id': mem_id,
                'title': title,
                'type': 'slow_memory' if 'slow_memory' in mem_type else 'proposition',
                'desc': desc,
                'evidence': evidence,
                'disclose': disclose
            })
            
    # Extract Edges
    edge_section = re.search(r'## 3\. 关系图区.*?(?=## 4\.)', content, re.DOTALL)
    if edge_section:
        rows = re.findall(r'\|\s*(Rel_[a-zA-Z0-9_]+)\s*\|\s*`([a-zA-Z0-9_]+) → ([a-zA-Z0-9_]+)`\s*\((.*?)\)\s*\|\s*(.*?)\|\s*(.*?)\|\s*([^\|]+)\s*\|\s*([^\|]+)\s*\|', edge_section.group(0))
        for row in rows:
            edge_id, src, dst, relation_type, emotional_texture, info_asym, policy, evidence = [x.strip() for x in row]
            edges.append({
                'id': edge_id,
                'src': src,
                'dst': dst,
                'relation_type': relation_type,
                'emotional_texture': emotional_texture,
                'info_asym': info_asym,
                'policy': policy,
                'evidence': evidence
            })
            
    return memories, edges

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    md_files = glob.glob(os.path.join(MD_DIR, '★★★筛查_*_开场前深过去_2026-08-04.md'))
    
    total_slow = 0
    total_prop = 0
    total_edges = 0
    
    for filepath in md_files:
        char_id = get_character_id_from_filename(filepath)
        if not char_id:
            continue
            
        memories, edges = parse_md_file(filepath)
        
        for m in memories:
            if m['type'] == 'slow_memory':
                cursor.execute("""
                    INSERT OR REPLACE INTO slow_memory 
                    (cons_id, screen_id, text, anchor, emo_tag, salience, available_ch, projection_text, reveal_ch)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"C.{char_id}", m['id'], m['desc'], m['evidence'], m['title'], 0.8, 0, None, None
                ))
                total_slow += 1
            else:
                cursor.execute("""
                    INSERT OR REPLACE INTO propositions 
                    (worldline, run, ch_anchor, entity_a, prop_type, entity_b, value, canon_src)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    'alpha', 0, 0, f"C.{char_id}", 'persona_facet', m['id'], m['desc'], m['evidence']
                ))
                total_prop += 1
                
        for e in edges:
            cursor.execute("""
                INSERT OR REPLACE INTO propositions 
                (worldline, run, ch_anchor, entity_a, prop_type, entity_b, value, canon_src)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'alpha', 0, 0, f"C.{e['src']}", 'social_habit', f"C.{e['dst']}", 
                f"[{e['relation_type']}] {e['emotional_texture']} Policy: {e['policy']}", 
                e['evidence']
            ))
            
            # Default to guarded for most to avoid FSM crash, unless specified
            state = 'guarded'
            if '信任' in e['relation_type'] or '死党' in e['relation_type']:
                state = 'open'
                
            cursor.execute("""
                INSERT OR IGNORE INTO affect_state 
                (worldline, run, ch_anchor, subject_id, target_id, current_state, trust_val, tension_val)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'alpha', 0, 0, f"C.{e['src']}", f"C.{e['dst']}", state, 50, 50
            ))
            total_edges += 1

    conn.commit()
    conn.close()
    
    print(f"Migration Complete!")
    print(f"Inserted/Updated {total_slow} slow_memory records.")
    print(f"Inserted/Updated {total_prop} persona propositions.")
    print(f"Inserted/Updated {total_edges} social_habit edges.")

if __name__ == '__main__':
    migrate()
