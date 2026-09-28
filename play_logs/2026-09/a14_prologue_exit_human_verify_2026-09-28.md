# a14 人验 · 龙也咖啡馆 RP4 后自由继续 · 2026-09-28

## 现场

- Session：`a14`
- 入口：`pline_ryuya_cafe`
- 模型：DeepSeek 官方 `deepseek-flash`
- 目的：验证刀 6 语义节奏、RP 完成后的自由交互、EndRun 边界。

## 实抓红灯 1：假断线

首轮在序幕收束处出现前端“断线”。server traceback 实际为：

`ValueError: prologue handoff requires an approved pending entry`

原因：独立序幕错误走了 `target_pending_entry`，但该局本来没有 approved `pending_entry`。前端旧逻辑又把后端 HTTP 500 的正文吞掉，只显示“链接失败”。

修复：
- 前端展示后端真实错误正文；
- server 调试日志落 `scratch/server_live.log`；
- 默认/实验 API 基线切到 DeepSeek 官方 `deepseek-flash`。

## 实抓红灯 2：RP 齐被误判成场结束

第一刀止血后，`a14` 在第 5 拍 RP4 出现后立刻插入：

`<<< 本场结束 >>>`

并把 session 写成 `ended=true`。这说明实现错误地把“must-happen 已完成”当成“玩家已经离场”。

现场最后可见事实：
- RP1–RP4 均已完成；
- 龙也刚把古铜色挂坠推到玩家面前；
- 玩家没有公开表达离场；
- 但系统自动 EndRun，导致无法继续聊天。

正确合同：
- **RP1–RP4 齐只解锁离场，不自动结束。**
- RP4 后玩家继续聊天时：`pace=neutral`，ActorCogLoop 顶 concern=`post_entrust_chat`。
- 角色应回到朋友之间的当下，顺着玩家话题继续，不复读托付、不主动催离。
- 只有玩家公开说/做出离场意图（如“先走”“回头见”）时，才 `pace=close` + farewell + EndRun。
- 真正从正戏触发的闪回仍允许按 `ryuya_flashback_return` 自动回正戏。

## a14 恢复

错误关局已落到 run=1。遵守 append-only，不删除历史回执。

恢复方式：
- 保留 run=1 错误回执作为审计证据；
- 新增 run=2：
  - `kind=fork`
  - `parent_run=1`
  - `fork_event=bug_recovery:premature_prologue_end:a14:run1`
- 原对话历史、RP1–RP4 保留；
- 只撤销错误自动生成的结束 marker、`prologue_receipt_deferred` 与对应错误挂坠 deferred transaction；
- 服务端复查：`ended=false`，可继续游玩。

## 机器验

新增/调整回归：
- RP4 后“再陪我聊会儿”不得 EndRun；
- RP4 后“我先走了，回头见”才允许正常收束；
- RP4 后非告别语义 => `pace=neutral`；
- RP4 后告别语义 => `pace=close`；
- ActorCogLoop 非告别 => `post_entrust_chat`，告别 => `farewell`。

`python scripts/verify.py --quick`：

**38 PASS / 0 FAIL / 165 SKIP**

## 实抓红灯 3：托付 / 挂坠节拍过紧

继续 `a14` 后进一步确认，之前的节拍不是单纯“体感快”，而是三处机械推进叠加：

- RP2 证据曾允许“闲聊拍数达到阈值”直接算谈话已转正事；
- RP3 的旧证据把 stage 动作文本也并进托付判断，存在“没说出口也算说了”的可能；
- RP4 旧逻辑只要挂坠动作命中，就可能直接算交付，且把托付回应与物件接受混在同一个 disposition。

现场关键证据：
- 第 10 拍龙也第一次真正说清：“不是让你替我保管。是给你的。”，挂坠仍停在两人之间；
- 第 11 拍玩家只说“想再见见你总要有个借口吧”，并没有明确收下；
- 旧逻辑却让龙也把挂坠直接塞进玩家手心，并自动关场。

新合同：
1. **RP2**：只认可见语义转向（如“有件事想说/临走前有事”或玩家主动打开认真话题）；拍数本身不是证据。
2. **RP3**：只认龙也真正说出口的可听台词，必须覆盖张尘、折原修哉、照顾/照应、禁名危险；stage 不得冒充口头托付。
3. **RP4**：拆成两拍语义：
   - 龙也明确口头说明“这枚挂坠是给你的/临别礼物”，并把物件递到玩家这边，只记 `prologue_pendant_offered`；
   - 等玩家下一拍明确收下、拒绝或暂放，才结算 `ryuya_pendant_disposition` 并完成 RP4。
4. 玩家未明确表态时，运行时硬闸会修复“塞进手心/替你戴上”等代替玩家决定的动作。

## a14 二次恢复与重放

- run=2 的错误关局保留审计；
- run=2 产生的一条错误 `delta_sediment` scar 使用既有 `revoked=1` 标记作废，没有删除历史；
- 新增 run=3：
  - `kind=fork`
  - `parent_run=2`
  - `fork_event=bug_recovery:pendant_two_step:a14:run2`
- 恢复点：第 10 拍之后，RP1–RP3 完成，`prologue_pendant_offered` 成立，RP4 未完成。

用玩家原第 11 句“想再见见你总要有个借口吧”原样重放：
- `ended=false`
- completed 仍为 RP1–RP3
- 无挂坠 world transaction
- 龙也只把挂坠往玩家这边又推半寸，停在那里看玩家
- 没有强塞，没有自动结束

## 机器验（更新）

新增/调整回归：
- 高拍数不能自动完成 RP2，也不能自动把 ActorCogLoop 推到 entrust；
- stage 写满托付内容也不能冒充口头 RP3；
- 挂坠 action-only / words-only 都不能建立完整 offer，必须口头赠与 + 可见递出；
- 玩家未明确处分挂坠时，强塞/代戴动作必须被修复；
- RP4 后仍只有玩家明确离场才结束。

`python scripts/verify.py --quick`：

**38 PASS / 0 FAIL / 165 SKIP**

## 下一步人验

继续 `a14` 当前 run=3。重点观察：
1. 你收 / 拒 / 暂放挂坠时，龙也是否自然承接而不抢决定；
2. 不回应挂坠、继续聊别的时，他是否能等，不重复递、不催；
3. 托付完成后是否仍像朋友聊天，而不是“任务节点已完成”的收尾腔；
4. 你明确离场后才结束，然后再开下一新周目验环境疤与角色零跨周目知情。
