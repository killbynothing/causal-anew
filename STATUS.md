# STATUS —— 当前真相（新的在最上）

### 2026-09-29（P2c-3 完成：Scene Fact 单一生产写权）

- **SceneFactReducer**：新增 `runtime/scene_fact_state.py` 纯 reducer；`FreeStageSession._reduce_scene_facts()` 成为 FreeStage `branch_progress + scene_receipts` 唯一生产 writer。receipt 是 append-only 证据，branch 只是当前 active fact 的兼容索引；assert/retract/replace/observe/reset_all 均由同一入口归约。
- **主链旁路归零**：FreeStage 中 `self.branch_progress.append`、`self.scene_receipts.append` 业务写归零；ExitPolicy 的 prospective semantic exit 仍只在 `ExitDecision.authorized` 后经 SceneFactReducer 落事实，P1a 不变量没有被 P2c 重构绕过。
- **旧同名状态拆分**：legacy `SceneState.branch_progress` 实际是 scene-contract 的 `{node_id:[path_id]}` 路由进度，不是 WorldCommit 世界事实。已改名为 `contract_branch_progress`；旧 JSON 的 `branch_progress` 只做单向 load migration，新 snapshot 只写新键，`scene_contracts/scene_api` 同步改用新名。
- **审计卫生**：Authority scanner 现在把通用 `load()` 归为 load_migration，并把 `scripts/test_*.py` 识别为 test，避免把真实迁移/测试工具冒充生产 writer。不是白名单遮旁路，P2c3 required gate 已证明 `branch_progress/scene_receipts` production writer 都只剩 `_reduce_scene_facts`，unknown alias=0。
- **后继不变量**：P1a 的旧“函数中首次出现 fact writer 必须在 ExitDecision 后”升级为语义级断言：semantic exit 选择→ExitDecision 之间不得写 scene fact，prospective fact 只能位于 `if exit_decision.authorized` 分支。旧测试没有删除。
- **验**：最终 Actions [36578353544](https://github.com/killbynothing/causal-anew/actions/runs/36578353544) **success**；quick **52 PASS / 0 FAIL / 163 SKIP（215 validators）**，DB checksum 前后不变。前一轮 36578024494 中 Authority 单 writer 已先通过，红点仅为新增 migration fixture 与 P1a 旧位置断言，均按真实语义修正。
- **报账**：未改 player_state/world_cursor/body/observation 的剩余 P2c writer、P3 ActorMind、run=0、正典卡、Seed/VOICE、★★★ 挂坠裁决或真人 a14 DB；**正典/人物/剧情新增 = 0**。
- **下一动**：开 **P2c integration**。从本已绿 P2c3 链头出发，逐域吸收并重新验证实验分支 `loop/world-beat-p2c-2026-09-29` 中的剩余 WorldCommit owner 工作；该实验分支当前最终 CI 是红的，禁止直接 merge/抄“debt==0”结论。迁移顺序：world_transactions/causal receipts → body/observation → player_state → world_cursor，每域单独 required gate。

### 2026-09-29（P2c-2 完成：跨视角 Frame Beat 单一生产写权）

- **Frame BeatReducer**：在 `runtime/beat_state.py` 增加纯 `reduce_frame_beats()`，保持既有 `run + frame_id::beat_id` 稳定键、ordered/idempotent append 与 run 隔离。调用方不再把 session 可变 `completed_beats` 直接交给 `beat_ledger.mark_done()`。
- **唯一 writer**：新增 `FreeStageSession._reduce_frame_beats()`，成为 `completed_beats` 唯一生产 writer；reset 也走同一 facade。legacy `_load` 仍可只读旧存档。live Authority Map required gate 证明 production writer = `_reduce_frame_beats` 且 unknown alias = 0。
- **来源链**：新增持久 `frame_beat_receipts`。只有真正新增的跨视角 beat 才产生 `free_stage.frame_beat_transition.v1` receipt，并引用本拍 scene Beat receipt；reset / retry 不伪造完成证据。
- **语义保持**：`_mark_frame_beats_for_progress()` 现在只消费 `newly_completed`，不再拿重复 `new_progress` 重新推；跨视角 folding 仍按 `frame_id + beat_id`，`frame_beat=[]` 的纯视角项仍永不折叠。
- **闸**：新增 quick `frame_beat_authority_p2c2`，覆盖纯 reducer copy-safe/幂等/run 隔离、reset 无假 receipt、scene receipt→frame receipt、save→load、跨视角 fold 与静态无 alias writer。P2c-1 旧“frame debt 必须存在”反例升级为 P2c-2 后“债必须消失”的 successor invariant，没有删测试刷绿。
- **验**：首跑 Actions `36572958722` 中 P2c-2 新测试、Authority Map、characterization 全 PASS，唯一红点是 P2c-1 旧债断言到期；升级后 Actions [36573150434](https://github.com/killbynothing/causal-anew/actions/runs/36573150434) **success**，quick **51 PASS / 0 FAIL / 163 SKIP（214 validators）**，DB checksum 前后不变。
- **报账**：未改 branch/scene receipts、world cursor、BodyFrame 其它写路、P3 ActorMind、run=0、正典卡、Seed/VOICE、★★★ 挂坠裁决或真人 a14 DB；**正典/人物/剧情新增 = 0**。
- **下一动**：只做 **P2c-3：scene fact authority**。把 `branch_progress + scene_receipts` 收成“receipt 为证据、branch 为只读索引”的单一提交/投影路径；先清业务 append/alias，再处理 reset/load 兼容。P2c-3 不顺手吞 observation/body/world cursor，也不碰 P3。

### 2026-09-29（P2c-1 完成：场景 Beat 单一生产写权）

- **BeatReducer 主干**：新增 `runtime/beat_state.py` 纯 reducer；`FreeStageSession._reduce_beat_state()` 成为 `completed / completed_by_card` 唯一生产 writer。旧字段暂保留为存档/兼容投影，不再允许 step/skip/canon/闪回/转场各自直接 append/extend/赋值。
- **生产迁移**：正常证据进度、RP1、挂坠 RP4 兼容投影、C16 ZG3/ZG4、canon segment、WH1 起场、brief skip、闪回进入/返回、普通换场与各类 scene snapshot 全部改经 BeatReducer。brief skip 用 `replace_complete` 保持旧“精确等于全部 must_happen”语义；flashback restore 不伪造新完成证据。
- **收据**：新增持久 `beat_receipts`。只有真正新增 beat 的 `complete/replace_complete` 产 `free_stage.beat_transition.v1` receipt，记录 scene/turn/source/evidence_refs/completed_after；snapshot/enter/restore/reset 不冒充新事件。挂坠 RP4 兼容写引用已提交 WorldCommit receipt。
- **静态收口**：`free_stage_prototype.py` 中 `self.completed.append/extend` 已归零，`self.completed_by_card[...]` 已归零；直接 `self.completed =` 只剩 legacy `_load` 与唯一生产 facade。P0 characterization 从“多 writer 已知债”升级为“scene Beat 单 writer”，同时明确保留 `completed_beats` 的 reset writer + alias mark_done 债，留 P2c-2。
- **兼容**：load 仍按旧字段读历史存档并读取可选 `beat_receipts`；旧无 receipt 存档不补造历史玩家/Beat 证据。save→load 覆盖 receipt 与 projection。
- **验**：新增 quick `beat_authority_p2c1`；Actions `36552043052` **success**，quick **50 PASS / 0 FAIL / 163 SKIP（213 validators）**，Authority Map/characterization/P2b 联合矩阵均通过，DB checksum 前后不变。
- **报账**：未改 `completed_beats` 跨视角语义、branch/scene receipts/world cursor、P3 ActorMind、run=0、正典卡、Seed/VOICE、★★★ 挂坠裁决或真人 a14 DB；**正典/人物/剧情新增 = 0**。
- **下一动**：P2c-2 收 `completed_beats`：保留 frame_id+beat_id 的既有幂等/跨视角语义，但禁止 `frame_beat_ledger.mark_done(self.completed_beats,...)` 直接拿 session 可变引用；统一经 BeatReducer 子入口提交，再更新 Authority Map。

### 2026-09-29（P2b-2 完成：咖啡馆联合矩阵 × Reflect 事实降权）

- **联合矩阵**：新增 quick `cafe_joint_matrix_p2b2`，固定覆盖纯玩笑、高拍数、认真话题、stage-only 托付、words-only/action-only/完整 offer、模糊回应、收/拒/暂放、不理继续聊，并另走 accepted→继续聊天→明确离场连续链。测试调用真实 `FreeStageSession.step()` 与 isolated actor caller，只比结构，不把自然语言做黄金文本。
- **跨层同查**：每个截面同时检查真实 actor caller packet（含 concern/prior Reflect 且不带 constraint_card）、Beat/RP、PlayerAction、World transaction、BodyFrame、player body_props、pendant observation 的 WorldCommit receipt、真实 `ExitDecision` 与 save→load。高拍数不造 RP2；stage-only 不造 RP3；单有 words/action 不算完整 offer；offer 不转 custody；模糊“我答应照顾他们”不变成收坠。
- **自由交互**：accepted 后的 WorldCommit/custody 在 save→load 后保持，下一拍继续聊仍由 ExitPolicy 返回 continue；只有明确“先走了/回头见”才 end_run。RP4/物件结算不再暗含自动关局。
- **Reflect 收权**：`actor_cog_loop.build_reflect_thought()` 新增只读 `pendant_disposition` 输入，生产从 `ryuya_pendant_disposition` WorldCommit 传入。accepted/declined/deferred 各自按已提交结果反思；仅有 RP4 兼容标记而无世界收据时明确“不自行补成已交付”；RP3 后只允许“明确递出→等玩家回应”，删除“下一拍必须交到手里”的强推。
- **未裁边界**：矩阵不对 declined/deferred 是否完成 RP4 作断言，不把当前兼容实现升格为正典；挂坠“必须赠与尝试 vs 必须最终 custody”仍是 ★★★ 人裁。场卡“必交”文案未动。
- **验**：最终 Actions `36550294313` **success**；quick **49 PASS / 0 FAIL / 163 SKIP（212 validators）**，DB checksum 前后不变。首跑 `36550154664` 的唯一红点是测试用空字符串做“不包含 thought”判断，属于测试表达式错误；修正为仅对非空 thought 检查后全绿，没有放宽运行时合同。
- **报账**：未改 run=0、正典场卡、Seed/VOICE、A/B 挂坠固定事实、真人 a14 DB 或 LFS 真值库；**正典/人物/剧情新增 = 0**。本轮新增的是联合观测测试与 receipt-driven Reflect 工程语义。
- **下一动**：进入 **P2c**。按 Authority Map 一类类迁移 `completed/completed_by_card/branch/scene receipts/ledger/body/world cursor` 的生产 writer，使 BeatState 与 World projection 成为唯一提交/派生路径；不在 P2c 顺手做 P3 ActorMind。

### 2026-09-29（P2b-1 完成：挂坠处分来源链 × WorldCommit 同源投影）

- **投影权威**：新增 `runtime/world_projection.py`。挂坠 player props、龙也 BodyFrame、run observation ledger 不再由 `_finalize_prologue_pendant()` 三处手改，而是只读已经提交的 WorldCommit receipt 一次性派生；reducer 对输入 copy-safe、重复投影幂等。
- **stage 降权**：`settle_body_frames_from_npc_turns()` 中“递/塞/交挂坠”不再凭舞台动作清空 `I.PENDANT_ANCHOR`。stage 只记录可见动作；custody 只能由已提交的挂坠处分 WorldCommit 改。相机/手机原有 BodyFrame 规则保留。
- **玩家来源链**：明确 offer 后的接受/拒绝/暂放先写 `PlayerAction(item_disposition_response)`，再由 WorldCommit 的 `source_refs` 指回该行为 receipt，成功后才维持现有 RP4 兼容投影。WorldCommit 冲突时玩家行为可保留，但 RP4 不先写半截。
- **parser 解耦**：`prologue_receipt_disposition()` 只管托付承诺；新增 `prologue_pendant_disposition()` 只认明确物件取舍。于是“我答应照顾他们”不再等于“我收下挂坠”；支持言语及动作通道的收/拒/暂放，沉默、玩笑、继续聊天和 thought-only 均保持 undecided。
- **事实收窄**：accepted 的 public effect 仍是 `pendant_transferred_to_player`；declined/deferred 只写 `pendant_not_in_player_custody`，不再超证据声称“仍由龙也持有”。具体桌面/手中位置继续由后续世界事实裁定。
- **兼容边界**：天安门 turn-0 开局梗概的“既有挂坠事实”仍走 WorldCommit→projection，但不伪造一张当前玩家 PlayerAction。旧存档 `_pendant_accepted()` 的 body_prop fallback 暂保留到 P2c migration。
- **闸**：新增 quick `cafe_world_projection_p2b`；覆盖 accepted/declined/deferred 三投影、stage-only 不转 custody、非挂坠 BodyFrame 不回归、conflict 不让 RP4 抢跑、save/load、turn-0 seed、不混入 custody 的 PlayerAction、言语/动作处分矩阵。
- **验**：本分支最终 Actions [36546969065](https://github.com/killbynothing/causal-anew/actions/runs/36546969065) **success**；quick **48 PASS / 0 FAIL / 163 SKIP（211 validators）**，DB checksum 前后不变。parser 拆分首次 run 36546413067 只暴露旧挂坠修复器误用托付 parser；改读新物件 parser 后 36546541698 绿。
- **报账**：未改 run=0、正典场卡、Seed/VOICE、挂坠 A/B 固定事实粒度或真人 a14 DB；**正典/人物/剧情新增 = 0**。本轮只收事实来源与投影一致性。
- **下一动**：继续 **P2b-2**，用固定咖啡馆输入矩阵捕获真实 caller payload、Beat/RP、World/PlayerAction、BodyFrame、观察账、ExitDecision 与 save→load 联合结果。暂放是否完成 RP4 继续 ★★★，测试只记录当前兼容结果，不把它升格为裁决。

### 2026-09-29（P2a 完成：WorldCommit × PlayerAction × 原子 batch）

- **分权**：新增 `runtime/player_action.py` 与 `runtime/world_commit.py`。PlayerAction receipt 只记录玩家行为（kind/target/value/turn），不允许把 custody、holding、world outcome 偷进玩家行为权；WorldCommit 只接受已经授权的世界事实，不负责替剧情做语义决定。
- **生产接线**：`FreeStageSession._commit_world_transaction()` 不再直接写 `self.world_transactions`，统一委托 `world_commit.commit_world_fact()`；新世界事务自带 RuntimeScope、request/turn、payload hash、source_refs 与 WorldCommit receipt。旧 pre-P2a transaction 可只读重放，绝不补造来源。
- **PlayerAction 接线**：新增 `player_action_receipts` 持久账本；现有 `_record_player_branch_fact()` 先经 PlayerAction 提交，再保留 legacy branch/scene receipt 投影。save/load 已覆盖。
- **幂等/冲突**：同 transaction/action ID 完全同 payload 可重试；同 ID 异 payload/provenance 硬报 `ReceiptConflict` 且 ledger 不变。新增原子 `commit_world_batch()`：稳定 `commit_batch_id`、receipt sequence，先校验整批再发布；任一冲突整批零部分副作用。
- **迁移债**：`P2A_WORLD_MIGRATION_DEBT` 机器列出当前 Authority Map 中仍由兼容路径写的 `branch_progress / scene_receipts / world_transactions(reset/load) / causal_receipts / run_observation_ledger / player_state / body_frames / world_cursor`。P2a 不冒充 World 已全收口；这些由 P2b/P2c 逐项缩减。
- **闸**：补齐历史已登记但长期缺失的 `scripts/tests/test_authoritative_world_transactions.py`，原 quick SKIP 变真实 PASS；同时升级 P0a world writer 断言，要求 `_commit_world_transaction` 不再直接写 ledger。
- **验**：最终 GitHub Actions [36545087570](https://github.com/killbynothing/causal-anew/actions/runs/36545087570) **success**；quick **47 PASS / 0 FAIL / 163 SKIP（210 validators）**，DB checksum 前后不变。首次接线 run 36544703141 仅因 P0a 旧 writer 断言到期而红，新 P2a 七条测试当时已全 PASS；升级断言后 36544870471 先绿，再补 batch 原子性。
- **报账**：未改 run=0、场卡、Seed/VOICE、挂坠 A/B 正典粒度或真人 a14 DB。**哪里是我编的：正典/人物/剧情新增 = 0**；WorldCommit/PlayerAction/batch 是工程协议。
- **下一动**：进入 **P2b 非正典竖切**，先迁挂坠处分后的 player props / Ryuya BodyFrame / observation ledger 派生一致性和来源链；★★★ 的“必须赠与尝试 vs 必须最终 custody”仍不代裁，暂放是否算 RP4 完成也不写死。

### 2026-09-29（P1b 完成：生命周期耐久 × outbox 恢复 × 追加式结算）

- **生命周期**：新增 `runtime/run_lifecycle.py`，可写 run 只允许 `open → closing → closed`；`ended/run_closed` 降为兼容投影，生产只由 `_set_lifecycle_state()` 写。closed run 的 reset/start/skip/stream/step 等写操作不能复活；closing 的下一次 step 只重试原 close，不调用模型。
- **耐久性**：主 session snapshot 改为 temp + `os.replace` 原子替换，损坏 JSON 硬报错。P0b outbox 正式接入 close：先 durable prepare，再写 closing snapshot；即使主 snapshot 写失败，reload 也会从 `.commit.json` 恢复 closing，完成同一 close 后 ack。final snapshot/ack 失败同样可继续原提交。
- **并发/副本**：Web load→reduce→save 以 session_id 进程内锁串行；`save_as` 同 run 副本改成 `snapshot_read_only`，不能产生第二个可写 writer；源/目标按固定顺序加锁，目标用 temp+replace。sidecar 不再出现在存档列表，delete 会同时删主 JSON 与 sidecar。
- **EndRun/settle**：`close_run` 用 SQLite `BEGIN IMMEDIATE` 把“是否已关→settle→receipt”包在一个提交边界，并发双 close 只结算一次。移除 `DELETE FROM delta_sediment WHERE src_run=?` 的重写幂等：同源完全相同则复用，不同 payload/重复 active/已 revoked 同源都硬冲突；revoked 历史不会被 settle 复活或擦掉。
- **保留债**：`run_meta.closed_at/final_delta_summary` 仍以 UPDATE 维护生命周期投影；本轮没有为追求“纯 append-only”擅自新增 DB schema 或扩大例外。该字段级差异继续留作后续迁移/投影债，不宣称所有 UPDATE 已消失。
- **闸**：新增 quick `run_lifecycle_p1b`；升级 P0/P1a authority 与 EndRun 旧反例。故障测试覆盖主 snapshot 写失败、DB close 失败、reload 重试不进模型、closed 禁写、只读 save_as、并发 close、冲突 rollback、revoked 保留、sidecar list/delete 边界。
- **验**：P1b 最终 GitHub Actions [36542378673](https://github.com/killbynothing/causal-anew/actions/runs/36542378673) **success**；`python scripts/verify.py --quick` **46 PASS / 0 FAIL / 164 SKIP（210 validators）**；Actions 前后 `data/world_truth.db` 哈希一致。P1b 中间绿灯还有 36541451878 / 36541722953 / 36542153344。
- **报账**：未修改 run=0、场卡、Seed/VOICE、正典内容或已提交 LFS DB；GitHub 侧没有接触本机真人 a14 DB。**哪里是我编的：正典/人物/剧情新增 = 0**；lifecycle/outbox/并发/只读副本是工程合同。
- **下一动**：只做 **P2a**，先建唯一 WorldCommit/PlayerAction 提交入口与 batch/receipt 投影边界；不提前做咖啡馆 ★★★ RP4 裁决，也不切 P3 心智。

### 2026-09-29（GitHub 同步 × quick CI）

- **同步**：P1a 提交 `6118ff1`（`feat: 收口P1a退出决策权`）；plan / P0a / P0b / P1a 四个指定分支已普通推送 origin。已 fetch 核实：P1a 是远端旧 director-gate 分支 `5acc0bb` 的正常延续；main 的既有 squash 分叉未改动。未 rebase、force push 或重新初始化。
- **验证**：P1a 四条定向测试全 PASS；本机 quick **45 PASS / 0 FAIL / 164 SKIP**。暂存及待推送增量历史密钥模式扫描无命中，排除 DB、配置、密钥和运行态。
- **CI**：独立分支 `loop/github-quick-ci-2026-09-29` 新增 `.github/workflows/verify.yml`，Ubuntu + Python 3.11 + LFS checkout；仅跑 quick，不注入模型密钥；前后校验已提交 DB 的 SHA256。远端 Actions 结果以该分支实际 run 为准。
- **干净环境修复**：首次已提交源码/LFS DB 副本 quick 为 44 PASS / 1 FAIL / 164 SKIP，暴露 smoke 对 ignored `web/config.json` 的依赖；改用临时空密钥配置夹具并补无配置场景，保留模型/选项/密钥字段断言，不读取真人配置、不删测试。
- **CI 提交前验**：修复后干净副本 quick **45 PASS / 0 FAIL / 164 SKIP**；LFS DB 哈希仍为 `5af683f316ec04067338412934b8c8ece128109c70b41d4b37ff4b7052e02852`，workflow YAML 解析通过。
- **远端验收**：CI 提交 `88bc6b9` 已普通推送；首次因 OAuth 缺 `workflow` 权限被拒，用户补授权后成功。[GitHub Actions 36539243584](https://github.com/killbynothing/causal-anew/actions/runs/36539243584) **success**，Ubuntu quick 通过且 DB 校验通过。五个目标分支均已同步；P1b 未启动。
- **保留**：真人 a14 DB 保持本地未提交，SHA256 `c582c623f25088088dc13080e1985b0d1695a2c63077f555995ea50645452084`；未启动 P1b。
- **哪里是我编的**：正典/人物/剧情新增 = 0；本轮仅版本同步与 CI 工程配置。

### 2026-09-29（P1a 完成：ExitPolicy 单一授权 × 目标冻结）

- **做**：新增 `runtime/exit_policy.py`，把退出授权收为纯 `ExitRequest → ExitDecision`；Decision 自带最终 target/mode/exit_spec，生产执行层不再重新选出口。接入 `step/_maybe_transition/skip_scene/run_session/flashback return/placeholder end`，但未改 P1b close durability。
- **修**：删除 `step()` 的“MH 齐且无 exits 自动 EndRun”和 `run_session()` 的事后 `ended=True`；MH 只影响 eligibility。semantic receipt 改为 prospective 审核事实，授权后才落账；forced confirmation 持久化第一次审核 target，取消/确认不重新选路；卡 `intent_tokens` 也纳入确认口径；多出口 generic leave 先出 menu。
- **skip**：brief 多出口不再静默取 `exits[0]`；无出口只有显式 auto-end 才可关。skip 直接写 `completed` 仍是 P2 Beat 债，本轮没顺手收。
- **生命周期边界**：`self.ended=True` 现在只在 `_mark_ended()`；但 reset/场景切换仍写 `ended=False`，close 仍走旧 `_close_run_once`。所以 P1a 是“授权单一”，**不是**“生命周期持久化已单 writer”；后者留 P1b。
- **闸**：新增 quick `exit_policy`、`exit_policy_production_wire`；升级 P0a authority/characterization 让已修的 `run_session` 旁路必须消失，同时保留 P1b lifecycle 多 writer 债。旧 smoke 的“MH 完成即 END”断言也升级为“完成后不自动关”。
- **验**：`python scripts/verify.py --quick`：**45 PASS / 0 FAIL / 164 SKIP（209 validators）**。Authority Map 已重生成：**228 writer / 130 production+tooling / 19 uncertain alias / 0 parse error**。
- **报账**：未改 run=0、场卡、Seed/VOICE、a14 或 `data/world_truth.db`；真人 DB 差异继续不进提交。**哪里是我编的：正典/人物/剧情新增 = 0**；ExitRequest/Decision、confirmation target 与 placeholder compatibility 标签是工程合同。
- **下一动**：只做 **P1b**：open→closing→closed、close 失败可恢复、closed 禁写、reset/save_as/并发、副本写权，以及 settle 的 delete/update 只追加债。P1b 完成前不切 P2。

### 2026-09-29（P0b 完成：Receipt × Snapshot × Schema × Recovery 合同）

- **做**：P0b 只建立协议与故障恢复合同，未切任何生产 writer。扩展既有 `runtime/causal_protocol.py`：`RuntimeScope`、`ReceiptEnvelope`、canonical payload hash、scope/幂等冲突检查、稳定 batch key、`PendingCommit / CommitCursor` 的 prepare/ack；没有新造第二套事件总线。
- **Snapshot**：新增 `runtime/runtime_snapshots.py`，`WorldSnapshot / ActorSnapshot` 用 canonical JSON 冻结 payload，调用方拿到的始终是新副本；只做只读协议视图，尚未接 `FreeStageSession`。
- **迁移**：新增 `runtime/session_schema.py` + v1/v2 fixtures。证明 `free_stage.session.v1 → v2` 纯内存、非破坏、未知版本拒绝、禁止降级；**生产仍明确写 v1，未 import 新迁移模块**。仓内旧 `session_opening_migration` 是 bridge→narrate 的另一语义，P0b 新闸使用 `session_schema_migration`，没有劫持旧名字。
- **耐久边界**：自审后明确 **pending/ack 只有一个权威**：session v2 只保存 `snapshot_revision + last_committed_batch_id`；待提交游标只在 `RuntimeStore` 的 `.commit.json` outbox sidecar。sidecar 用 temp+`os.replace` 原子替换，损坏文件硬报错；故障注入已证明失败不会覆盖旧 durable outbox。现有主 session `load/save` 仍保持旧实现，属于 P1b 债。
- **DB**：P0b 没有 DDL/表迁移。未来 commit batch 的稳定键字段定为 `worldline/run/session_id/scene_instance_id/request_id/batch_index`；真正 DB unique/index 要到对应 writer 迁移阶段走既有 import/迁移流程。
- **闸**：补齐历史登记但缺失的 `test_causal_protocol.py`，并新增 `test_receipt_protocol.py`、`test_session_schema_migration.py`。三条定向测试全通过；全 `python scripts/verify.py --quick`：**43 PASS / 0 FAIL / 164 SKIP（207 validators）**。原 `causal_protocol` 从 SKIP 变真实 PASS，新加两条 P0b required gate。
- **报账**：未改 run=0、场卡、Seed/VOICE、a14、生产 session schema 或 P1/P2 writer；`data/world_truth.db` 既有真人运行态仍不纳入提交。**哪里是我编的：正典/人物/剧情新增 = 0**；receipt/snapshot/outbox/schema 是工程协议。
- **下一动**：只做 **P1a**：统一 ExitRequest → ExitDecision、目标解析与最终前置条件闸；先用 legacy 只读桥。P1b 前不改 close durability，P2 前不切 World/Beat writer。

### 2026-09-29（P0a 完成：Authority Map × required gate）

- **做**：只实施重构计划 P0a，不改 runtime 生产行为。新增 `scripts/audit_runtime_authority.py`，静态扫描 runtime/web/scripts 的 tracked state 属性写、容器 mutator、局部别名/疑似 mutating helper、关键 SQL DML，并给 direct writer 建 best-effort caller 索引；同时读取 `scripts/verify.py` 登记表。
- **产物**：`docs/analysis/runtime_authority_map_2026-09-29.json`（机器原件）+ 同名 `.md`（人读投影）。每条 writer 带 semantic fact、current/target owner、classification、scope、caller、confidence、removal phase。
- **结果**：**223 writer / 128 production+tooling / 19 uncertain alias / 0 AST parse error**；23 个 tracked fact 有多 production writer。19 条 uncertain alias 明确保留为对应域切换前的阻断项，不把 AST 没证明的东西当不存在。
- **闸**：新增 quick ID `runtime_authority_map` 与 `authority_characterization`。前者保证 Beat/World/Mind/Exit 代表 writer、外部 `session.ended`、初始化分类、caller、verify inventory 可被抓；后者把现有多 Beat writer、legacy mind、Exit 多写路、settlement DELETE/UPDATE、unknown alias 冻结为 KNOWN_BUG 证据，后续修复必须与新 invariant 同步改，不准删用例变绿。
- **验**：正式报告附带实跑 `python scripts/verify.py --quick`：**40 PASS / 0 FAIL / 165 SKIP**；quick 登记从 203 增至 **205**，静态 precheck 与实跑计数一致。两条 P0a 定向测试单独运行也通过。
- **报账**：未改 run=0、场卡、Seed/VOICE、runtime 行为或真人存档；`data/world_truth.db` 的既有 a14 运行态差异继续不进提交。**哪里是我编的：正典/人物/剧情新增 = 0**；target owner/removal phase/扫描启发式是工程元数据。
- **下一动**：只做 **P0b**：最小 receipt envelope、immutable snapshot、schema migration fixtures、pending/ack 与恢复游标合同。P0b 稳定前不提前切 ExitPolicy/World writer。

### 2026-09-29（重构计划细化：源码核查完成，实施从 P0a 开始）

- **判断**：需要结构性重构，重点是唯一写入权与提交边界。AST 核准 `free_stage_prototype.py` 13,539 行、`FreeStageSession` 5,054 行、`step()` 1,765 行。原有机制保留，先收权再拆文件。
- **新证据**：通用 MH 齐自动关局及 CLI/skip 旁路仍在；BodyFrame 可凭递物 stage 提前记交付；Reflect 仍会催下一拍必须交坠；关局失败可能留下 ended/DB 不一致；settle 的 DELETE/UPDATE 是既有只追加债。静态风险不冒充本轮复现，a14 人验仍引用已有记录。
- **文档**：原 `计划_运行时权威收口×主循环重构_2026-09-28.md` 已细化为 18 节：证据表、五域 writer 合同、收据/提交/流式公开边界、P0a–P6b 交付与验收、必跑测试矩阵、版本迁移和失败恢复。纠正“无存档版本”“ContextAssembly 未进生产”两处旧判断；现有版本与审计包装继续复用。
- **下一动**：P0a 测绘与测试基线 → P0b 最小协议/恢复合同 → P1 退出与生命周期 → P2 World 全写路径 + Beat/PlayerAgency → P3 心理 → P4 参与 → P5 装配 → P6 拆循环；**P0 扫描器/新测试尚未实现，P1–P6 未启动**。挂坠固定事实粒度仍 ★★★，不代裁 tier/never_soften；未裁不切改变正典的 RP4 合同。
- **验**：本机 Python 3.11 实跑 `scripts/verify.py --quick`：**38 PASS / 0 FAIL / 165 SKIP**。部分核心测试登记了但文件缺失，故新计划要求本阶段 required gate 缺失/SKIP 即不算完成。
- **哪里是我编的**：新增正典/人物/剧情为零；收据字段、状态机、模块边界和迁移/测试规格是工程提案。只改计划、INDEX、路线图与本状态；未改运行时、库或真人存档。已有数据库运行态差异留在工作区，不随文档提交。

### 2026-09-28（架构复盘：从补丁收口转入运行时权威重构）

- **总体判断**：方向/宪法没有错，问题在生产接线。现 `free_stage_prototype.py` 约 13.5k 行、`FreeStageSession` 约 5k 行、`step()` 约 1.8k 行；角色、导演、MH 会计、玩家行动、转场/EndRun 与场特例在同一主路径互相读写。a14 的假断线、RP 齐自动关局、托付/挂坠抢跑属于同一类“多权威接缝债”，不再按孤立 badcase 继续贴补丁。
- **新计划**：新增并登记 `docs/plans/计划_运行时权威收口×主循环重构_2026-09-28.md`，挂长期路线图阶段 5；允许结构性大改，但仍守 AGENTS 红线与 ★★★ 人裁。长期路线图同步为：先完成 ActorMind / Resolver / Beat / PlayerAgency / Exit 唯一权威，再继续 causal_web / 全角色量产。
- **目标架构**：世界事实只由 EventReceipt/Resolver 落；角色持续心理只由 ActorMind；MH 内部改 BeatState（必要时支持 offered→settled）；玩家关键动作必须有 PlayerActionReceipt；EndRun/transition 只经 ExitPolicy；Floor 只仲裁参与冲突，不替角色分配内容。
- **准备淘汰**：`private_inner_states` 作为持久心理权威、直接 `completed.append` 业务路径、generic MH complete→EndRun、core loop 的 scene-specific if forest、content-aware speaker boost、`context_assembly` 仅观测不生产的双装配。
- **执行序**：P0 authority map + characterization → P1 ExitPolicy → P2 BeatState + PlayerAgency（咖啡馆竖切）→ P3 ActorMind 真权威 → P4 participation ownership → P5 ContextAssembler 唯一入口 → P6 TurnEngine / ScenePolicy 拆主循环；两场人验稳定后才回 causal_web。
- **★★★ 待人裁**：挂坠固定事实粒度。A=龙也必须完成“明确赠与尝试”，玩家可拒/暂放；B=本节点结束前玩家最终必须取得挂坠，但必须提供合法世界因果路径，绝不能靠 stage 强塞。裁决前运行时按最保守 Player Agency：未明确接受则不写 custody。
- **本轮报账**：只做架构审计与计划文档，未改运行时代码、run=0、角色 Seed/VOICE 或正典内容；`data/world_truth.db` 仍只有 a14 真人运行态变化，继续不进代码提交。

### 2026-09-28（刀 6 人验前收口：语义节奏 × 单一心智权威 × 去机械复用）

- **做**：咖啡馆导演新增确定性 `hold/open/neutral/close` 节奏信号，只管“什么时候”，不代角色决定“说什么”；`你最好有事情` 这类轻口吻/回避不再因拍数直接跳托付。`ActorMind` 明确为唯一持久心智权威，旧 `private_inner_states` 降为本拍 working context；观测台工程原件改读 `actor_state`。共史锚点保留 4 条边界，但每拍只轮换 ≤2 条提醒；角色 prompt 已要求相似小动作宁可留空，不换词重复敲桌/收目光/摸杯。
- **验**：新增节奏、锚点轮换、ActorMind 单一权威测试；`python scripts/verify.py --quick` **38 PASS / 0 FAIL / 165 SKIP**。
- **人验实抓**：真人咖啡馆连续抓到三层红灯：① 独立序幕出口缺 `pending_entry` 曾抛 HTTP 500；② RP1–RP4 全齐曾被误当自动 `EndRun`；③ **托付/挂坠节拍过紧**：RP2 曾可被拍数自动满足，RP3 证据曾把 stage 动作也当口头托付，RP4 曾把“动作递物”直接算交付，并在玩家暧昧回应时替玩家把挂坠塞进手里。现合同统一改正：**拍数不证明节拍；RP2 要可见语义转向，RP3 只认龙也真正说出口的全名托付+禁名，RP4 拆成“明确口头赠与+可见递出 → 等玩家下一拍收/拒/暂放”两段**。玩家未表态时任何“塞进手心/替你戴上”都会被运行时修复为“挂坠停在两人之间，等待决定”。RP4 后无离场信号仍 `pace=neutral` + `post_entrust_chat`；玩家明确离场才收束。
- **API 基线**：火山 CodingPlan 已过期，运行基线切到 DeepSeek 官方 `deepseek-flash`；`config_experiment.json` / 默认 fallback / UI 同步，Key 仍只在 gitignore 的 `web/config.json`。15 次短压测 15/15 HTTP 200；本局调用未见线路级异常。
- **a14 恢复**：run=1/run=2 的错误关局均保留审计；run=2 误生成的 `delta_sediment` scar 已用既有 `revoked=1` 机制作废，不删历史。现追加 run=3 `kind=fork`、`fork_event=bug_recovery:pendant_two_step:a14:run2`，恢复到第 10 拍：龙也已明确说“是给你的”并把挂坠递到玩家这边，`RP1–RP3` 完成、`prologue_pendant_offered` 成立、`RP4` 未完成。重放玩家原句“想再见见你总要有个借口吧”后：`ended=false`、仍仅 RP1–RP3，龙也只把挂坠往玩家这边推半寸，没有强塞、没有自动关场。
- **你**：直接继续 `a14`。现在系统正等你自己决定挂坠：可以收、拒绝、先放着，也可以继续聊。挂坠去向不会再由动作或暧昧台词代判。之后只有你明确离场才真正关局，再开下一新周目验疤。
- **报账**：未改 run=0 正典、场卡正典、VOICE 原句或角色 Seed；只改运行时证据闸、角色工作目标/节奏、玩家行动权修复与测试。真人运行态保留 run/δ 审计，错误沉淀只标 `revoked`，不删除历史。
- **验**：新增“高拍数不自动 RP2/entrust、stage 不冒充口头托付、挂坠必须话+动作、未表态禁止强塞”回归；`python scripts/verify.py --quick` **38 PASS / 0 FAIL / 165 SKIP**。
- **下一动**：继续 `a14` 人验两件事：① 挂坠回应是否自然；② 托付之后是否还能松弛聊天。玩家自己关局后再开新周目验疤。

### 2026-09-18（实习专项最小集：Rubric × 工具契约 × 七槽 × 对齐旁路）

- **做**：现行计划改为 `计划_对标游戏公司实习_Rubric评测×工具契约×对齐旁路_2026-09-18.md`（初稿 MCP/运行时 DPO 标过期，文件保留）。落地：`runtime/director_tools.py`（五招 Function Calling schema，非法调用拒）；`runtime/narrative_rubric.py` + `scripts/eval_narrative_rubric.py --smoke`（任务/一致/叙事/工具/安全）；`runtime/agent_module_slots.py` 投影进 `debug_payload.agent_modules`，观测台 ④ 七槽只读；`scripts/pipeline/build_preference_pairs.py` 旁路 jsonl + 可选 PyTorch 头（不进闸）。
- **验**：`--quick` **38 PASS / 0 FAIL / 165 SKIP**（+director_tools / narrative_rubric / agent_module_slots / preference_pairs）。`eval_narrative_rubric.py --smoke` 黄金集该挂的维挂。preference holdout 分类头 1.0（失败谓词特征，非句长）。
- **你**：硬刷新观测台新开咖啡场——④ 组应见七槽；点美式仍应是龙也自己说。人验记录仍要你写 `play_logs/`。
- **报账**：机制与评测夹具；负例对白不进库/VOICE。未编正典。简历仍仓外。MCP 未做。SFT/DPO 未接运行时。
- **下一刀**：导演闸刀 6 薄压力（人感）仍并行；本专项投递前你要打完一场咖啡馆。

### 2026-09-18（实习专项：对标游戏公司 AI Agent 研发计划落位）

- **做**：对标头部游戏公司 AI NPC / Agent 核心研发与算法实习岗位，完成专项升级规划并落位：`docs/plans/计划_对标游戏公司实习_Rubric评测×DPO微调×MCP工具_2026-09-18.md`；同步登记 `docs/plans/INDEX.md`。
- **拆解**：四大模块：① 叙事与角色 Rubric 自动化评测体系（Agent Eval）；② NPC 认知对齐 SFT/DPO 数据飞轮与微调管线；③ 标准 Tool Use 与 MCP 协议适配；④ 工业级架构门面与求职面试攻防手册。
- **验**：`--quick` **34 PASS / 0 FAIL / 165 SKIP**。
- **报账**：规划与索引落位，未改动 `data/world_truth.db` 既有正典事实。
- **下一动**：启动模块一，编写 `scripts/eval_narrative_rubric.py` 混合评测套件。

### 2026-09-11（刀 5：下周读疤）

- **做**：`runtime/scars_reader.py`（`read_run_scars` + `compute_node_effective_threshold`）；读取 `src_run < current_run` 的 `delta_sediment`；固定底节点强制 $S \equiv 0$；`FreeStageSession` 开局/reset 挂接 `sediment_S` 与微残影 `ambient_scar`（物理感官质感，零泄密）；`physical_state` 携带软化度。
- **验**：`test_read_scars` 6 例；`--quick` **34 PASS / 0 FAIL / 165 SKIP**。固定底仍挡。
- **你**：新开第二周目（run≥2）时，观测台与会话状态能读到上周目沉淀 $S$ 且有效阈值自动软化；龙也仍不知上周目。
- **报账**：机制；未编正典。残影文本纯物理感官，无元词汇。下一刀：刀 6 薄压力人感 / Rubric 评测脚本。

### 2026-08-28（刀 4：EndRun + 冷回执）

- **做**：`runtime/end_run.py` 关局 settle、出事实清单（无情感、无署名）；场结束 `_mark_ended` 只关一次；`reset()` 不清已关周目。
- **验**：`test_end_run` 5 例；`--quick` **33 PASS / 0 FAIL / 165 SKIP**。固定底仍挡。
- **你**：打完一场应收回执 toast（run N · k 条）。署名/口气仍 ★★★，这张单只记账。
- **报账**：机制；未编正典。下一刀：下周读疤（刀 5）。刀 6 薄压力人感仍待。

### 2026-08-28（刀 3：δ 进库）

- **做**：`runtime/delta_db.py` 把玩时 δ 追加进 `world_truth.db.delta_ledger`（run≥1，幂等，run=0 整批拒绝）；`free_stage` 双写 JSON 追溯件 + 库表（库失败不中断游玩）。Z1b dump 把 `run_meta`/`delta_ledger`/`delta_sediment` 标成玩时可变表，不进 sql 指纹。
- **验**：`test_delta_ledger_db` 8 例；`--quick` **32 PASS / 0 FAIL / 165 SKIP**。G1 存档仍不写真值库；δ 事件进库是本刀合同。
- **你**：新开一场并正常离场后，库表应有 run≥1 行；`reset()` 仍不写新 δ。下一刀才是 EndRun+结算单。
- **报账**：机制接线；未编正典。JSON 里原有天安门 `normal_exit` 未回填进库（等人下场玩时写入）。legacy `scene_api.py` 冻结不改。测试默认不传 `truth_db`，避免 `--quick` 污染真库。
- **下一刀**：`计划_导演闸×周目回执×角色环不动_2026-08-14` **刀 4** EndRun+回执。

### 2026-08-17（刀 2：开局写 run_meta，run 递增）

- **做**：`runtime/run_registry.py`（`open_run` 只追加 run≥1）；观测台「从头新开」`create_session` 登记一行；存档记下 `run_no`；resume 不新开；`reset()` 仍不是新周目。
- **验**：`test_run_meta_open` 5 例；`--quick` **31 PASS / 0 FAIL / 165 SKIP**。G1 存档仍不写真值库。
- **你**：观测台从头新开一场，再新开一场，第二场 `run` 应为 2。`reset()` 不应变成 run 3。
- **报账**：机制；未编正典。下一刀：δ 进库。

### 2026-08-17（交接：下一刀仍是 run_meta）

- **能玩**：咖啡馆闪回、天安门。导演闸刀 1 机制完；点咖啡店员薄声=人验待你。
- **下一刀**：`计划_导演闸×周目回执×角色环不动_2026-08-14` **刀 2** 开局写 `run_meta`。刀 3–6 未做。
- **不要**：换角色环、训世界基模、DSH 当车间。简历在仓外。
- 新会话读：AGENTS → 本文件最上 → 该计划「新会话入口」。

### 2026-08-17（门面：北极星提前，原著名用《存在的意义》）

- README 开头改北极星；公开页原著名去掉「因果之外」。哲学文链到「为什么这样做」。
- 个人页 / 简历在仓外改：GitHub 不出现真名和单位。

### 2026-08-17（门面措辞：工程译成体验问题，去掉虚数字）

- README / `docs/design-philosophy.md`：四端口、FTA、Goffman 改成「遇到什么体验问题 → 怎么解」；删未实测的「约 5%」、目录里的「92 个文件 / 30+ 测试」。
- 简历与 GitHub 个人页在仓外改，不进本仓。身份：同人读者，不是原作者。

### 2026-08-14（目录改名：c1_web_console→web，design 压平，GIT 工作流进 docs）

- GitHub 文件列表要靠**顶层名字**变，不是靠 README。
- `c1_web_console` → `web`；`design/00_架构/*` → `design/`；`GIT工作流_…` → `docs/git-workflow.md`。

### 2026-08-14（门面：README 去海报化 + LICENSE + docs/analysis 索引）

- GitHub 目录页显得像草稿：默认分支提交旧、README 黑客松风、`web` 名暂不改（断路径）。
- 改：专业 README；`LICENSE` 源码保留、原著权利不转；`docs/README.md`、`analysis/README.md`。

### 2026-08-14（落位：根目录临时件进 scratch；远程钉 causal-anew）

- 根目录 `tmp_*` / `maki_temp*` 挪进 `scratch/`（gitignore 已挡）。
- `origin` = `https://github.com/killbynothing/causal-anew`。

### 2026-08-14（刀 1 收尾：voice 上场 × 本拍合法招 × 瘦提示）

- **做**：`fold_world_skin_into_ambient`（voice/stage.hint→ambient）；`opportunity` 必须 ∈ 本拍 `legal_moves`；snapshot 补封顶/离场钟/收窗；真调用走 `build_harness_prompt`。
- **验**：`test_director_harness` 21 例（含点美式店员可见）；`--quick` 30/0/165。
- **你**：硬刷新后新开咖啡场，点一杯美式——左栏应有店员薄声，主卡仍是龙也自己说。
- **报账**：机制；未编正典。下一刀才是 run_meta。

### 2026-08-14（计划刷新：刀进度 + DSH 能学什么 + 离终点）

- **文**：`计划_导演闸×周目回执×角色环不动_2026-08-14.md` 重写进度节。
- **刀 1 ≈60%**：主卡词卸了；`voice` 未上场；opportunity 未闸本拍合法招。刀 2–6 = 0。
- **DSH**：不当车间。只学：能力组合、只追加轨迹、预设先冻。
- **下一刀**：刀 1 四条收尾（voice 并进 ambient 等）。未动业务码。

### 2026-08-14（用词改名：导演闸 / 角色环；DSH 不当本仓车间）

- **改名**：计划 → `计划_导演闸×周目回执×角色环不动_2026-08-14.md`；设计 → `导演闸主循环备忘_四端口×闭集_2026-08-14.md`。代码 `director_harness.py` 不动（那是笼子实现）。
- **口令**：角色要活（角色环）；导演要冷（导演闸）。Harness ≠ 物种。
- **DSH**：创造模式是通用 Agent 车间，**不是本项目车间**。本仓车间=观测台+verify+迁库。
- **刀 1 仍未完**：`voice` 未接到可见层。

### 2026-08-14（刀 1 落地：导演卸 turns × 证据先行会计 × 闭集五招 × 四端口接线）

- **产出**：`runtime/director_harness.py`（出招/裁招/复核）+ `runtime/beat_evidence.py`（注册节拍证据表）+ `runtime/free_stage_prototype.py` 生产接线 + `scripts/tests/test_director_harness.py`。
- **刀 1 合同**：导演 LLM 只填 `{director_note, opportunity, stage, voice, mh_progress(hint)}`；**主卡台词只由 `call_actor_packet` 产出**（导演写 turns → 拒收+降级 `director_turns_rejected`，绝不重试导演）；`opportunity` 必须是闭集五招（quiet/店员薄声/时间压/放进路人/收窗）之一，非法即 fatal；mh 是 hint，注册节拍一律被证据覆盖。
- **证据先行**：RP1·RP2·RP3·TM1·TM2·TM3·TM4 凭可见证据落账（复用现有手调谓词防漂移）；after 顺序 + 隐式前置（后拍证据⇒前拍已完成）；**RP4 不在证据表**（留 tuned hint + 收据块 + authored 挂坠降级兜底）。
- **四端口**：Resolver 会计（永不 LLM）→ 看见 → 闭集出招 → Resolver 裁招 → LLM 只填 Stage/Dramaturgy/Voice → Resolver 复核 → 留痕（`director_port_trace` 含 Dramaturgy 闭集招记录，`dispatch_turn` 透传 opportunity）。
- **maki 假链接**（真纪→海洋馆=正典污染）：进 `_AMBIENT_BANNED`（导演 voice/ambient 闸）+ OPENING_TIANANMEN_002 演员行 SOFT 守卫（红字+降级 `maki_aquarium_false_link`）；**非**全局 hard_check（王府井 WJ3 自测里「真纪说直接去海洋馆」是正典 → 会误伤）。
- **验**：`--quick` **30 PASS / 0 FAIL / 165 SKIP**（新增 director_harness 验证器；free_stage_smoke 5 个旧合同测试改写为新合同；双向软证据样例 RP3/TM2 防假阳+防漏检；天安门无 hint 凭证据走完 TM1-4）。
- **报账**：机制接线；未编正典。★ 待你裁：RP4 挂坠 authored 兜底（有 provenance 的确定性降级）是否保留；WJ/真纪「直接去海洋馆」正典口径存疑（★★★，见设计备忘）。
- **你**：重启控制台后新开天安门场——导演不再写主卡台词；无 hint 也能按证据推进 TM1-4。

### 2026-08-14（导演 Harness 主循环设计 · 未动码）

- **产出**：后改名为 `design/导演闸主循环备忘_四端口×闭集_2026-08-14.md`。
- **要点**：一拍内顺序 = Resolver会计(永不LLM)→看见→闭集出招→Resolver裁招→LLM只填Stage/Dramaturgy/Voice→Resolver复核→四端口留痕；闭集=quiet/店员薄声/时间压/放进路人/收窗；导演合同删 `turns`+`mh_progress`；接线映射到现码行号。
- **未动码**：接线留刀 1 loop（先测试→再接线→`--quick` 绿）。
- **报账**：机制设计；未编正典。

### 2026-08-14（规划：导演闸 × 周目回执 × 角色环不动）

- **裁定**：不训世界基模、不换角色环。导演重是因为还在写 `turns`；run 轴表在 0 行；关局无回执。
- **文**：后改名为 `docs/plans/计划_导演闸×周目回执×角色环不动_2026-08-14.md`。
- **刀序**：①导演卸 turns ②开局 run_meta ③δ 进库 ④EndRun+结算单 ⑤下周读疤 ⑥薄压力。回执署名 ★★★。
- **未动码**。咖啡 G4 人验仍要你走。
- **报账**：机制规划；未编正典。

### 2026-08-09（a13 人验：闲聊无 Agent × 旁白左栏 × 托付重宣 × 收束）

- **根因（a13）**：多数拍 `speakers=[]` → 掉进无包 `call_actor`，Decide/Reflect 空白；`player_visible_turns` 漏 `narrate`；RP3 只看本拍导致禁名跨拍不齐、画像重念。
- **第一性**：独立咖啡馆=闪回内容的排练，脊柱=闲聊→临走信号→托付一次→交坠→收束；单人场竞价不得踢主卡。
- **修**：`ensure_solo_or_prologue_speakers`；旁白进左栏；托付跨拍累计+重宣修复；点咖啡 ambient 提示店员；MH 齐后独立场可收束。
- **你**：硬刷新后新开场；观测台左栏应见旁白；闲聊包应有 Decide。

### 2026-08-08（咖啡首句改 LLM 即兴 · 去掉写死雨句）

- **改**：`start` / 闪回入场不再塞 authored「这雨下得…」；`_llm_ryuya_opening_turn` 走角色包+VOICE，可调侃雨/初遇泼袖/开档身份；`opening_temperature` 默认 0.75。
- **降级**：无 caller/无 api_key → **不**回退固定台词（只留旁白）；托付清单句软拒。
- **验**：`test_llm_opening_not_authored_rain` 等。
- **你**：重启控制台后新开咖啡场，首句应每次不同。

### 2026-08-08（托付张尘优先 × 画像入库 × 声纹 × 已说事实真写入）

- **根因**：RP3 先 `extend` 进 `completed` 再查「不在 completed」→ **托付永远写不进** `run_observation_ledger`；`stated_public_facts` 又要求双全名才算说过 → 「照顾」复读三次仍当第一次。
- **机制**：放宽事实检测（半截照顾/复读次数/账本 kind）；soft want + `no_reannounce`；ledger 用 `newly_completed`。
- **库/卡**：BOUNDARY+HOLD+IDENTITY 张尘优先；画像（成熟其实累 / 天才好人嘴毒）；want/RP/locks 同步。
- **声纹**：`ex_brother`（L18918–32）+ `ex_entrust_soft`（authored 张尘优先口吻）+ cadence 禁断言共史/禁复读照顾。
- **验**：`test_ryuya_voice_cog_loop`；props 484；`--quick`。
- **报账**：画像为人裁软口径（非原著整句）；天才句有行号；§5.1 仿写仍不迁。
- **你**：硬刷新后新开咖啡场——托付应先张尘；说过照顾后应推交坠；交坠后平常道别收束。

### 2026-08-08（声纹闲聊补库 × 已婚淡提 × Agent 闭环）

- **判断**：不扩共史硬闸；用 soft anchors + Decide/Reflect 回灌压瞎编。
- **声纹**：`P.VOICE.ryuya.W1.ex_casual`（L14633/39/50）+ `ex_married_soft`（L1728）；cadence 改闲聊优先；`migrate_ryuya_voice_cafe_2026-08-08.py --apply`。
- **婚姻**：HOLD 放宽——可淡提「结婚了/已婚」，不提妻名；定情/信物 cue → Decide 顶格轻挡。
- **闭环**：`prior_reflect_by_cons` 进下一拍；`stated_public_facts` 防托付重宣；托付已出口则 want 软推到交坠。
- **验**：`test_ryuya_voice_cog_loop` 🟢。
- **报账**：声纹原著行号；未编新剧情；§5.1 仿写仍不迁。
- **你**：重启/硬刷新后新开咖啡场；调侃定情信物应能淡提已婚；托付后应少复读。

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

- **设计**：`design/社交参与与自主决策备忘_…` 人裁为**全场**现行；`runtime/social_participation.py` 各角色社交习惯可用。
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

- **观测台**：流水线置顶（装配展开 + 按人核/关系/记忆/先想/再说）；已固化对照保留；「角色」改为深检副本默认不展开。服务已重启（`web/server.py`，自检 `observer.html` 200）。
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

- 文：`design/三层分工备忘_…`

### 2026-08-03（苏颖退出固定底 + β S6）

- `CC.SUYING_DEATH` 已删；`run_meta`/`delta_sediment`/settle 已落。
