# Design Philosophy & Architectural Lessons

> README 给概览，这篇给深度。这里记录的是「为什么这样做而不是那样做」——包括试过然后放弃的路。

---

## 1. 走过的弯路（Failure Archaeology）

以下做法我们试过，然后因为具体原因放弃：

| 试过的做法 | 为什么放弃 |
|---|---|
| 把所有人设塞进一个 System Prompt | 10 轮之后角色开始顺从玩家的一切要求（Sycophancy），性格消失 |
| 让导演 LLM 同时写场景描述和角色台词 | 所有角色的声线变得一模一样——导演的语气污染了每个人 |
| 用"性格温柔""说话嘴毒"等形容词约束语气 | LLM 完全忽略，或者把"嘴毒"理解为骂人。形容词对语言风格没有约束力 |
| 给导演完全开放的出招权（可以安排任何事件） | 导演开始编造原著没有的剧情，无法收束 |
| 用 LLM 判断"这条红线是否被触犯" | 概率模型有一定比例会说"没触犯"——确定性底线不能走概率 |
| 固定开场第一句台词防止偏离 | 每次进场都说同一句话，失去涌现感和真实感 |
| 拆一个独立的"环境 LLM"和"店员 Agent" | 增加了延迟和复杂度，但环境描写和店员薄声本质上是导演同拍的附属输出 |

这些失败直接塑造了现在的架构。

---

## 2. 核心架构决策

### 决策一：角色要活，导演要冷（分离执行与编排）

- **角色环（Actor Loop）**：
  - 角色是独立的认知个体。采用 **Decide → Enact → Reflect** 闭环。
  - **Decide（拍前）**：审视当面局势，评估顶格关切（Want Now / Immediate Concern）与社交边界，决定本拍是发言（Speak）、短接（Backchannel）、侧聊（Side）还是沉默（Pass）。
  - **Enact（拍中）**：在严格隔离的上下文包（ActorPacket）中生成当面台词，严格遵守声纹（Voice Fingerprint）与当前已知事实。
  - **Reflect（拍后）**：产生内心独白（Private Reflection），更新对在场人物的好感、疑虑与未尽意图，回写至私有账本。
- **导演闸（Director Gate）**：
  - 导演定位为**冷酷的世界物理法则与收束反派**。
  - **红线**：**导演绝对不写主卡角色的台词**。试过让导演写——结果所有角色声线同质化。
  - 导演仅拥有**闭集出招权**（`quiet`、`ambient_extra`、`time_pressure`、`admit_extra`、`close_window`）。试过给开放出招权——导演会编造剧情。
  - 经由**四端口流水线**：Resolver 会计（确定性，永不走 LLM）→ 观察 → 闭集出招 → Resolver 裁招 → LLM 只填 Stage/Voice → Resolver 复核 → 留痕。

### 决策二：分层装配本体论（Layered Persona Assembly）

试过把人设塞进单一文本——10 轮后性格消失。于是把角色状态拆成数学正交的层：

$$\text{ActorPacket} = \text{PersonaCore} \cup \text{RelBaseline} \cup \text{ActProfile} \cup \text{KnowledgeSlice} \cup \text{MemoryRecall} \cup \text{WantNow} \cup \text{Affect} \cup \text{SceneOverlay}$$

每一层有不同的变化速度和更新机制：

1. **PersonaCore（不可覆写的人格底色）**：极其精炼的 5-7 句核心认知与行为定式。这层永不变——试过让它随互动演化，角色会在几轮之内被玩家"洗脑"。
2. **RelBaseline（关系基准与边界）**：对各人物的信任阈值、禁忌话题与防备机制。极慢变化。
3. **KnowledgeSlice（知识门控）**：严格依据 $learn\_ch \le current\_ch$ 截断。试过不做门控——NPC 会剧透十章之后的剧情，声称自己"直觉感受到了"。
4. **MemoryRecall（慢环情景记忆）**：结合语义相似度（Cosine）与情绪共振度（Emotion Weight）Top-K 召回。试过纯语义——角色对情绪无关但关键词匹配的事件过度反应。加了情绪维度后，"被背叛"这种记忆会在对方出现时自然涌上来。
5. **WantNow & Affect（即时意图与情绪态）**：每拍由前序交互动态驱动。

### 决策三：对话要像人

多人场对话乱，不是因为「缺文采」，是因为缺约束。下面三条都是先撞上体验异味，再补上的规则（术语只作索引，不是出发点）：

- **单回合单意图**：陌生人初次互动，一句话里不得同时质问身份、索要物品、评价外貌。没有这条时，NPC 会一口气把三件事做完——不像人。
- **双通道话轮流**：
  - **Floor Lane**：正对玩家的主对白气泡，严格出队，打字时挂起（Hold），允许打断（Barge-in）。
  - **Companion Lane**：同伴之间的轻声附和（如"嗯"、"没事吧"），不抢占主对话。没有这个通道时，配角要么完全沉默，要么跟主角一起长篇大论。
- **心想 δ（Thought Delta）**：玩家内心独白在系统内作为独立事件流转，导演可感知但 NPC 物理上听不见。没做隔离时，NPC 会对玩家心里想的东西做出回应——极其违和。

### 决策四：确定性硬闸胜过概率模型

- 核心世界因果通过数据库约束与 Python 断言硬性保证。试过用 LLM 判断红线是否被触犯——它会放行不该放行的操作。角色是否该死这种事不能走概率。
- **Goodhart 护栏**：绝不为了测试变绿而删减 Badcase 样例或放宽阈值。这条规则是在一次差点删掉一个"太难通过"的测试用例时确立的。

---

## 3. Badcase 驱动的能力优化

项目的迭代方法不是"想到一个好功能然后加上去"，而是 **"在人验中发现体验异味 → 形式化建模 → 归因到架构层 → 写回归测试 → 修机制"**：

| 现象 (Badcase) | 根因归因 | 架构级解决方案 | 回归测试 |
|---|---|---|---|
| **NPC 反复自我介绍**：托付请求说了三次仍当第一次 | 事实检测依赖"双全名"匹配；`extend` 在查询前执行，写入时机先于去重 | `solidified_facts` + 半截谓词检测 + `no_reannounce` | `test_solidified_facts_packet` |
| **开场每次都是同一句话** | 固定 Authored 模板牺牲了涌现 | 角色包驱动即兴生成（Temperature 0.75 + Voice 声纹约束） | `test_llm_opening_not_authored_rain` |
| **三个 NPC 轮流长篇大论** | 无话轮竞价、无主次位判定 | `MAX_BID_SPEAKERS=1` + Companion 侧聊分流 | `test_dual_lane_companion` |
| **NPC 能读到玩家内心** | 上下文组装混入 Thought | `thought_delta` 物理通道隔离 | `test_utterance_stream` |
| **所有角色口吻一样、AI 味浓** | Prompt 仅给"温柔/嘴毒"等形容词 | 原著行号锚定声纹语料库（VOICE Fingerprint） | `verify_persona_parity` |

---

## 4. 可观测性与工程纪律

1. **10 步深检观测台（`web/observer.html`）**：
   - 实时呈现每拍内部流转：稳定前缀 → 动态包体积 → Decide 意图 → Voice 声纹 → Reflect 回写 → 固化事实覆盖 → 导演四端口 Trace。
   - 这个观测台不是后加的调试工具——它是和系统一起长出来的。每次抓到 Badcase，第一步是确认观测台能不能看见它。
2. **零成本自动化心跳（`python scripts/verify.py --quick`）**：
   - 本地心跳自检（`verify.py --quick`）必须全绿才允许提交。
   - 规则是**验证先行**：要加任何能力，先在 `verify.py` 里加一个验证器，再写实现。
3. **内容三铁律**：
   - **不许编**——入库内容必须出自原著，带精确行号；
   - **可审**——任何设定迁移必须经过 diff 预览与人裁；
   - **报账**——每轮迭代单列"哪里是 AI 编的"，目标零编造。
