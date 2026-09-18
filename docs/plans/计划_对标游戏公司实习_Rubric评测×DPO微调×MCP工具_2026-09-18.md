# 计划 —— 对标游戏公司实习 · Rubric评测 × DPO微调 × MCP工具（2026-09-18）

> **状态**：**过期**。保留作初稿证据，不执行。现行稿：`计划_对标游戏公司实习_Rubric评测×工具契约×对齐旁路_2026-09-18.md`（砍 MCP；DPO 只旁路；评测维对齐 JD）。
> **归属**：专项落地计划初稿（对标头部游戏公司 AI Agent / 智能 NPC 核心算法与工程岗位）。
> **索引**：登记于 `docs/plans/INDEX.md`（过期）。
> **原则**：坚守 `AGENTS.md` 红线：不污染 `world_truth.db` 既有正典事实；`verify.py --quick` 恒绿；机制与算法升级服务于系统真实存在度。

---

## 1. 目标与价值对齐

| 岗位职责 (JD) | 实施模块 | 交付产物与量化证明 |
|---|---|---|
| **评测体系与实验分析 (Agent Eval)** | **模块一：Narrative Rubric Agent Eval 混合评测套件** | `scripts/eval_narrative_rubric.py`<br>硬指标（剧透率/因果违背/节奏）+ 软指标（OOC/潜台词/推进）定量报告与雷达图 |
| **训练与对齐优化、数据闭环** | **模块二：NPC 认知对齐 SFT/DPO 数据飞轮与训练管线** | `scripts/pipeline/build_sft_dpo_data.py`<br>`training/train_dpo_align.py`<br>基于真实真值库提取高质量对齐样本，完成 DPO 偏好对齐训练代码 |
| **工具调用、环境交互与前沿探索** | **模块三：标准 Tool Use 与 MCP (Model Context Protocol) 适配** | `runtime/mcp/npc_mcp_server.py`<br>将情景记忆检索、场景物态感知、社交意图发布封装为标准 MCP 工具 |
| **工程落地、开源门面与面试竞争力** | **模块四：架构基准报告与简历 STAR 精修** | 工业级架构大图、消融对比 Benchmark 数据、简历直投手册 |

---

## 2. 实施细节（四阶段）

### 阶段一：落地 Narrative Rubric Agent Eval 自动化评测体系
- **目标**：解决评测“全凭主观感觉”的痛点，构建自动化打分雷达。
- **文件**：`scripts/eval_narrative_rubric.py`
- **内容**：
  1. **硬指标（Rule-based Deterministic）**：
     - `Spoiler / Premise Leak Rate`：是否跨越 `available_ch` 泄密（结合现有 `spoiler_defense`）。
     - `Pacing & Token Compliance`：单句台词字数分布（如 ≤45 字），标点断句节奏。
     - `Repetition & Knot Penalty`：多轮对话中的机械复读与死循环抑制率。
  2. **软指标（LLM-as-a-Judge Rubric 1-5分制）**：
     - `Persona Consistency`（角色性格与口吻稳定性，防 OOC）。
     - `Subtext Density`（潜台词深度，先想后说 Decide 与台词 Enact 的张力）。
     - `Causal Convergence`（叙事推进合理性与因果收敛效率）。
  3. 支持 `--smoke` 快速回归（免 API / GPU，CI 绿灯）与全量评测输出 Markdown/JSON 报告。
- **接入**：接入 `scripts/verify.py` 自动化测试清单。

### 阶段二：补齐算法闭环 —— SFT / DPO 数据生成与模型对齐管线
- **目标**：证明具备从真实游戏业务场景提炼数据并完成模型对齐的算法能力。
- **文件**：`scripts/pipeline/build_sft_dpo_data.py` 与 `training/train_dpo_align.py`
- **内容**：
  1. **数据提取流水线**：从 `world_truth.db` 原著声纹（`P.VOICE`）、经历（`slow_memory`）及 `play_logs/` 轨迹提取样本。
  2. **结构化构建**：
     - SFT：`{system, history, thought(Decide), response(Enact)}`（先想后说）。
     - DPO：构造针对性偏好对（`chosen`: 潜台词丰富、语气对味、遵守知识门控；`rejected`: OOC 客服腔、长篇说教、未卜先知剧透）。
  3. **微调脚本**：基于 Hugging Face `trl.DPOTrainer` / `peft`，针对 Qwen2.5-3B/7B 编写标准训练与 Dry-run 验证逻辑。

### 阶段三：工业界前沿接口 —— 标准 Tool Use 与 MCP 适配
- **目标**：对齐 2024-2026 年行业最主流的 MCP 标准与 Agent 工具调用规范。
- **文件**：`runtime/mcp/npc_mcp_server.py`
- **内容**：
  1. 将核心接口封装为符合 Anthropic MCP 协议的 Tool：
     - `query_episodic_memory`（时序因果受限的情景记忆检索）
     - `inspect_scene_affordance`（场景物态与可见交互点）
     - `submit_actor_intent`（提交社交话轮意图）
  2. 编写单元测试 `scripts/tests/test_mcp_server.py` 验证 Schema 合法性与端到端调用。

### 阶段四：工程门面与简历包装
- **目标**：让招聘方一分钟看懂项目深度与竞争力。
- **内容**：
  1. `README.md` 顶部定位与双层架构大图升级，嵌入 Benchmark 评测对比表。
  2. 撰写 `docs/experience/实习直投_项目亮点与面试攻防手册.md`（含简历 4 栏精修 Bullet Points、高频技术提问应答）。

---

## 3. 验收标准 (Verification & DoD)

1. `python scripts/verify.py --quick` 保持全绿（不破坏任何现有测试）。
2. `python scripts/eval_narrative_rubric.py --smoke` 秒级通过并输出合规性评分雷达。
3. `python scripts/pipeline/build_sft_dpo_data.py` 成功生成标准 `sft_dataset.jsonl` 与 `dpo_dataset.jsonl`。
4. `python training/train_dpo_align.py --dry-run` 数据流与前向自检通过。
5. MCP 工具接口自测试 100% 通过。
