# STATUS —— 当前真相（新的在最上）

### 2026-08-08（导演同拍 ambient · 不拆第二脑 · idle 轻渗）

- **裁决**：环境/店员薄声 = 导演**同拍**可选字段 `ambient`；**不**再拆 env LLM / 店员 Agent。控场仍是一脑。
- **实现**：`normalize_director_ambient` → narrate；orchestrator 透传；观测台 ③ 显示；look-around 只留确定性兜底。
- **idle**：want/concern 轻渗初遇泼袖 + 开档身份，禁简历复述、禁编共史。
- **文档**：社交备忘 P8.1；GA 介绍 §5；龙也缺口计划 G4。
- **验**：`test_ryuya_voice_cog_loop` 增补；`--quick` 应绿。
- **报账**：机制层；未编新正典。
- **你**：硬刷新观测台，新开咖啡场：点贵的/环顾应能出薄 ambient；开场闲聊应能带初识，不急托付。

### 2026-08-08（咖啡闪回顶配硬闸 · 对齐旧设计）

- **Decide/Reflect**：已做（序幕样板）。Decide=拍前顶格 concern；Reflect=拍后私想写回观测台。不是全量 GA。
- **「可后置」纠偏**：公司线/WMAIN BOUNDARY **不是**这场；龙也现玩场=咖啡馆。闲聊封顶 / 禁编共史 / 收据默认 / 导演不灌 MH **本场要做**——已做。
- **硬闸**：`repair_ryuya_prologue_invent`；`hard_check` 拦 mystic+早清单+FUTURE；闪回无收据→`deferred`（沉默≠答应）；`build_director_instruction` 序幕不列 RP id；`soft_beat_budget` 到顶硬推 deepen。
- **对接**：导演=环境/MH 收据；角色 agent=独立 packet+Decide；事实=`solidified`/`run_observation_ledger`/当面收据。
- **你**：人验抽咖啡场（G4）；其余 R4 卫生 / G5·G6 不挡本场。

### 2026-08-08（龙也声纹入库 × ActorCogLoop × 观测台 · 咖啡场可演）

- **声纹**：`migrate_ryuya_voice_2026-08-08.py --apply` → `P.VOICE` W1×4 + WMAIN×4；§5.1 闲聊仿写未迁；MANNER.voice_rule 保留。
- **Agent 环**：`runtime/actor_cog_loop.py` — 序幕 Decide（顶格 concern + pending）→ Enact（LLM）→ Reflect 写回；指令注入 voice_samples / cog_loop.decide。
- **观测台**：`observer.html` 流水线扩为 10 步（VOICE / Decide / Reflect）；`debug_payload.private_reflections`。
- **验**：`ryuya_voice_cog_loop` + `--quick` 🟢；registry / persona_parity / truth_completeness 已跟数字。
- **报账**：VOICE 句带原著行号；Decide/Reflect 为机制层，不编新剧情。
- **你**：硬刷新观测台，新开两年前咖啡场看右侧 Decide/VOICE/Reflect。

### 2026-08-08（龙也相对齐全 × Agent 环缺口入计划）

- **判断**：龙也 Seed 相对最齐；缺口计划已立（随后本刀部分销账）。

### 2026-08-07（张尘刀1 Seed 入库 · 召回防灌 · API 探针）

- **已做**：`migrate_zhangchen_seed_knife1_2026-08-07.py --apply` → 薄核 7 + ACT 2 + REL 8×2；`interaction_dynamics` 魏初/周泽/Leonard；旧深 K0 `spoiler_tier` 降级；修 `C.zhangchen.WMAIN.md`（删「哥哥龙也」串戏）。
- **工程**：`fetch_relevant_knowledge` 闲聊相关度=0 时只留 ≤2 条 tier0，禁止灌满深史。
- **未做**：K.* 全表重写、44 条 A 情景记忆（刀3）；张尘入职场仍常被魏初抢话（竞价另案）。
- **验**：`test_zhangchen_seed_knife1`；入职 API 复探针 Top-K 不再灌深 K0。
- **报账**：未编；刀1 为可审稿压缩映射。

### 2026-08-05（开场记忆详扩 · 人格核×情景A/B×关系 三层齐 · 等人裁）

- **产出**：张尘 **第四次重写**（按五重身份：职员/达斯特/DS首领/尘叔知情/跃迁残留 + 48 条 A）；其余 9 人详扩见下表。
- **未动库**：全部 `--apply` 等人裁；未授权不迁。
- **你裁**：张尘 ZC-A09–A29 绝口 A 是否全迁；山本/吴/莱纳德详稿 vs 旧「极薄」口径；魏初龙也婚姻史进 A 还是 internal；T₀ `available_ch=0` vs `8`。
- **上位**：`筛查模板_统一格式_薄核×情景A·B×开场关系_2026-08-05.md` · `★★★人裁纠错_开场记忆批量筛查_2026-08-05.md`

### 2026-08-05（开场记忆批量纠错 · 修哉M33 · 张尘首版重写）

- **库侧**：修哉 XM-M33 曾删后按人裁回退插回（★时序待核）；migrate 脚本在仓。
- **首版**：张尘/各角薄稿 → 本次详扩 supersede。

### 2026-08-05（情景记忆时序分桶 · 多筛落位 · 等人裁）

- **产出**：`docs/plans/情景记忆时序分桶×多筛落位_2026-08-05.md`（已登 INDEX / 登记簿 A8b）。
- **口径草案**：主轴=故事内时间（非书写章）；A=开场前可迁 / B=开场后正典默认（多筛寄存，先不误开） / C=本 run 活记忆；细剖仍只给导演。
- **待你裁**：开场持有用 `available_ch=0` 还是 `8` 全仓统一；B 先稿后库还是同表闸死；是否审计已入库错挂。

### 2026-08-04（折原修哉开场前深过去及社交关系入库 · 架构共识确认）

- **已做**：执行迁移脚本 `--apply`，35条经历记忆落入 `slow_memory`（S4完成）；9人社交模式与标签落入 `affect_state`（有效状态受限，采用标准fsm）及 `propositions`（自定义标签）。
- **架构共识**：明确NPC局限性（只带过去记忆）与导演上帝视角（掌握全知剧情）。确认 `learn_ch` 门控对于防范NPC“未卜先知”底层真相（如龙也意识转移）的绝对必要性。
- **验证**：更新 `verify_truth_completeness.py` 以匹配新增的 13 条命题。跑通 `verify.py --quick` 🟢（27 PASS），完成 `world_truth.sql` 备份。
- **产出**：`docs/plans/★★★筛查_折原修哉_开场前深过去_2026-08-04.md` 已标记【已入库】。

### 2026-08-04（龙也情景记忆入库 · 双意识底库）

- **已做**：`migrate_ryuya_episodic_deep_past_2026-08-04.py --apply` → W1×13 + WMAIN×16（`available_ch=0`）；旧挂坠 mem#12 并入 `[W1-M13]`。
- **嵌合**：`fetch_slow_memory` 候选池默认 64（与激活 Top-K 分离）；`test_ryuya_episodic_deep_past` 入 `--quick`；`data/world_truth.sql` 已 dump。
- **报账**：W1-M12/M13=authored；其余原著蒸馏（anchor 带行号）；无新编情节。
- **召回**：cue∪cos+emo＝语义相似度；不必另加 LLM「要不要想」裁判。装死可说硬闸属 M2 余量。
- **你**：查库或重开序幕看候选；人格核保持薄，细节在记忆库。

### 2026-08-04（社交开放项收口 · 日语 side×MH 环境余波×ActorDecision.mode）

- **side 日语**：语言确认前 companion side 统一（日语）中文标；确认后剥标记（同 Kakashi surface 规则）。
- **must_happen**：stall≥2 只出 `must_happen_director_env_hint` 给导演；C16 不再用 MH 文案竞价/选角。
- **ActorDecision**：正式字段 `participation_mode`∈{speak,backchannel,side,pass}，校验入库。
- **验证**：`test_dual_lane_companion.py` 增补；`--quick` 🟢。

### 2026-08-04（双通道 companion lane · HOLD side · 等人验）

- **双通道**：floor（对玩家，单气泡+hold/barge-in）× companion（side/backchannel，本拍自动出，虚线「侧聊」气泡）。
- **选角**：`pick_side_actors`（修哉等 HOLD 拌嘴）+ backchannel（晴明短接）→ `companion_actors`；单 FTA 不对 companion 生效。
- **演员**：`call_actor_packet` 对 side/backchannel 限 1 句；turn 打 `stream_lane` / `participation_mode`。
- **验证**：`test_dual_lane_companion.py`；`--quick` 🟢。
- **你**：天安门蹭到后——秋人道歉的同时，修哉应能侧聊、晴明短接，且不跟玩家抢「借视频 checklist」。

### 2026-08-04（情景记忆装配与执行 · 策划等人裁）

- **产出**：`docs/plans/策划_情景记忆装配与执行_2026-08-04.md`（怎么安进包 + Loop M0–M6）。
- **安法摘要**：详库绑意识带情绪 → fetch 候选 → cos+emo Top-K → 披露/装死闸 → 进 ActorPacket；玩时不回跳原著；events 仍归导演。
- **你拍板**：文内 §6（安法 / speak_policy 列 / 执行序 / 是否改装配备忘 §4）。

### 2026-08-04（龙也开场前深过去 · 双意识筛查稿 · 不动库）

- **人裁已落**：①开枪后哭=第一次知另一意识；②装死→对玩家几乎不谈家（只淡「有弟弟」「已婚不知是谁」）；③记忆库不砍；W1 跃迁/尘叔挚友线必详。
- **召回口径**：情景记忆库 ≠ 细剖事实账本；玩时只搜库，**不**回跳原著（专项计划新增 §11 · Tulving/CoALA）。
- **产出**：筛查改2 + 专项计划 §11。未裁「拟入库正文」前不迁库。

### 2026-08-04（深过去记忆 × 信息不对齐 · 专项计划等人裁）

- **判断**：细剖 `events` = 导演脊柱/进展，**不是**角色随身回忆库；开场从零玩时，真正要装的是「更过去」+ 每人知情版本不对齐。
- **计划**：`docs/plans/深过去记忆×信息不对齐_专项计划_2026-08-04.md`（已登记 INDEX / 登记簿 A8）。
- **你拍板**：文内 §8 四问（分层口径 / 首批 Truth / P2 表是否新建 / lorebook 是否去双源）。未裁不迁库、不开挖正文。

### 2026-08-04（话轮流 B + 心想 delta · 全量接线 · 等人验）

- **话轮流**：`runtime/utterance_stream.py` — 单气泡出队；说/做 **hold** 队列、发送 **barge-in**；`advance_utterance` / `stream_hold` API；玩家舱「继续听」。
- **心想 δ**：`runtime/thought_delta.py` — 仅心想 early return，写入 `run_observation_ledger`（觉察/权重人物/立场）；NPC 听不见。
- **竞价**：`MAX_BID_SPEAKERS=1`（主话轮一条；backchannel 另通道）。
- **验证**：`test_utterance_stream.py` + `test_social_participation.py`；`--quick` 🟢。
- **你**：重玩天安门 — 秋人/修哉/晴明应逐句出；心想不卡 NPC；打字时队列暂停。

### 2026-08-04（社交参与宪法落地 · 意图队列 × backchannel · 等人验）

- **设计**：`design/00_架构/社交参与与自主决策备忘_…` 人裁为**全场**现行；`runtime/social_participation.py` 各角色社交习惯可用。
- **运行时**：天安门 open concerns 顶格进 `want_now`（不 checklist）；撤竞价 content boost；`backchannel_actors`（晴明等短接）；语言呈现 locks 更新；撤 primary「推进 want」脚本。
- **验证**：`test_social_participation.py` + 原 solidified 测；`--quick` 🟢。
- **你**：重玩天安门——蹭到后应先道歉；语言通后另拍才借视频；晴明应有短接；一句不应叠四件事。

### 2026-08-04（自然话轮 × 姓名闸 × 社交习惯 · 等人验）

- **姓名闸**：`hard_check` 对齐递进绑定（已自报可全名上台签）；短名不再因全名子串双重叉。
- **话轮**：天安门去掉两人硬帽（默认最多 3）；语言通且视频未结时自然抬升秋人竞价（拍砸→能聊→顺势想借视频，不谈「债务」）；修哉介绍拍仍可编排但不包办。
- **社交**：`OPENING_TRIO_SOCIAL_HABITS` × HOLD/主次位进包；次位提示改为真人接话（禁「批准旁听」脚本）。
- **观测台**：`inner_states` 缺字段不再用串场默认补 `unsaid`/`knot`（卡卡西毒默认已清）。
- **验证**：`test_solidified_facts_packet.py` 增补；`--quick` 🟢。
- **你**：重玩天安门语言通后一拍——秋人应能自然开口借视频；右侧内心流不应再出现「一进场就察觉你」。

### 2026-08-03（观测台整合 × 先想再说 × 物态提取 · 已重启）

- **观测台**：流水线置顶（装配展开 + 按人核/关系/记忆/先想/再说）；已固化对照保留；「角色」改为深检副本默认不展开。服务已重启（`c1_web_console/server.py`，自检 `observer.html` 200）。
- **先想再说**：`call_actor_packet` 要求 `pre_speech`；缺则合成回执并留痕；流水线第 7/8 步可见。
- **物态**：对话/舞台提取手机·单反进 `本场用过的物件`；挂坠不特提；BodyFrame 仍连续。
- **登记簿**：A1 改为「开场两场 session FSM 已接」。
- **你**：硬刷新观测台后新开一局看右侧；装配应是 ✅ 列表而非满屏 ⏸。

### 2026-08-03（开场体验七条落地 · 无硬闸涌现 · 等人验）

- **已做**：回滚 `suppress_repeat_roster` 硬闸；序幕删负向「不要补造」lock；固化事实（姓名自报 / run 观察 / 场次收据）写入各角色包 `场面已成立的事实`；`场上可见物态`（含手机递还结算）；`REL.HOLD`×主/次位软社交提示；次位改为批准旁听四选一（去掉还手机脚本）。
- **观测台**：右侧新增「角色包流水线」（导演世界→记忆→听见→义务→包摘要→说出）+「已固化×是否进包」对照。
- **验证**：`scripts/tests/test_solidified_facts_packet.py`；`--quick` 🟢。
- **你**：重玩天安门「介绍完还介绍 / 递手机只嗯」；右侧先看固化覆盖再看该角色包。

### 2026-08-03（前两场顶配三项补齐 · 等人验 · 医院因果暂定）

- **你**：正在验两场；验完告诉我。
- **医院因果**：脊柱暂定（视频→追杀→受伤入院）；与前两场无接驳。
- **前两场顶配**：隔离包 + FSM/Rel/KGE/cos+emo **且** 三项补齐——`fronting_canon` 运行时竞选（序幕→W1）、`generate_cards` authored_overlay、β `S(node)`→导演 `effective_threshold`（空沉淀 S≡0，run=1 不变）。观测台 `deferred_not_top_tier=[]`。`--quick` 🟢。
- **仍非本书长期线一次做完**：阶段4 S5 导演宪章入库、医院因果网落表、其它场 generate 全量人裁仍按登记簿。

### 2026-08-03（三层分工备忘 · 卡保留）

- 文：`design/00_架构/三层分工备忘_…`

### 2026-08-03（苏颖退出固定底 + β S6）

- `CC.SUYING_DEATH` 已删；`run_meta`/`delta_sediment`/settle 已落。
