# P6 最终人验 · 天安门多人场 · 2026-10-05

> 状态：**PENDING HUMAN RUN**
>
> 本文件是 §14.3 / §16 的真人体验证据模板。不得因为机器 gate 绿色而预填 PASS。

## 现场基线

- 分支：`loop/turn-engine-p6-2026-10-05`
- 当前记录 HEAD：`f075d886c3770c7599887a7b3c1a13e98fbe06f7`
- P6 代码验收基线：`5c0b5ebadca58760105c81162c7095ff90b79ac2`
- Session schema：`free_stage.session.v1`
- 最近机器证据：Quick verification #397 success；P6 代码 gate 基线 #394 success
- Session ID：`<开跑后填写>`
- Run no：`<开跑后填写>`
- Opening / 入口：`<开跑后填写>`
- 模型 / provider：`<开跑后填写>`
- 实际 build SHA：`<开跑时确认；如已变化，不得沿用上面的当前记录 HEAD>`

## 体验原则

这不是关键词命中测试。玩家应自然说话，观察多人参与是否像真实会话，而不是轮流报台词。

重点判断：

- 多人接话是否由公开语境和各自意图产生，Floor 不像点名器；
- 有人可以 pass / side / backchannel，不要求人人每拍发言；
- 未介绍前不得偷知道姓名/身份；
- 玩家公开证明“听得懂日语”等事实后，角色只从可见证据更新，不重复追问；
- 物件/视频等事实状态前后一致；
- 私有 thought 不得改变别人的参与或知识；
- 主动离场由玩家触发，不能被场景节点硬拖走。

## 主路径 · 多人交流到主动离场

至少覆盖：

1. 开场自然交流，观察多人参与与沉默权。
2. 在姓名/身份尚未公开时主动试探，检查知识门控。
3. 自然暴露或确认语言能力，检查后续是否承接而非重复询问。
4. 涉及一个有状态的物件/视频事实，检查提供/没有/已谈妥不会互相矛盾。
5. 制造一个适合 side / backchannel / pass 的时刻，观察 Floor 是否允许非主发言结果。
6. 只写一拍 thought，不说/不做，确认不会被其他角色读取，也不会触发 actor transport。
7. 恢复公开说话，观察 thought-only 拍不会制造虚假剧情事实。
8. 主动表达离场，确认 ExitPolicy 才执行离场。

### 逐拍实录

| turn | 玩家实际输入 | 获得 floor / side / pass 的角色 | 实际可见输出摘要/原文片段 | Knowledge / Mind / World / Exit 关键状态 | 体验 verdict |
|---:|---|---|---|---|---|
| 1 |  |  |  |  |  |
| 2 |  |  |  |  |  |
| 3 |  |  |  |  |  |
| 4 |  |  |  |  |  |
| 5 |  |  |  |  |  |
| 6 |  |  |  |  |  |
| 7 |  |  |  |  |  |
| 8+ |  |  |  |  |  |

### 主路径核对

- [ ] 多人不是机械轮流说话，也没有无权强塞 speaker。
- [ ] 至少出现一次自然 pass / side / backchannel 或明确证明该机会合法存在。
- [ ] 姓名/身份在公开前没有泄漏。
- [ ] 语言能力只在可见证据后生效，生效后不反复询问。
- [ ] 视频/物件状态无前后矛盾。
- [ ] thought-only 拍没有泄给角色，没有 actor transport。
- [ ] 玩家恢复公开输入后，没有把 thought 当成已发生公开事实。
- [ ] 主动离场前场景保持 open，明确离场后才 transition/close。
- [ ] 人物口吻和边界自然，没有“为了过节点而说话”的机械感。

## 跨 run / 固定底

另开新周目或可证明的新 run：

- [ ] 新周目角色不知道上一周目的私密对话/玩家 thought。
- [ ] 允许的世界疤按既有机制存在，但不转化为角色无来源记忆。
- [ ] fixed bottom / never_soften 始终阻挡不可回滚事实被软化。

记录：

- parent / fork（如有）：
- 新 run no：
- 可见疤：
- 角色知情检查：
- 固定底检查：

## 人验后机器对账

人验结束后再核，不在人验前预填：

- build SHA：
- session / run：
- save→load 是否保持结果：
- ParticipationIntent / FloorGrant：
- Observation / Mind receipts：
- World / Beat receipts：
- ExitDecision / lifecycle：
- context receipt / prompt SHA 是否仍同源：
- 是否出现跨 run 私密串包：
- 若失败，归因到哪个 owner / adapter / policy，不在 TurnEngine core 加场名补丁：

## 最终 verdict

- [ ] PASS
- [ ] FAIL
- [ ] BLOCKED（环境/模型/服务问题，不能算体验失败）

结论与理由：

> <真人填写>
