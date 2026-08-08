# 介绍：若采用 Generative Agents 认知环 · 整体怎么构造 · 2026-08-08

> **性质**：架构介绍（非排期、非入库）。回答三问：它是不是 agent？和我们兼不兼容？若用，库/导演/角色怎么拼。  
> **参考代码**：`docs/refs/generative_agents/reverie/...`（稀疏拉取的认知核心）  
> **上位宪法**：装配备忘 · 三层分工 · 社交参与备忘 · AGENTS 红线  
> **结论先行**：**抄认知环，不整仓替换。** 它是「小镇生活模拟 agent」；我们是「正典叙事游戏 + 数字人」。兼容在概念层，不兼容在代码层。

---

## 0. 它是不是 agent？

**是。** 官方 `Persona` 类注释写明：这就是 GenerativeAgent。每拍主循环（`persona.move`）：

```text
perceive → retrieve → plan → reflect → execute
```

| 模块 | 干什么 |
|---|---|
| perceive | 看见周围事件（带宽/保留） |
| retrieve | 按近因×相关×重要捞记忆 |
| plan | 日计划 → 小时分解 → 当下行动 |
| reflect | 重要性攒够了，合成更高层「想法」写回记忆 |
| execute / converse | 落到格子移动或对话 |

所以它不是「更好的台词模型」，而是**带记忆与目标的决策 agent**。

---

## 1. 兼容性验证（能不能「直接用」）

### 1.1 概念层：高度同构（该用）

| Generative Agents | 我们已有 / 已设计 | 兼容？ |
|---|---|---|
| associative memory（事件+想法流） | `slow_memory` + run 固结 | ✅ 同构 |
| retrieve(recency×relevance×importance) | cue∪cos+emo Top-K | ✅ 可对齐权重 |
| scratch（短时身份/计划/当前行动） | session：`want_now` / BodyFrame / working | ✅ 部分已有 |
| innate / learned / currently | `P.ARCH/MANNER` / K.* / 场内状态 | ✅ 分层一致 |
| reflect → 写回 thought | **缺**（最大缺口） | 🟡 该补 |
| plan → daily/hourly | 场卡 `want_now` / open concerns | 🟡 该改成角色自推 |
| ActorDecision 四形态 | 社交参与备忘已定 | ✅ 比他们更贴叙事 |
| 双意识 / 知识门控 / never_soften | 我们独有 | ❌ 他们没有，必须我们保留 |

### 1.2 代码层：不兼容（勿整仓嵌入）

| 他们的假设 | 我们的硬约束 | 冲突 |
|---|---|---|
| 2D maze 格子 + 日程小镇 | 场卡 / Storylet + 导演脊柱 | 世界模型不同 |
| 无「正典红线」，自由沙盒 | `never_soften` / 四支柱 / 禁旁白硬拽 | 必须外挂闸 |
| 单一人格 JSON（innate/learned） | 双意识 `C.ryuya.W1/WMAIN` + fronting | 身份模型更复杂 |
| 无导演；角色即世界 | **导演 ≠ 演员**；MH=收据不派戏 | 调用关系相反 |
| OpenAI `utils.py` + Django 前端 | `free_stage` + `world_truth.db` | 栈不同 |
| 每日睡醒重规划 | 叙事拍/场景拍，不是仿真日 | 时间粒度不同 |

**判定**：  
- ❌ 不要 `import` 他们的 `Persona` 当运行时主类。  
- ✅ 把 `move` 五步收成我们的 **ActorCogLoop**，数据读写全部走我们的库与 session。

---

## 2. 推荐整体构造（一张图）

```text
                    ┌──────────── 世界真值 ────────────┐
                    │  world_truth.db (run=0 只读)      │
                    │  P.* REL.* K.* slow_memory        │
                    │  events / causal_web / 固定底     │
                    └───────────────┬──────────────────┘
                                    │ 投影（只读装配）
                                    ▼
┌───────────── 场包装（卡 / Storylet）─────────────┐
│ 在场 cons · 入口钩 · 知识闸 · 离场 · 薄覆盖      │
│ MH = 收据槽（不写「谁必须说啥」）                │
└───────────────────────┬─────────────────────────┘
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
   【导演 Agent】  【角色 Agent×N】  【世界结算】
   环境/物态/压力   ActorCogLoop      合法动作落地
   红线闸/收场      每人独立          receipt→记忆
   不写台词         Decide→Enact→Voice
         │              │              │
         └──────────────┴──────────────┘
                        │
                        ▼
                 玩家可见层（气泡/stage）
```

**一句话**：Generative Agents 只替换/强化中间的「角色 Agent」认知环；库、导演、卡、红线仍是我们的。

---

## 3. 库的内容怎么投影进 agent

投影原则：**Seed 薄常驻 · 记忆检索 · 状态 run 可变**（装配备忘原句）。

| 库资产 | 投影到 agent 哪一槽 | GA 对应 | 注意 |
|---|---|---|---|
| `P.ARCH/MANNER/BOUNDARY` | PersonaCore（常驻） | innate + 部分 learned | 薄；不灌传记 |
| `P.VOICE.*` | VoiceFilter（Enact 后） | （无；他们靠对话样本） | 只锁腔，不锁剧情 |
| `REL.IDENTITY/HOLD` | RelBaseline | currently 里的关系句 | 质地，不写演令 |
| `K.*` ∩ `learn_ch` | KnowledgeSlice | learned 事实 | **门控**；GA 无此闸 |
| `slow_memory` | MemoryStore → retrieve | associative memory | A/B 桶；细剖 events **不进** |
| `P.ACT.*` + BodyFrame | 习惯/身体 | execute 姿态侧 | |
| fronting / occupancy | 选哪个 cons 进环 | （无） | 同一身体只跑前台意识 |
| run 固结 / thought_delta | 本周目记忆流 | 新 event/thought 节点 | 只追加 |

**禁止**：把 `events` 细剖当角色「我记得」；把导演 MH 文案投影进 want。

### 投影伪代码（目标态）

```text
for cons in present_fronting:
  seed = fetch_persona + REL + K(gated) + VOICE
  mem  = retrieve(slow_memory ∪ run_mem, cue=scene+player, top_k)
  scratch = session[cons]  # want, concerns, daily_intent?, body
  packet = assemble(seed, mem, scratch, scene_visible, director_pressure)
  decision = ActorCogLoop(packet)   # 见 §4
```

---

## 4. 角色 Agent：用 GA 环，落我们的输出

### 4.1 ActorCogLoop（每拍、每在场意识）

```text
1. Perceive   可见场面、玩家输入、同伴刚说的、物态变化
2. Retrieve   Top-K 情景 + 相关 K.*（已门控）
3. Decide     → ActorDecision{ mode, intent, concern_id? }
              （speak | backchannel | side | pass）
4. Reflect?   若本拍 salience 高或累计 importance≥阈
              → 写 1 句私有结论进 run 记忆（可晚一拍）
5. Enact      若需说话：内容草稿（跟 intent）
6. Voice      P.VOICE 洗腔（W1/WMAIN 分意识）
7. Emit       stage + text；receipt 回写
```

对比 GA 原版 `plan→execute`：我们把「走到沙发画画」改成「社交参与形态 + 叙事动作」；**日计划**降级为可选的离屏/长线，不当场卡主驱动。

### 4.2 自由从哪来

| 自由 | 约束 |
|---|---|
| Decide 选不选开口、推哪条 concern | BOUNDARY / 知识门控 / never_soften |
| Enact 说什么 | 人格×关系×记忆×intent |
| 声纹 | 只约束怎么说 |

声纹 ≠ 剧本；GA 也不是靠背台词活着的——靠 **计划与反思**。

---

## 5. 导演怎么调用（和 GA 的本质差别）

GA：**没有导演**；每个 Persona 自己就是世界动力。  
我们：**导演 = 反派/世界压力**；演员不掌握脊柱。

| 导演做 | 导演不做 |
|---|---|
| 推进/检查脊柱与固定底 | 指定「下一句谁念什么」 |
| 改环境、物态、合法 affordance | 把 MH 当话轮脚本 |
| 给 **压力/机会**（可见事件） | 覆盖角色 want 成 checklist |
| 收场、转场、红线闸 | 替角色做社交 Decide |

调用序（目标）：

```text
玩家输入
  → 导演：更新世界可见层 + 压力（可选）+ 红线预检
           └─ 同拍可选 ambient（薄层环境/店员）——不另开第二脑
  → 各角色：ActorCogLoop（并行 Decide，串行 speak）
  → 世界结算：动作合法性、物态、MH 收据打勾
  → 记忆回写：观察 / thought_delta / 条件触发 reflect
```

这与社交参与备忘 **P8「导演管世界，演员管嘴」** / **P8.1 同拍 ambient** 一致；GA 只强化「演员管嘴」之前的脑子。

**角色环必须闭环（2026-08-08）**：Reflect 不能只写观测台——`prior_reflect` + `stated_public_facts` 要进下一拍 Decide。否则托付后仍会开环复读。

**明确不做**：把导演职责拆成「环境 Agent + 压力 Agent + 收场 Agent」多次调用——控场必须是同一脑。共史以 soft anchors / Decide 压，不靠无限关键词硬闸。

---

## 6. 场卡 / 脊柱放哪

三层分工不变：

| 层 | 用 GA 之后 |
|---|---|
| ① 脊柱 causal_web | 仍只指导「这场为何存在」；**不**进角色记忆检索 |
| ② 场卡 | 仍包装在场/钩子/闸/离场；`want` 种子可给，**禁止**拍内 checklist |
| ③ 软化 | 与 agent 无关；跨周目后置 |

场卡给角色的应是：**场景事实 + 开放 concern 种子**（例如「临别前还有挂坠未交」），不是「本拍必须交挂坠台词」。

---

## 7. 和现况的差距（兼容改造清单）

| 优先级 | 项 | 说明 |
|---|---|---|
| P0 | Decide 先于台词 | 已有 `ActorDecision`；要保证生成路径必经 |
| P0 | MH 去内容催促 | 收据化（备忘已定，验实机） |
| P1 | Reflect 写回 | 高 salience → 1 句 thought 进 run 记忆 |
| P1 | OpenConcern 顶格 | `want_now`=顶格一条；其余 pending |
| P1 | Voice 第三步 | `P.VOICE` 入库后 Enact→Voice |
| P2 | Retrieve 三维分 | 显式 recency/relevance/importance（可对齐 GA） |
| P2 | 离屏 plan | 非场内日课表；可选「下场前意图」 |
| — | 整仓跑 Smallville | **不做**（路径/栈/叙事模型均不合） |

---

## 8. 明确不做什么

1. 不把 Stanford 仓当运行时依赖 merge 进 `runtime/`。  
2. 不用他们的 maze/Django 驱动开场。  
3. 不让角色 agent 读取细剖 `events` 当自传。  
4. 不因「更自由」关掉知识门控或固定底。  
5. 不训练小模型替代本环——环是编排，模型是工兵。

---

## 9. 一句话收束

**Generative Agents = 成熟的「角色认知 agent」参考实现。**  
我们用它的 **感知→检索→决策→反思→行动** 五步，接在已有 **库投影 × 场卡 × 导演四端口** 上；  
库继续赢，导演继续管世界，角色用这环获得「活人判断」，声纹只负责最后一公里的「像谁」。

若开 loop：目标可写成「ActorCogLoop 必经 Decide；reflect 写回可测；同一序幕关 MH 内容催促后托付仍可由 want 自推」。
