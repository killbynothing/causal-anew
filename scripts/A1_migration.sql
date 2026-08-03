-- ============================================================
-- A1 迁移脚本 v1.0 ｜ world_truth.db → Schema v0.9.2 完全体 + B5 决议落库
-- 执行前提：对 world_truth.db 的副本执行；原库保留为备份
-- ============================================================
BEGIN;

-- ---------- 1. 摄入清单（章节顺序硬编码） ----------
CREATE TABLE IF NOT EXISTS source_manifest(
  seq INTEGER PRIMARY KEY, filename TEXT NOT NULL,
  ch_from INTEGER, ch_to INTEGER, note TEXT);
INSERT OR REPLACE INTO source_manifest VALUES
 (1,'novel_1-69.md',1,69,'东京日常篇(1-6)+第一部'),
 (2,'novel_chapters_70_87.txt',70,87,'注意.txt编码'),
 (3,'novel_88-107.md',88,107,'第二部至一秒之差'),
 (4,'novel_108-end.md',108,130,'含跃迁揭示与尾声');

-- ---------- 2. 正典前台账（B5 决议：龙也一身两意识的前台分配） ----------
CREATE TABLE IF NOT EXISTS fronting_canon(
  fc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  body_id TEXT, scene TEXT, ch_ref TEXT,
  fronting_cons TEXT, back_state TEXT, canon_src TEXT);
INSERT INTO fronting_canon(body_id,scene,ch_ref,fronting_cons,back_state,canon_src) VALUES
 ('B.ryuya.WMAIN','日常温柔面（对亲人、对玩家）','贯穿','C.ryuya.W1',
  '本体后台旁观——冷酷的本体也喜欢看温柔的这个爱他的亲人','B5决议·总裁定'),
 ('B.ryuya.WMAIN','冷酷面（组织行动）','贯穿','C.ryuya.WMAIN','W1意识后台','B5决议·总裁定'),
 ('B.ryuya.WMAIN','推落苏颖（十六中正门）','四年前','C.ryuya.WMAIN',NULL,'B5决议：肯定是本体'),
 ('B.ryuya.WMAIN','与玩家的全部交往（多年交情，临终叮嘱为最后一面）','至两年前','C.ryuya.W1',
  '带任务而来','B5决议+游戏正典：玩家身份A+C方案增强'),
 ('B.ryuya.WMAIN','赴死之夜：举枪掩护张尘','Ch.84闪回','C.ryuya.WMAIN',
  'W1意识惶恐误判——以为本体要杀张尘、以为这个世界又要完了；实则本体在保护','B5决议#1'),
 ('B.ryuya.WMAIN','临终：尘叔到场，与W1意识告别','赴死同夜','C.ryuya.W1',
  '本体保护完成后让位前台；同夜稍早已完成对玩家的叮嘱','B5决议#1+#附加·新增正典');

-- ---------- 3. occupancy 修正 ----------
UPDATE occupancy SET occ_mode='jump_in',
  canon_src='W3获其身(B5#5确认)→随晴明君肉体跃迁入W-MAIN→终局远征归乡W1'
  WHERE occ_id=2;
UPDATE occupancy SET canon_src='出生→赴死之夜(与W1意识同终,Ch.84闪回)' WHERE occ_id=4;
UPDATE occupancy SET canon_src='W1修哉送入→赴死之夜;与玩家多年交往均为此意识前台(B5)' WHERE occ_id=5;

-- ---------- 4. B5 衍生正典命题 ----------
INSERT OR REPLACE INTO propositions VALUES
 ('P.BLACKOUT_SECRET','Ch.85全城断电是本体张尘瞒着尘叔的擅自慈悲，尘叔的城市置换计划因此被破坏；本体下令时心虚',3,'B5决议#2'),
 ('P.DS_PUPPET','DS本质为尘叔所建；本体张尘为台前执行者，按尘叔安排行事、承压巨大且低估自己真实的号召力',3,'B5决议#2'),
 ('P.RYUYA_CORESIDENT','主世界龙也一身两意识共驻（本体+W1意识），对外呈现为人格分裂',3,'B5决议·总裁定'),
 ('P.PLAYER_RYUYA_HISTORY','龙也（W1意识前台）在影子岁月中受钥匙指引找到玩家，以日常接触切入，两年间建立君子之交；临终交付挂坠（钥匙）',2,'B5决议·附加·2026-07-28修订');

-- ---------- 5. 运行时区与游戏层表（引擎初始化） ----------
CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY, run INTEGER NOT NULL, wl_id TEXT,
  t_game INTEGER, ch_anchor INTEGER, location_id TEXT,
  etype TEXT, payload TEXT, parent_event INTEGER);
CREATE TABLE IF NOT EXISTS body_state(
  run INTEGER, body_id TEXT, asof_event INTEGER, wl_id TEXT,
  location_id TEXT, hp TEXT, holding TEXT, PRIMARY KEY(run,body_id));
CREATE TABLE IF NOT EXISTS items(item_id TEXT PRIMARY KEY, display_name TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS item_custody(
  run INTEGER, item_id TEXT, holder_body TEXT, from_event INTEGER, to_event INTEGER);
CREATE TABLE IF NOT EXISTS knowledge_runtime(
  run INTEGER, cons_id TEXT, prop_id TEXT, acquired_event INTEGER,
  confidence REAL DEFAULT 1.0, PRIMARY KEY(run,cons_id,prop_id));
CREATE TABLE IF NOT EXISTS fronting_state(
  run INTEGER, body_id TEXT, fronting_cons TEXT, asof_event INTEGER,
  PRIMARY KEY(run,body_id));
CREATE TABLE IF NOT EXISTS delta_ledger(
  delta_id INTEGER PRIMARY KEY, run INTEGER NOT NULL, node_id TEXT,
  description TEXT, converged INTEGER DEFAULT 0, emo_tag TEXT, src_event INTEGER);
CREATE TABLE IF NOT EXISTS bleed_config(
  cons_id TEXT PRIMARY KEY, base_bleed REAL DEFAULT 0,
  growth_per_delta REAL DEFAULT 0, restart_immunity REAL DEFAULT 0);
INSERT OR REPLACE INTO bleed_config VALUES
 ('C.zhangchen.WMAIN',0.35,0.02,0.0),
 ('C.dust.W1',0.50,0.03,0.8),   -- B5决议#6：尘叔部分免疫Restart
 ('C.xiuzai.WMAIN',0.20,0.02,0.0),
 ('C.kakashi.WMAIN',0.20,0.02,0.0),
 ('C.weichu.WMAIN',0.05,0.01,0.0),
 ('C.luojie.WMAIN',0.05,0.01,0.0);
CREATE TABLE IF NOT EXISTS node_contracts(node_id TEXT PRIMARY KEY, part INTEGER, contract TEXT);
CREATE TABLE IF NOT EXISTS snapshots(
  snap_id INTEGER PRIMARY KEY, run INTEGER, node_id TEXT, created_at INTEGER, blob BLOB);

-- ---------- 6. 正典物品 ----------
INSERT OR REPLACE INTO items VALUES
 ('I.PEN','钢笔/原子笔','LT核心大门钥匙系；魏初/刘云天物权链'),
 ('I.PENDANT_ANCHOR','挂坠（LT_ANCHOR天线）','玩家持有；龙也(W1前台)交付'),
 ('I.DATADISK','革命一号数据盘','Ch.72拷贝事件'),
 ('I.PHOTO_FRAME','魏初茶几上的空相框','Ch.7伏笔，关联P.WEICHU_WIDOW');

COMMIT;
