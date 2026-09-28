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

## 下一步人验

继续 `a14`，从“挂坠刚被推到面前”往下自由聊。重点观察：
1. 能否自然继续聊天，不被系统或龙也催散；
2. 龙也是否避免复读张尘/修哉托付；
3. 玩家明确说要走时，才真正结束；
4. 关局后再开下一新周目，验环境疤与角色零跨周目知情。
