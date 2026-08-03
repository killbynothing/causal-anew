import sqlite3
import re
import os
import json
import subprocess
import sys
from db_indexes import ensure_indexes

DB_FILE = os.path.join("data", "world_truth.db")

# 1. 建立数据库连接，开启外键约束
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

# 2. 初始化表结构 (DDL)
def create_tables(conn):
    cursor = conn.cursor()
    
    # 世界线
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS worldlines (
      wl_id        TEXT PRIMARY KEY,
      parent_wl    TEXT REFERENCES worldlines(wl_id),
      desync_ms    INTEGER DEFAULT 0,
      note         TEXT
    );
    """)
    
    # 同位体
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS archetypes (
      arch_id      TEXT PRIMARY KEY,
      display_name TEXT NOT NULL
    );
    """)
    
    # 身体
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bodies (
      body_id      TEXT PRIMARY KEY,
      origin_wl    TEXT NOT NULL REFERENCES worldlines(wl_id),
      arch_id      TEXT REFERENCES archetypes(arch_id),
      body_type    TEXT NOT NULL CHECK(body_type IN ('human','artificial','machine_hybrid')),
      rtw_code     TEXT,
      note         TEXT
    );
    """)
    
    # 肉体跃迁
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS body_transfers (
      xfer_id      INTEGER PRIMARY KEY AUTOINCREMENT,
      body_id      TEXT NOT NULL REFERENCES bodies(body_id),
      from_wl      TEXT REFERENCES worldlines(wl_id),
      to_wl        TEXT NOT NULL REFERENCES worldlines(wl_id),
      via          TEXT,
      at_event     INTEGER,
      canon_src    TEXT
    );
    """)
    
    # 意识
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS consciousnesses (
      cons_id      TEXT PRIMARY KEY,
      native_wl    TEXT NOT NULL REFERENCES worldlines(wl_id),
      arch_id      TEXT NOT NULL REFERENCES archetypes(arch_id),
      jump_capable INTEGER DEFAULT 0,
      note         TEXT
    );
    """)
    
    # 意识占用身体
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS occupancy (
      occ_id       INTEGER PRIMARY KEY AUTOINCREMENT,
      body_id      TEXT NOT NULL REFERENCES bodies(body_id),
      cons_id      TEXT NOT NULL REFERENCES consciousnesses(cons_id),
      from_event   INTEGER,
      to_event     INTEGER,
      occ_mode     TEXT CHECK(occ_mode IN ('native','jump_in','restored','installed','co_resident')),
      canon_src    TEXT
    );
    """)
    
    # 命题
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS propositions (
      prop_id      TEXT PRIMARY KEY,
      statement    TEXT NOT NULL,
      spoiler_tier INTEGER NOT NULL,
      canon_src    TEXT
    );
    """)
    
    # 知识时间表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_schedule (
      cons_id      TEXT REFERENCES consciousnesses(cons_id),
      prop_id      TEXT REFERENCES propositions(prop_id),
      learn_ch     INTEGER NOT NULL,
      source_desc  TEXT,
      PRIMARY KEY (cons_id, prop_id)
    );
    """)
    
    # 高光台词锁定库
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS canon_locks (
      lock_id      TEXT PRIMARY KEY,
      node_id      TEXT,
      ch_ref       INTEGER,
      locked_text  TEXT NOT NULL,
      context      TEXT,
      speaker_cons TEXT REFERENCES consciousnesses(cons_id)
    );
    """)
    
    # 慢环记忆（感官锚点）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS slow_memory (
      mem_id INTEGER PRIMARY KEY AUTOINCREMENT,
      run INTEGER, 
      cons_id TEXT REFERENCES consciousnesses(cons_id),
      text TEXT NOT NULL, 
      anchor TEXT,
      salience REAL, 
      emo_tag TEXT,
      src_event INTEGER, 
      available_ch INTEGER,
      projection_text TEXT,
      reveal_ch INTEGER,
      embedding BLOB
    );
    """)
    
    # 情感状态基线 (运行时/初始状态)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS affect_state (
      run INTEGER, 
      cons_id TEXT REFERENCES consciousnesses(cons_id), 
      target TEXT,
      trust INTEGER, 
      intimacy INTEGER, 
      alert INTEGER,
      fsm_state TEXT CHECK(fsm_state IN ('open','probing','guarded','detached')),
      PRIMARY KEY (run, cons_id, target)
    );
    """)
    
    # 身份信念
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS identity_beliefs (
      run INTEGER,
      observer_cons TEXT REFERENCES consciousnesses(cons_id),
      body_id       TEXT REFERENCES bodies(body_id),
      believed_cons TEXT REFERENCES consciousnesses(cons_id),
      doubt         REAL DEFAULT 0.0,
      asof_event    INTEGER,
      PRIMARY KEY (run, observer_cons, body_id)
    );
    """)

    # 跨周目扑救/羁绊记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS run_bonds (
      run INTEGER,
      character_id TEXT,
      action_flag TEXT,
      timestamp TEXT,
      PRIMARY KEY (run, character_id, action_flag)
    );
    """)

    conn.commit()
    ensure_indexes(conn)
    print("Tables created successfully.")

# 3. 填充正典常量与基线数据
def populate_initial_data(conn):
    cursor = conn.cursor()
    
    # 世界线
    worldlines = [
        ('W1', None, 0, '第一世界/原生世界'),
        ('W2', None, 0, '高科技世界，尘叔在此与龙也缔约'),
        ('W3', None, 0, '秋人世界，尘叔在此获得晴明机体，并开启物理顶替'),
        ('W-MAIN', None, 0, '主世界（正典世界线）'),
        ('W-MAIN/TJ-ENCLAVE', 'W-MAIN', 1000, '天津避难飞地（时钟偏移1000ms）')
    ]
    cursor.executemany("INSERT OR REPLACE INTO worldlines VALUES (?, ?, ?, ?)", worldlines)
    
    # 同位体
    archetypes = [
        ('zhangchen', '张尘'),
        ('xiuzai', '折原修哉'),
        ('ryuya', '折原龙也'),
        ('kakashi', '卡卡西/晴明'),
        ('weichu', '魏初'),
        ('guojiazheng', '郭家政'),
        ('nakajima', '中岛'),
        ('luojie', '罗洁'),
        ('liuyuntian', '刘云天'),
        ('wuxiaxian', '吴夏弦'),
        ('akito', '川口秋人'),
        ('banbo', '敖斑驳'),
        ('yuxuan', '雨璇'),
        # 原著只以家庭称谓指代；不可擅造姓名。
        ('pan_father', '潘父'),
        ('pan_mother', '潘母'),
        ('maki', '折原真纪'),
        ('sasuke', '佐助'),
        ('sakura', '小樱'),
        ('naruto', '鸣人'),
        ('yamato', '大和'),
        ('liuxu', '柳絮'),
        ('itachi', '宇智波鼬'),
        ('sai', '佐井'),
        ('yamamoto_che', '山本澈'),
        ('minamoto', '源晃'),
        ('leonard', '莱纳德'),
        ('fein', '费恩'),
        ('zhouze', '周泽')
    ]
    cursor.executemany("INSERT OR REPLACE INTO archetypes VALUES (?, ?)", archetypes)
    
    # 身体 (Bodies)
    bodies = [
        ('B.zhangchen.WMAIN', 'W-MAIN', 'zhangchen', 'human', None, '主世界原生张尘的身体（有鼻伤）'),
        ('B.dust', 'W3', 'zhangchen', 'human', None, '第一世界原生的张尘物理身体（物理跃迁，无鼻伤）'),
        ('B.seimei', 'W3', 'kakashi', 'machine_hybrid', 'RTW-131', '晴明君机体，人造人载体，搭载异世界修哉大脑'),
        ('B.ryuya.WMAIN', 'W-MAIN', 'ryuya', 'human', None, '主世界折原龙也的身体'),
        ('B.xiuzai.WMAIN', 'W-MAIN', 'xiuzai', 'human', None, '主世界折原修哉的身体'),
        ('B.kakashi.WMAIN', 'W-MAIN', 'kakashi', 'human', None, '银发卡卡西本体在主世界的物理身体'),
        ('B.weichu.WMAIN', 'W-MAIN', 'weichu', 'human', None, '魏初在主世界的物理身体'),
        ('B.liuyuntian.WMAIN', 'W-MAIN', 'liuyuntian', 'human', None, '刘云天在主世界的物理身体'),
        ('B.wuxiaxian.WMAIN', 'W-MAIN', 'wuxiaxian', 'human', None, '吴夏弦在主世界的物理身体'),
        ('B.akito.WMAIN', 'W-MAIN', 'akito', 'human', None, '川口秋人在主世界的物理身体'),
        ('B.akito.W3', 'W3', 'akito', 'human', None, 'W3世界线川口秋人的物理身体'),
        ('B.banbo.WMAIN', 'W-MAIN', 'banbo', 'human', None, '主世界敖斑驳的身体'),
        ('B.yuxuan.WMAIN', 'W-MAIN', 'yuxuan', 'human', None, '主世界雨璇的身体'),
        ('B.pan_father.WMAIN', 'W-MAIN', 'pan_father', 'human', None, '主世界潘父的身体（原著仅以家庭称谓出现）'),
        ('B.pan_mother.WMAIN', 'W-MAIN', 'pan_mother', 'human', None, '主世界潘母的身体（原著仅以家庭称谓出现）'),
        ('B.maki.WMAIN', 'W-MAIN', 'maki', 'human', None, '主世界折原真纪的身体'),
        ('B.sasuke.WMAIN', 'W-MAIN', 'sasuke', 'human', None, '主世界佐助的身体'),
        ('B.sakura.WMAIN', 'W-MAIN', 'sakura', 'human', None, '主世界小樱的身体'),
        ('B.naruto.WMAIN', 'W-MAIN', 'naruto', 'human', None, '主世界鸣人的身体'),
        ('B.yamato.WMAIN', 'W-MAIN', 'yamato', 'human', None, '主世界大和的身体'),
        ('B.liuxu.WMAIN', 'W-MAIN', 'liuxu', 'human', None, '主世界柳絮的身体'),
        ('B.itachi.WMAIN', 'W-MAIN', 'itachi', 'human', None, '主世界宇智波鼬的身体（主世界化名为折原达也）'),
        ('B.sai.WMAIN', 'W-MAIN', 'sai', 'human', None, '主世界佐井的身体'),
        ('B.yamamoto_che.WMAIN', 'W-MAIN', 'yamamoto_che', 'human', None, '主世界山本澈的身体'),
        ('B.minamoto.WMAIN', 'W-MAIN', 'minamoto', 'human', None, '主世界源晃的身体'),
        ('B.leonard.WMAIN', 'W-MAIN', 'leonard', 'human', None, '主世界莱纳德的身体'),
        ('B.fein.WMAIN', 'W-MAIN', 'fein', 'human', None, '主世界费恩的身体'),
        ('B.zhouze.WMAIN', 'W-MAIN', 'zhouze', 'human', None, '主世界周泽的身体')
    ]
    cursor.executemany("INSERT OR REPLACE INTO bodies VALUES (?, ?, ?, ?, ?, ?)", bodies)
    
    # 意识 (Consciousnesses)
    consciousnesses = [
        ('C.zhangchen.WMAIN', 'W-MAIN', 'zhangchen', 0, '主世界原生张尘的意识（本体）'),
        ('C.dust.W1', 'W1', 'zhangchen', 1, '第一世界原生的张尘意识（尘叔）'),
        ('C.xiuzai.WMAIN', 'W-MAIN', 'xiuzai', 0, '主世界折原修哉的意识'),
        ('C.xiuzai.W3', 'W3', 'xiuzai', 1, '第一世界/W3已故修哉的大脑意识（载于晴明机体）'),
        ('C.ryuya.WMAIN', 'W-MAIN', 'ryuya', 0, '主世界原生折原龙也意识'),
        ('C.ryuya.W1', 'W1', 'ryuya', 1, '第一世界折原龙也意识'),
        ('C.weichu.WMAIN', 'W-MAIN', 'weichu', 0, '主世界魏初的意识（天津置换后经历了单线跨世界意识重组与短暂混乱）'),
        ('C.weichu.W1', 'W1', 'weichu', 1, '第一世界魏初意识（流浪归来，还钢笔）'),
        ('C.guojiazheng.WMAIN', 'W-MAIN', 'guojiazheng', 0, '主世界郭家政的意识'),
        ('C.nakajima.WMAIN', 'W-MAIN', 'nakajima', 0, '主世界中岛的意识'),
        ('C.luojie.WMAIN', 'W-MAIN', 'luojie', 0, '主世界罗洁的意识'),
        ('C.kakashi.WMAIN', 'W-MAIN', 'kakashi', 0, '银发卡卡西在主世界的原生意识'),
        ('C.liuyuntian.WMAIN', 'W-MAIN', 'liuyuntian', 0, '主世界刘云天的意识（天津置换后经历了单线跨世界意识重组与短暂混乱）'),
        ('C.wuxiaxian.WMAIN', 'W-MAIN', 'wuxiaxian', 0, '主世界吴夏弦的意识'),
        ('C.akito.WMAIN', 'W-MAIN', 'akito', 0, '主世界川口秋人的意识（终局在世界政府/LT中被强行注入多世界记忆芯片，非意识跃迁，但借此获得全知性的多维世界线记忆）'),
        ('C.akito.W3', 'W3', 'akito', 1, '第一世界/W3已故川口秋人的意识'),
        ('C.banbo.WMAIN', 'W-MAIN', 'banbo', 0, '主世界敖斑驳的意识'),
        ('C.yuxuan.WMAIN', 'W-MAIN', 'yuxuan', 0, '主世界雨璇的意识'),
        ('C.pan_father.WMAIN', 'W-MAIN', 'pan_father', 0, '主世界潘父的意识（原著仅以家庭称谓出现）'),
        ('C.pan_mother.WMAIN', 'W-MAIN', 'pan_mother', 0, '主世界潘母的意识（原著仅以家庭称谓出现）'),
        ('C.maki.WMAIN', 'W-MAIN', 'maki', 0, '主世界折原真纪的意识'),
        ('C.sasuke.WMAIN', 'W-MAIN', 'sasuke', 0, '主世界佐助的意识'),
        ('C.sakura.WMAIN', 'W-MAIN', 'sakura', 0, '主世界小樱的意识'),
        ('C.naruto.WMAIN', 'W-MAIN', 'naruto', 0, '主世界鸣人的意识'),
        ('C.yamato.WMAIN', 'W-MAIN', 'yamato', 0, '主世界大和的意识'),
        ('C.liuxu.WMAIN', 'W-MAIN', 'liuxu', 0, '主世界柳絮的意识'),
        ('C.itachi.WMAIN', 'W-MAIN', 'itachi', 0, '宇智波鼬的意识（主世界化名为折原达也）'),
        ('C.sai.WMAIN', 'W-MAIN', 'sai', 0, '主世界佐井的意识'),
        ('C.yamamoto_che.WMAIN', 'W-MAIN', 'yamamoto_che', 0, '主世界山本澈的意识'),
        ('C.minamoto.WMAIN', 'W-MAIN', 'minamoto', 0, '主世界源晃的意识'),
        ('C.leonard.WMAIN', 'W-MAIN', 'leonard', 0, '主世界莱纳德的意识'),
        ('C.fein.WMAIN', 'W-MAIN', 'fein', 0, '主世界费恩的意识'),
        ('C.zhouze.WMAIN', 'W-MAIN', 'zhouze', 0, '主世界周泽的意识')
    ]
    cursor.executemany("INSERT OR REPLACE INTO consciousnesses VALUES (?, ?, ?, ?, ?)", consciousnesses)
    
    # 意识占用身体表 (occupancy)
    # 跃迁者尘叔是肉体跃迁，物理上他使用自己的身体 B.dust，没有占用 B.zhangchen.WMAIN。
    # 晴明机体 B.seimei 被第一世界修哉大脑意识 C.xiuzai.W3 占用。
    # 龙也身体被两个意识共驻（人格分裂表现）。
    occupancies = [
        ('B.zhangchen.WMAIN', 'C.zhangchen.WMAIN', None, None, 'native', 'Ch.1-130'),
        ('B.dust', 'C.dust.W1', None, None, 'native', 'Ch.107-113'),
        ('B.seimei', 'C.xiuzai.W3', None, None, 'installed', 'Ch.98+'),
        ('B.ryuya.WMAIN', 'C.ryuya.WMAIN', None, None, 'native', 'Ch.1-60'),
        ('B.ryuya.WMAIN', 'C.ryuya.W1', None, None, 'co_resident', 'Ch.60'),
        ('B.xiuzai.WMAIN', 'C.xiuzai.WMAIN', None, None, 'native', 'Ch.1-130'),
        ('B.kakashi.WMAIN', 'C.kakashi.WMAIN', None, None, 'native', 'Ch.1-130'),
        ('B.weichu.WMAIN', 'C.weichu.WMAIN', None, None, 'native', 'Ch.7-130'),
        ('B.liuyuntian.WMAIN', 'C.liuyuntian.WMAIN', None, None, 'native', 'Ch.7-130'),
        ('B.wuxiaxian.WMAIN', 'C.wuxiaxian.WMAIN', None, None, 'native', 'Ch.8-130'),
        ('B.akito.WMAIN', 'C.akito.WMAIN', None, None, 'native', 'Ch.7-130'),
        ('B.akito.W3', 'C.akito.W3', None, None, 'native', 'W3毁灭前夕'),
        ('B.banbo.WMAIN', 'C.banbo.WMAIN', None, None, 'native', 'Ch.15-131'),
        ('B.yuxuan.WMAIN', 'C.yuxuan.WMAIN', None, None, 'native', 'Ch.15-131'),
        ('B.pan_father.WMAIN', 'C.pan_father.WMAIN', None, None, 'native', 'Ch.16-131'),
        ('B.pan_mother.WMAIN', 'C.pan_mother.WMAIN', None, None, 'native', 'Ch.16-131'),
        ('B.maki.WMAIN', 'C.maki.WMAIN', None, None, 'native', 'Ch.14-130'),
        ('B.sasuke.WMAIN', 'C.sasuke.WMAIN', None, None, 'native', 'Ch.116-130'),
        ('B.sakura.WMAIN', 'C.sakura.WMAIN', None, None, 'native', 'Ch.116-130'),
        ('B.naruto.WMAIN', 'C.naruto.WMAIN', None, None, 'native', 'Ch.116-130'),
        ('B.yamato.WMAIN', 'C.yamato.WMAIN', None, None, 'native', 'Ch.103-130'),
        ('B.liuxu.WMAIN', 'C.liuxu.WMAIN', None, None, 'native', 'Ch.8-130'),
        ('B.itachi.WMAIN', 'C.itachi.WMAIN', None, None, 'native', 'Ch.116-131'),
        ('B.sai.WMAIN', 'C.sai.WMAIN', None, None, 'native', 'Ch.108-130'),
        ('B.yamamoto_che.WMAIN', 'C.yamamoto_che.WMAIN', None, None, 'native', 'Ch.78-130'),
        ('B.minamoto.WMAIN', 'C.minamoto.WMAIN', None, None, 'native', 'Ch.78-130'),
        ('B.leonard.WMAIN', 'C.leonard.WMAIN', None, None, 'native', 'Ch.12-131'),
        ('B.fein.WMAIN', 'C.fein.WMAIN', None, None, 'native', 'Ch.12-130'),
        ('B.zhouze.WMAIN', 'C.zhouze.WMAIN', None, None, 'native', 'Ch.24-130')
    ]
    for body_id, cons_id, from_ev, to_ev, occ_mode, src in occupancies:
        cursor.execute("""
            INSERT OR REPLACE INTO occupancy (body_id, cons_id, from_event, to_event, occ_mode, canon_src)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (body_id, cons_id, from_ev, to_ev, occ_mode, src))
        
    # 肉体跃迁表 (body_transfers)
    # 尘叔和晴明君均从外部世界线转移到主世界 W-MAIN
    transfers = [
        ('B.dust', 'W3', 'W-MAIN', 'seimei_spacetime', None, 'Ch.107'),
        ('B.seimei', 'W3', 'W-MAIN', 'seimei_spacetime', None, 'Ch.98')
    ]
    for body_id, from_wl, to_wl, via, at_event, src in transfers:
        cursor.execute("""
            INSERT OR REPLACE INTO body_transfers (body_id, from_wl, to_wl, via, at_event, canon_src)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (body_id, from_wl, to_wl, via, at_event, src))
        
    # 命题主数据 (propositions)
    props = [
        ('P.RTW_EXISTS', '世界政府/RTW 组织确实存在并暗中控制秩序', 2, 'Ch.7/41'),
        ('P.GF_DEATH_TRUTH', '女友苏颖四年前在十六中正门坠楼死亡，真相为折原龙也亲手推下', 2, 'Ch.41/60'),
        ('P.RYUYA_DEATH_TRUTH', '折原龙也因与世界政府利益对抗而选择假死，并设计弑父（折原正义）以完成最终交换', 2, 'Ch.60'),
        ('P.SEIMEI_MACHINE', '晴明君（黑发坂本卡卡西）并非原生人类，而是人造机体，内部搭载异世界折原修哉的大脑', 3, 'Ch.98/113'),
        ('P.DUST_CREATOR', '世界政府/RTW 实际上是物理跃迁者尘叔（Dust）在更早世界线中创建的', 3, 'Ch.110'),
        ('P.FIRST_WORLD_PROMISE', '第一世界中尘叔与折原修哉在斯德哥尔摩大火中离别，并约定“一定会带你回来”', 3, 'Ch.111'),
        ('P.RTW131_IDENTITY', '银发卡卡西并非普通人类，而是初代人造人实验体 RTW131', 3, 'Ch.78/92'),
        ('P.WEICHU_WIDOW', '魏初是已故世界政府高层折原龙也的遗孀，并暗中卷入因果中枢', 2, 'Ch.19/96')
    ]
    cursor.executemany("INSERT OR REPLACE INTO propositions VALUES (?, ?, ?, ?)", props)
    
    # 知识时间表 (knowledge_schedule)
    k_schedule = [
        ('C.zhangchen.WMAIN', 'P.RTW_EXISTS', 7, '自小耳濡目染及早期工作获知'),
        ('C.zhangchen.WMAIN', 'P.GF_DEATH_TRUTH', 60, '折原龙也临终送行交底'),
        ('C.zhangchen.WMAIN', 'P.RYUYA_DEATH_TRUTH', 60, '折原龙也口述交换秘密'),
        ('C.zhangchen.WMAIN', 'P.SEIMEI_MACHINE', 98, '东京诊室中岛的诊断及观察'),
        # 尘叔是创始人和跃迁者，全知
        ('C.dust.W1', 'P.RTW_EXISTS', 1, '创始人生来知晓'),
        ('C.dust.W1', 'P.GF_DEATH_TRUTH', 1, '已在多宇宙知悉因果'),
        ('C.dust.W1', 'P.RYUYA_DEATH_TRUTH', 1, '第一世界共同谋划者'),
        ('C.dust.W1', 'P.SEIMEI_MACHINE', 1, '拥有晴明机体的最高指挥权'),
        ('C.dust.W1', 'P.DUST_CREATOR', 1, '自身历史'),
        ('C.dust.W1', 'P.FIRST_WORLD_PROMISE', 1, '自身最深刻执念'),
        # 折原修哉本体的知识
        ('C.xiuzai.WMAIN', 'P.RTW_EXISTS', 8, '利用顶级黑客技术突破信息管制发现'),
        ('C.xiuzai.WMAIN', 'P.GF_DEATH_TRUTH', 60, '龙也假死与面谈时交底'),
        ('C.xiuzai.WMAIN', 'P.RYUYA_DEATH_TRUTH', 60, '龙也面谈时揭秘'),
        ('C.xiuzai.WMAIN', 'P.SEIMEI_MACHINE', 98, '检测到晴明机体异常脑电波'),
        # 异世界修哉大脑 (晴明君)，全知
        ('C.xiuzai.W3', 'P.RTW_EXISTS', 1, '参与早期开发计划并有记录'),
        ('C.xiuzai.W3', 'P.GF_DEATH_TRUTH', 1, '异世界历史常识'),
        ('C.xiuzai.W3', 'P.RYUYA_DEATH_TRUTH', 1, '参与第一世界因果设定'),
        ('C.xiuzai.W3', 'P.SEIMEI_MACHINE', 1, '机体自知本身即是机体'),
        ('C.xiuzai.W3', 'P.DUST_CREATOR', 1, '与尘叔深度合作'),
        ('C.xiuzai.W3', 'P.FIRST_WORLD_PROMISE', 1, '斯德哥尔摩约定的一方'),
        # 折原龙也本体的知识
        ('C.ryuya.WMAIN', 'P.RTW_EXISTS', 8, '进入世界政府管理层后获知内部绝密'),
        ('C.ryuya.WMAIN', 'P.GF_DEATH_TRUTH', 41, '亲手推苏颖下楼作为因果交换'),
        ('C.ryuya.WMAIN', 'P.RYUYA_DEATH_TRUTH', 60, '自身假死与弑父计划实施者'),
        ('C.ryuya.WMAIN', 'P.SEIMEI_MACHINE', 98, '暗中掌握卡卡西人造机体改造程序'),
        # 第一世界龙也的知识 (全知)
        ('C.ryuya.W1', 'P.RTW_EXISTS', 1, '创始核心成员'),
        ('C.ryuya.W1', 'P.GF_DEATH_TRUTH', 1, '已掌握其他宇宙的因果规律'),
        ('C.ryuya.W1', 'P.RYUYA_DEATH_TRUTH', 1, '第一世界共同谋划者'),
        ('C.ryuya.W1', 'P.SEIMEI_MACHINE', 1, '协助修哉制造晴明君载体'),
        ('C.ryuya.W1', 'P.DUST_CREATOR', 1, '知悉尘叔创建世界政府始末'),
        ('C.ryuya.W1', 'P.FIRST_WORLD_PROMISE', 1, '第一世界拯救约定的见证者'),
        # 银发卡卡西的知识
        ('C.kakashi.WMAIN', 'P.RTW_EXISTS', 78, '听取总经理山本澈在雨中车内的全盘托出'),
        ('C.kakashi.WMAIN', 'P.RTW131_IDENTITY', 78, '山本澈在雨中车内告知其人造人真相'),
        ('C.kakashi.WMAIN', 'P.GF_DEATH_TRUTH', 61, '老罗家救援张尘交谈获知'),
        ('C.kakashi.WMAIN', 'P.RYUYA_DEATH_TRUTH', 61, '张尘清醒后口述中获知'),
        ('C.kakashi.WMAIN', 'P.SEIMEI_MACHINE', 98, '与修哉共同参与据点分析发现'),
        # 魏初的知识
        ('C.weichu.WMAIN', 'P.RTW_EXISTS', 19, '折原真纪口述证实折原家产业真相'),
        ('C.weichu.WMAIN', 'P.GF_DEATH_TRUTH', 46, '张尘在客厅情绪崩溃质问修哉时得知'),
        ('C.weichu.WMAIN', 'P.RYUYA_DEATH_TRUTH', 46, '张尘质问和修哉交底中怀疑龙也死因'),
        ('C.weichu.WMAIN', 'P.WEICHU_WIDOW', 7, '自身身份'),
        # 主世界秋人的知识 (终局 LT 芯片注入)
        ('C.akito.WMAIN', 'P.RTW_EXISTS', 130, '被带入世界政府 LT 核心，强行注入记忆芯片后获得'),
        ('C.akito.WMAIN', 'P.GF_DEATH_TRUTH', 130, '被带入世界政府 LT 核心，强行注入记忆芯片后获得'),
        ('C.akito.WMAIN', 'P.RYUYA_DEATH_TRUTH', 130, '被带入世界政府 LT 核心，强行注入记忆芯片后获得'),
        ('C.akito.WMAIN', 'P.SEIMEI_MACHINE', 130, '被带入世界政府 LT 核心，强行注入记忆芯片后获得'),
        ('C.akito.WMAIN', 'P.DUST_CREATOR', 130, '被带入世界政府 LT 核心，强行注入记忆芯片后获得'),
        ('C.akito.WMAIN', 'P.FIRST_WORLD_PROMISE', 130, '被带入世界政府 LT 核心，强行注入记忆芯片后获得'),
        # W3秋人的知识
        ('C.akito.W3', 'P.RTW_EXISTS', 1, '作为 W3 记录者自知'),
        ('C.akito.W3', 'P.SEIMEI_MACHINE', 1, '协助修哉脑波实验并记录其载体本质'),
    ]
    cursor.executemany("INSERT OR REPLACE INTO knowledge_schedule VALUES (?, ?, ?, ?)", k_schedule)
    
    # 慢环记忆（感官锚点）慢环记忆绑定意识！
    slow_memories = [
        # 张尘的正典慢环在 events 转录后由 migrate_slow_memory_provenance.py 写入，
        # 以便“原文/事件来源章”和“本人何时已拥有记忆”分字段保存。
        (0, 'C.dust.W1', '第一世界瑞典斯德哥尔摩教堂大火的噼啪爆裂声，与被强行推入舱门时的绝望哭喊。', '斯德哥尔摩大火/爆裂', 0.98, 'separation_despair'),
        (0, 'C.dust.W1', '多次跃迁时意识扭曲如针刺般的虚无空旷感，仿佛跨越无数冰冷的玻璃幕墙。', '跃迁扭曲/虚无', 0.80, 'fatigue'),
        (0, 'C.xiuzai.WMAIN', '四年前灭门惨案发生时哥哥龙也身上流出的温热血腥味，与父亲折原正义死在眼前的精神崩溃。', '灭门惨剧/血腥味', 0.98, 'trauma_grief'),
        (0, 'C.xiuzai.WMAIN', '战区装甲车倾覆翻滚时，四周刺眼而炙热的火焰爆轰与滚烫热浪。', '车辆爆炸/高温', 0.90, 'fear_death'),
        (0, 'C.xiuzai.WMAIN', '在冰冷的生化容器中脑电波苏醒时，四周浓烈的防腐液气味与连接在大脑皮层上的电极刺微痛。', '脑共鸣实验/电极微痛', 0.95, 'rebirth_confinement'),
        (0, 'C.xiuzai.W3', '第一世界瑞典斯德哥尔摩大火与尘叔告别时他掌心的温热，以及被关进意识舱时隔着毛玻璃看见的冲天火光。', '大火别离/温热掌心', 0.96, 'separation_regret'),
        (0, 'C.xiuzai.W3', '人造人机体内部齿轮精细咬合与电流信号传导时酥麻的机械冰冷感。', '机体运作/机械冷感', 0.85, 'mechanical_desync'),
        # 折原龙也本体的慢环记忆
        (0, 'C.ryuya.WMAIN', '四年前推下苏颖时，十六中正门刺骨的冷雨打在手掌上的冰凉，以及身后车辆尖锐的刹车声。', '苏颖坠楼/风雨冷意', 0.95, 'guilt_fear'),
        (0, 'C.ryuya.WMAIN', '亲手枪杀父亲折原正义时，枪托顶在肩膀上的猛烈后座力，与消音器沉闷如叹息般的枪声。', '手刃生父/后座力', 0.98, 'trauma_grief'),
        (0, 'C.ryuya.WMAIN', '总部大楼坍塌前，自己亲手用扳手砸毁脑波记录仪时，空中落下的微小石灰粉尘呛入喉咙的苦涩。', '毁坏仪器/苦粉尘', 0.90, 'determination'),
        # 第一世界龙也的慢环记忆
        (0, 'C.ryuya.W1', '第一世界大火实验室中，强行关闭传送舱透明舱门时掌心贴在坚硬玻璃上的炽热阻力。', '火中关舱门/热玻璃', 0.96, 'anxiety_separation'),
        (0, 'C.ryuya.W1', '两年前在主世界临终前，将量子信物（古铜色金属挂坠）交托给唯一的高维观测者（玩家）时指尖传来的坚硬冷感。', '临终托付/金属冷感', 0.98, 'hope_relief'),
        # 银发卡卡西的慢环记忆
        (0, 'C.kakashi.WMAIN', '肖羽警车里残留的刺鼻汽油与焦糊塑料味，夹杂着暴雨中闪击的雷光。', '肖羽警车/焦糊味', 0.90, 'fear_tension'),
        (0, 'C.kakashi.WMAIN', '千代田大楼顶层雷切电弧爆裂在手掌上的酥麻感，与写轮眼过载时的针刺样剧痛。', '雷切电弧/电击痛', 0.95, 'physical_pain'),
        (0, 'C.kakashi.WMAIN', '新宿街头第一次吃冷便当时，米饭冰凉酸涩且难以下咽的生硬口感。', '冷便当/酸涩冷感', 0.85, 'loneliness'),
        # 魏初的慢环记忆
        (0, 'C.weichu.WMAIN', '四年前抢救室红灯熄灭、绿灯亮起瞬间，四周惨白灯光投在空旷走廊上的无声死寂。', '手术室灯光/死寂', 0.96, 'trauma_grief'),
        (0, 'C.weichu.WMAIN', '深夜在卧室抚摸折原龙也照片时，指尖触碰相框玻璃传来的刺骨凉意。', '龙也相框/玻璃凉意', 0.92, 'loneliness_regret'),
        (0, 'C.weichu.WMAIN', '天津置换后避难所内刺鼻的消毒水味，与德国特工推开门时自己手握托盘的颤抖手感。', '避难所特工/手部颤抖', 0.88, 'fear_tension'),
        (0, 'C.weichu.WMAIN', '天津置换大雾袭来时，突然感觉脚下地砖倾角发生微小改变，导致短暂失去平衡并产生强烈世界线剥离感的生理眩晕。', '天津置换/重力感错位', 0.89, 'confusion_desync'),
        # 刘云天的慢环记忆
        (0, 'C.liuyuntian.WMAIN', '天津大雾消散后，握着方向盘时突然产生的、无法分清手动挡还是自动档的短暂意识认知错位与眩晕感。', '方向盘/手动挡错位', 0.90, 'confusion_desync'),
        (0, 'C.liuyuntian.WMAIN', '天津大雾爆发时，车窗外扭曲的灰白雾气中若隐若现的陌生高楼轮廓，与耳边不断回响的低频物理嗡鸣声。', '天津大雾/扭曲轮廓', 0.85, 'fear_tension'),
        # 川口秋人主世界的残余慢速记忆
        (0, 'C.akito.WMAIN', '手绘板上无意识画出的倾覆军舰与渤海湾核爆轮廓，惊醒后发现画纸已被手汗湿透的本能恐惧。', '渤海湾核爆/梦境残影', 0.85, 'fear_desync'),
        (0, 'C.akito.WMAIN', '洗印照片时在暗室红光下，胶片上偶尔浮现出的、从未拍过的斯德哥尔摩教堂大火残影。', '大火残影/胶片渗漏', 0.80, '既视感'),
        # W3世界线秋人的慢速记忆
        (0, 'C.akito.W3', 'W3世界线千代田控制室废墟中空气的焦糊碳粉味，与单反相机机身被高压电弧融化时的刺鼻橡胶气味。', '控制室焦糊味/相机融化', 0.95, 'destruction'),
        (0, 'C.akito.W3', '与折原修哉在 W3 脑波共鸣实验室里，看着指示灯有规律地闪烁而自己无能为力的空洞感。', 'W3实验室闪烁/空洞', 0.88, 'powerless'),
        # 新增角色的慢速记忆（感官锚点）
        (0, 'C.itachi.WMAIN', '千代田总部大门前，拔出太刀切碎量产人造人时，刀刃摩擦人造骨骼发出的高频摩擦声，伴随着飘飞的血雾。', '刀刃摩擦骨骼/血雾', 0.95, 'tension_combat'),
        (0, 'C.itachi.WMAIN', '战后在狭窄的出租屋里用梳子尝试给阿琛梳头发，却怎么也扎不顺的局促与手足无措感。', '给阿琛扎发/局促', 0.88, 'warmth_daily'),
        (0, 'C.itachi.WMAIN', '月光下和晴明在阳台上喝冰啤酒，指尖触碰易拉罐冷凝水滴时的冰凉感，伴随着夏夜的微风。', '冰啤酒/夏夜微风', 0.90, 'apathy_calm'),
        (0, 'C.sai.WMAIN', '千代田大楼死角里，看着大和天藏头也不回地走出去，空气中干燥而刺鼻的硝烟味，和手心握紧空画笔时的粗糙感。', '大和出走/握空笔', 0.94, 'powerless_regret'),
        (0, 'C.yamamoto_che.WMAIN', '雨天的新宿街头，坐在雷克萨斯密闭车厢里，看着雨刮器一下下刮走卡卡西的银发轮廓，混合着皮革座椅和香烟的古板气味。', '雷克萨斯/皮革与香烟', 0.92, 'determination'),
        (0, 'C.minamoto.WMAIN', '源晃大厦落地窗前，俯瞰东京雨幕时手中高脚杯边缘残留的温热红酒微涩，伴随着内网服务器断开时的低频警报声。', '红酒余温/内网断开', 0.85, 'calm'),
        (0, 'C.leonard.WMAIN', '纽约实验室里，屏幕上疯狂闪烁的绿色 LT 代码，键盘上被手汗浸湿的黏腻触感，伴随着风扇嘈杂的蜂鸣声。', 'LT绿代码/黏腻键盘', 0.88, 'obsession'),
        (0, 'C.fein.WMAIN', '千代田狭窄清洁室内，后背贴在合金门板上挡住弹雨时骨骼碎裂的闷响与灼烧感，伴随着眼前张尘眼泪的温热。', '背贴门板/骨裂与弹雨', 0.98, 'separation_sacrifice'),
        (0, 'C.zhouze.WMAIN', '新宿据点内，因黑客入侵被世界政府定位时，主机电源烧毁发出的焦炭臭味，伴随着心跳过速的耳鸣声。', '主机烧毁/焦炭味', 0.90, 'fear_tension')
    ]
    for run, cons_id, text, anchor, salience, tag in slow_memories:
        cursor.execute("""
            INSERT INTO slow_memory (run, cons_id, text, anchor, salience, emo_tag)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run, cons_id, text, anchor, salience, tag))

    # 初始信念表 (identity_beliefs)
    # 对应 Ch.107 诊疗室，中岛和老郭实际交互的是 B.dust，但他们认为他是本体 C.zhangchen.WMAIN，doubt 达 0.7
    beliefs = [
        (0, 'C.nakajima.WMAIN', 'B.dust', 'C.zhangchen.WMAIN', 0.7, None),
        (0, 'C.guojiazheng.WMAIN', 'B.dust', 'C.zhangchen.WMAIN', 0.7, None)
    ]
    cursor.executemany("INSERT OR REPLACE INTO identity_beliefs VALUES (?, ?, ?, ?, ?, ?)", beliefs)
    
    conn.commit()
    print("Initial metadata populated successfully.")

# 4. 读入并解析台词文本文件
def parse_and_import_quotes(conn):
    cursor = conn.cursor()
    
    files_to_parse = [
        ("wmain_quotes.txt", "C.zhangchen.WMAIN", "L.zhangchen.wmain"),
        ("dust_quotes.txt", "C.dust.W1", "L.dust"),
        ("xiuzai_wmain_quotes.txt", "C.xiuzai.WMAIN", "L.xiuzai.wmain"),
        ("xiuzai_w3_quotes.txt", "C.xiuzai.W3", "L.seimei"),
        ("ryuya_wmain_quotes.txt", "C.ryuya.WMAIN", "L.ryuya.wmain"),
        ("ryuya_w1_quotes.txt", "C.ryuya.W1", "L.ryuya.w1"),
        ("kakashi_quotes.txt", "C.kakashi.WMAIN", "L.kakashi"),
        ("weichu_quotes.txt", "C.weichu.WMAIN", "L.weichu"),
        ("weichu_w1_quotes.txt", "C.weichu.W1", "L.weichu.w1"),
        ("liuyuntian_quotes.txt", "C.liuyuntian.WMAIN", "L.liuyuntian"),
        ("wuxiaxian_quotes.txt", "C.wuxiaxian.WMAIN", "L.wuxiaxian"),
        ("akito_quotes.txt", "C.akito.WMAIN", "L.akito"),
        ("akito_w3_quotes.txt", "C.akito.W3", "L.akito.w3"),
        ("liuxu_quotes.txt", "C.liuxu.WMAIN", "L.liuxu"),
        ("yuxuan_quotes.txt", "C.yuxuan.WMAIN", "L.yuxuan.wmain"),
        ("banbo_quotes.txt", "C.banbo.WMAIN", "L.banbo.wmain"),
        ("maki_quotes.txt", "C.maki.WMAIN", "L.maki.wmain"),
        ("pan_father_quotes.txt", "C.pan_father.WMAIN", "L.pan_father.wmain"),
        ("pan_mother_quotes.txt", "C.pan_mother.WMAIN", "L.pan_mother.wmain"),
        # 新增角色的高光台词文件解析
        ("itachi_quotes.txt", "C.itachi.WMAIN", "L.itachi"),
        ("sai_quotes.txt", "C.sai.WMAIN", "L.sai"),
        ("yamamoto_che_quotes.txt", "C.yamamoto_che.WMAIN", "L.yamamoto_che"),
        ("leonard_quotes.txt", "C.leonard.WMAIN", "L.leonard"),
        ("fein_quotes.txt", "C.fein.WMAIN", "L.fein")
    ]
    
    lock_count = 0
    QUOTES_DIR = "corpus"
    for filename, speaker_cons, id_prefix in files_to_parse:
        filename = os.path.join(QUOTES_DIR, filename)
        if not os.path.exists(filename):
            print(f"Warning: {filename} not found.")
            continue

        print(f"Parsing and importing {filename}...")

        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 寻找格式如：
        # [Ch 9] 台词内容
        # Context: 上下文内容
        # --------------------------------------------------
        # 的匹配
        pattern = re.compile(
            r'\[Ch\s+(\d+)\]\s+(.*?)\nContext:\s+(.*?)\n-{10,}', 
            re.DOTALL
        )
        
        matches = pattern.findall(content)
        idx = 1
        for ch_str, quote_str, context_str in matches:
            ch_ref = int(ch_str)
            quote = quote_str.strip()
            context = context_str.strip()
            
            lock_id = f"{id_prefix}.{idx:04d}"
            
            cursor.execute("""
                INSERT OR REPLACE INTO canon_locks (lock_id, node_id, ch_ref, locked_text, context, speaker_cons)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (lock_id, None, ch_ref, quote, context, speaker_cons))
            
            idx += 1
            lock_count += 1
            
    conn.commit()
    print(f"Imported {lock_count} quotes into canon_locks.")

def main():
    if os.path.exists(DB_FILE):
        print(f"Database {DB_FILE} already exists. Recreating...")
        os.remove(DB_FILE)
        
    conn = get_db_connection()
    try:
        create_tables(conn)
        populate_initial_data(conn)
        parse_and_import_quotes(conn)
        print("Database import completed successfully.")
        
        # M-1: 自动连跑 apply_migration.py，合流 B5 与 A1 迁移数据并进行幂等校验
        print("\n[M-1 Pipeline] Running apply_migration.py...")
        _migration_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apply_migration.py")
        subprocess.run([sys.executable, _migration_script], check=True)

        # M-1b: 链入 A2 四支柱迁移（建 causal_constants/xline_messages/anchor_channel/coherence_matrix + 锁链种子）；幂等
        print("[M-1 Pipeline] Applying A2_mechanics_migration.sql...")
        _a2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "A2_mechanics_migration.sql")
        with open(_a2, encoding="utf-8") as _f:
            conn.executescript(_f.read())
        conn.commit()

        # M-4: 转录细剖事件表，补齐 events(run=0) 供 contracts 外键与卡片证据链使用
        print("\n[M-4 Pipeline] Running transcribe_events.py...")
        _events_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe_events.py")
        subprocess.run([sys.executable, _events_script], check=True)

        print("[M-4a C16] Applying sourced C16 truth/provenance corrections...")
        _c16_truth_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "migrate_c16_truth_provenance.py",
        )
        subprocess.run([sys.executable, _c16_truth_script, "--db", DB_FILE], check=True)

        print("[M-4b Pipeline] Migrating sourced slow-memory assets...")
        _slow_memory_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "migrate_slow_memory_provenance.py",
        )
        subprocess.run([sys.executable, _slow_memory_script, "--db", DB_FILE], check=True)

        print("\n[M-6 Pipeline] Running transcribe_knowledge.py...")
        _knowledge_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe_knowledge.py")
        subprocess.run([sys.executable, _knowledge_script], check=True)

        # 链入高保真角色知识时间线转录
        print("\n[Timeline Pipeline] Running transcribe_character_timelines.py...")
        _timeline_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe_character_timelines.py")
        subprocess.run([sys.executable, _timeline_script], check=True)

        print("[B2 Pipeline] Applying approved identity relations...")
        _identity_relations_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "migrate_identity_relations.py",
        )
        subprocess.run([sys.executable, _identity_relations_script, "--db", DB_FILE], check=True)

        print("\n[D1 Pipeline] Running d1_compiler.py...")
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "d1_compiler.py"),
             "--db", DB_FILE, "--contracts", "contracts"],
            check=True,
        )
    except Exception as e:
        print(f"Error occurred: {e}")
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    main()
