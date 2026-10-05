# P6 基线测绘：主循环 × ScenePolicy × FreeStageSession writer（2026-10-05）

> 分支：`loop/turn-engine-p6-2026-10-05`
>
> 基线：`loop/context-assembly-p5-2026-10-03@655c550e6ff9ea958817e23606e93ab14108fd9d`
>
> 目的：只做 P6 开工前的源码测绘与迁移边界确认，不重做 P2c/P3/P4/P5，不改正典、场卡、Seed/VOICE、run=0、★★★ 挂坠裁决或 `data/world_truth.db`。

## 1. P5 基线继承

`acc5282a22613caa5e35761da43373f4e8686f30..655c550e6ff9ea958817e23606e93ab14108fd9d` 只有两份文档变化：

- `STATUS.md`
- `docs/plans/计划_运行时权威收口×主循环重构_2026-09-28.md`

因此 P5 final 文档 HEAD 的 runtime/tests/workflow/DB 内容与已绿代码态 `acc5282a` 相同。已知代码态证据仍是 Actions `37211358100` success、quick 63 PASS / 0 FAIL / 161 SKIP、`context_assembly [OK]`、P0–P4 required gates 绿、`data/world_truth.db: OK`。

当前 GitHub connector 的 commit→workflow 查询只枚举 pull-request-triggered runs，`655c550e` 返回空，故本报告不把“未枚举到 push run”冒充为该文档 commit 的 Actions success。

## 2. 当前主循环形状

`runtime/free_stage_prototype.py` 当前：

- `FreeStageSession`：约 6337 行（6507–12843）
- `step()`：约 1910 行（10075–11984）
- `skip_scene()`：约 192 行（12014–12205）
- `_maybe_transition()`：约 644 行（12233–12876）
- `_load()`：约 209 行（6694–6902）
- `reset()`：约 84 行（7517–7600）
- `advance_utterance()`：8967–8986
- one-shot `run_session()`：13630 起，仍以 `FreeStageSession.step()` 为唯一业务入口并随后 drain queue。

仓内目前没有：

- `runtime/turn_engine.py`
- `runtime/scene_policy.py`
- `runtime/scene_policies.py`

所以 P6 不是“接已有 TurnEngine”，而是把现有 Session 内的编排职责抽出，同时保持 P2–P5 owner 不变。

## 3. Writer 分类：权威 owner 已收口，但提交编排仍困在 Session

下表的“writer”指由 `FreeStageSession` 发起的生产状态变化。它们多数已经调用 P2–P5 的唯一 owner，因此是 **P6 orchestration debt**，不是重新出现的多 owner debt。

| 域 | 当前 Session 发起点 | 当前真正 owner | P6 判断 |
|---|---|---|---|
| Beat | `_beat_complete/_beat_complete_many/_beat_replace/_archive_scene_beats`；`step` 10281/10436/10707/11416/11501 等 | BeatState / SceneBeatArchive / FrameBeatState | owner 保留；何时提交由 TurnEngine + ScenePolicy proposal 驱动 |
| World | `_commit_world_transaction`；`step` 与 transition 内 world proposal/commit | WorldLedgerState / WorldCommit | owner 保留；ScenePolicy 不得直接调用 commit |
| Physical | `_body_ensure/_body_settle`、`physical_state.increment_elapsed/decrease_convergence/patch_player` | PhysicalState | owner 保留；从 Session 业务流程迁到 engine commit/project 阶段 |
| Scene fact projection | `_branch_add/remove`、`_record_scene_receipt`、`_observe` | RuntimeFactProjection / ObservationLedgerState | 只保留投影 owner；policy 只能返回 evidence/proposal |
| Mind | `_record_player_visible_mind_receipts`、`_record_public_actor_mind_receipts`、WorkingContext patch、ReflectProposal set | ActorMindState / TurnWorkingContextState / ReflectProposalState | P3 owner 不动；TurnEngine 在 observe/enact/commit 节点统一调用 |
| Participation | `build_speaker_plan` → P4 intents/floor → actor call | Participation/Floor protocol | P4 不重做；TurnEngine 只编排 deliberate→floor→enact |
| Context | actor 调用前 build/finalize | ContextAssembler | P5 不重做；TurnEngine 只能调用 assembler 唯一入口 |
| Exit/lifecycle | `step→_maybe_transition`、`skip_scene`、`_mark_ended`、card/cursor/lifecycle 切换 | ExitPolicy + run_lifecycle + domain owners | P6b 重点：decision 与 execution 分开，Session 不再自己夹场规则重判 |
| Delivery queue | `advance_utterance` 直接 queue.pop + history.append；one-shot drain 也直接写 history | 当前仍是 Session 局部状态 | P6 必须保住 P4“未播放不算事实”合同，并把 delivery 与 commit 顺序显式化 |

## 4. `step()` 中的场策略热点

### 4.1 龙也序幕 / 咖啡馆

`step()` 直接判断 `prologue_active` 并处理：

- 玩家对托付/挂坠的 disposition；
- PlayerAction→WorldCommit 后 RP4/branch 投影；
- RP2/RP3 证据补齐；
- 挂坠 offer 可见证据；
- opening soft hint、want ladder、flashback beat；
- 输出 repair / entrust / pendant agency guard。

已有较纯的候选函数包括：

- `prologue_receipt_disposition`
- `prologue_pendant_disposition`
- `turns_cover_ryuya_deepen`
- `turns_cover_ryuya_entrust`
- `turns_cover_ryuya_pendant_gift`
- `ryuya_deep_topic_interface`
- `advance_ryuya_prologue_want_now`
- `flashback_return_pendant_look`

P6a 应先把“识别 / 机会 / proposal”迁出；World/Beat/Mind commit 继续由 engine 调现有 owner。不得在迁移时裁 RP4 新正典。

### 4.2 天安门

`step()` 直接处理：

- `tiananmen_player_facts()`；
- scene receipt / branch / observation；
- TM2/TM3 可见证据与完成；
- want/concern 更新；
- video contradiction repair 与 aquarium decision surface。

已有候选纯函数：

- `tiananmen_player_facts`
- `tiananmen_tm2_visible_evidence`
- `ensure_tiananmen_tm3_self_intro`
- `repair_tiananmen_video_contradiction`
- `advance_tiananmen_want_now`

P6a 目标是让 Tiananmen policy 返回 evidence/proposal，而不是自己写 branch/Beat/Mind。

### 4.3 十六中 / C16

`step()` 的 C16 分支最明显地把策略与提交混在一起：

- gate intervention；
- 奶茶接受/拒绝；
- counter encounter diversion；
- inside observer / follow / stay / leave / join；
- actor autonomous consequences；
- 多处同拍直接调用 `_maybe_transition()`。

已有候选纯函数：

- `_c16_subtle_peripheral_watch`
- `_c16_overt_intervention`
- `c16_milktea_disposition`
- `c16_counter_encounter_diversion`
- `c16_shop_follow_disposition`
- `c16_gate_disposition`
- `c16_table_follow_disposition`
- `c16_player_trio_intro_done`

C16 适合作为首个 ScenePolicy 迁移样本：规则集中、分支多、能直接证明“改一场 policy 不影响其它场”。

### 4.4 正典自动段 / 闪回

当前 `start()`、`step()`、`_maybe_transition()` 都可触发 canon segment / flashback：

- `start()` 直接扫描 on_start canon segment 并 emit；
- `step()` 在 actor beat 后可串 canonical performance；
- `_maybe_transition()` 内部处理 Ryuya flashback return、pendant deferred fallback、return frame、cursor/card 切换和 flashback world transaction。

这些规则不能继续留在一个通用 transition executor 中。P6a policy 只给 opportunity/evidence/proposal；P6b engine/ExitPolicy 执行合法 transition/commit。

## 5. `_maybe_transition()` 是 P6 最大的混合点

当前该方法同时做：

1. C16 场专用退出资格；
2. Ryuya prologue handoff / pendant fallback；
3. forced/menu/semantic exit 输入状态；
4. 调 ExitPolicy；
5. EndRun；
6. actor commitment projection 到目标场；
7. consolidated memory；
8. world cursor；
9. scene leave/enter MindReceipt；
10. card_path/card/pending_entry/lifecycle 切换；
11. flashback WorldCommit / observation / pendant look；
12. transition narration 与 placeholder auto-end。

目标形状应拆成：

`ScenePolicy.evaluate(snapshot,input) -> proposal/evidence`
→ `ExitPolicy.decide(snapshot, exit_request)`
→ `TurnEngine.commit(decision/proposals)`
→ `FreeStageSession` 只持 state handle / facade。

ExitPolicy 已在 P1 成为唯一“该不该走”的 decider，P6 不重新发明第二套 exit policy。

## 6. Facade / API 合同现状

`web/server.py` 当前直接实例化 `FreeStageSession`，公开 op：

- `reset`
- `start`
- `skip_scene`
- `stream_hold`
- `advance_utterance`
- `player_say`
- `save_as`
- `delete_session`

`player_say` 调 `session.step()`；`skip_scene` / `advance_utterance` 各走 Session 方法。P6 必须保持这些 outward response 字段与锁语义兼容，不要求 web 层认识具体 ScenePolicy。

`scripts/tests/test_free_stage_session_api.py` 同时比较 one-shot `run_session()` 与增量 Session，并覆盖 save→load。P6 required gate 应把这个合同纳入 replay，而不是只测新类。

## 7. P6 边界分组

### 可以迁出

- 场特化输入分类；
- 场特化 evidence/proposal；
- scene-local opportunity；
- generic TurnEngine 阶段顺序；
- transition execution orchestration；
- delivery commit orchestration。

### 必须复用，不平行复制

- `exit_policy`
- `beat_state`
- `player_action`
- `world_commit` / WorldLedger
- `actor_mind`
- `participation`
- `context_assembly`
- `RuntimeStore` / session domain envelope

### 本轮禁碰

- 正典与任何场卡内容；
- Seed / VOICE；
- run=0；
- ★★★ 挂坠事实粒度；
- 真人 `data/world_truth.db`；
- P2c/P3/P4/P5 已关闭 authority 合同。

## 8. 建议迁移顺序

1. 先落一个无场名的 `ScenePolicy` 输入/输出数据合同，输入只接受冻结快照/值对象，输出只含 evidence/opportunity/proposal。
2. 首迁 C16 policy，保留所有现有结果，通过固定 fixture 做 old-vs-new structure replay。
3. 再迁 Tiananmen、Ryuya prologue、canon/flashback policy。
4. 建 `TurnEngine`，只做 `input→observe→deliberate→floor→enact→resolve→commit→exit→project`，调用现有 owner。
5. `FreeStageSession.step/start/skip_scene/advance_utterance` 降成 facade，web/CLI 不换公开合同。
6. 最后 required gate 同时验：
   - core 不 import 具体 ScenePolicy；
   - policy 不持 mutable Session；
   - policy 无权威 owner mutator；
   - 修改 C16 policy fixture 不改变 Tiananmen/Ryuya projection；
   - normal/opening/repair/autonomous/fallback context finalizer 仍同源；
   - queue/save/API/receipt replay 一致。

## 9. 本次报账

本测绘没有改 runtime、测试、数据库、场卡、Seed/VOICE 或正典；新增事实/人物/剧情 = 0。这里只把现有代码职责分层并登记 P6 迁移顺序。
