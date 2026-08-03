-- A2_mechanics_migration.sql —— 高维机制四支柱建表 + CC.SELF_REF_CHAIN 锁链种子
-- 依据《高维机制四支柱设计书》v1.1。幂等可重放。供 D1 编译器做四个编译错误码校验。
BEGIN;

-- 支柱一：不可回滚常量（自指悖论锁）
CREATE TABLE IF NOT EXISTS causal_constants (
  const_id   TEXT PRIMARY KEY,
  prop_id    TEXT REFERENCES propositions(prop_id),
  lock_type  TEXT CHECK(lock_type IN ('self_reference','anchor_dependency')),
  dependency_chain TEXT NOT NULL,   -- JSON: 自指链事件/命题序列（终幕渲染）
  canon_src  TEXT
);

-- 支柱二：一秒之差（跨线延时专表）
CREATE TABLE IF NOT EXISTS xline_messages (
  msg_id INTEGER PRIMARY KEY, run INTEGER,
  from_wl TEXT, to_wl TEXT, channel TEXT,           -- LT_ANCHOR / PHONE / DATAPACK
  t_send INTEGER NOT NULL, t_observed INTEGER NOT NULL,  -- 引擎算，禁手填
  payload TEXT
);

-- 支柱三：锚点信道信噪比
CREATE TABLE IF NOT EXISTS anchor_channel (
  run INTEGER PRIMARY KEY,
  snr REAL DEFAULT 1.0,
  lt_filter REAL DEFAULT 0.0,
  diversity TEXT DEFAULT '[]'
);

-- 支柱四：双跳者相干矩阵
CREATE TABLE IF NOT EXISTS coherence_matrix (
  cons_id TEXT PRIMARY KEY,
  coupling REAL DEFAULT 0.0,
  note TEXT
);

-- ---------- 种子：CC.SELF_REF_CHAIN（2026-08-03 人裁：苏颖退出固定底）----------
-- 链：龙也罪疚/假死真相侧 → 挂坠交付 → 玩家受托 → 回滚成立。
-- CC.SUYING_DEATH 已退役：玩家线与苏颖无关；P.GF_DEATH_TRUTH 仍可作正典知识，不作固定底。
DELETE FROM causal_constants WHERE const_id IN ('CC.SUYING_DEATH','CC.RYUYA_DEATH','CC.PLAYER_ENTRUST');
INSERT OR REPLACE INTO causal_constants (const_id, prop_id, lock_type, dependency_chain, canon_src) VALUES
 ('CC.RYUYA_DEATH','P.RYUYA_DEATH_TRUTH','self_reference',
  '["E_RYUYA_GUILT","E_ANCHOR_DELIVER","E_PLAYER_ENTRUST","E_ROLLBACK_TRIGGER"]','Ch.60；2026-08-03去苏颖根'),
 ('CC.PLAYER_ENTRUST',NULL,'self_reference',
  '["E_RYUYA_GUILT","E_ANCHOR_DELIVER","E_PLAYER_ENTRUST","E_ROLLBACK_TRIGGER"]','玩家受托=回滚前件；2026-08-03去苏颖根');

-- 运行时锚点信道初始化（run=0 基线）
INSERT OR IGNORE INTO anchor_channel (run, snr, lt_filter, diversity) VALUES (0, 1.0, 0.0, '[]');

-- 双跳者耦合：尘叔最高（与 restart_immunity 同源）
INSERT OR REPLACE INTO coherence_matrix (cons_id, coupling, note) VALUES
 ('C.dust.W1', 0.8, '横向跳者·渗漏放大器'),
 ('C.zhangchen.WMAIN', 0.3, '本体张尘（被顶替前）');

COMMIT;
