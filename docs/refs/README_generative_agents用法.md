# Generative Agents 本地参考（填东西用）

> **位置**：`docs/refs/generative_agents/`  
> **来源**：https://github.com/joonspk-research/generative_agents  
> **性质**：外部参考，**未接入**本仓 `free_stage` / `world_truth.db`。用来抄架构、填角色种子、对照「感知→记忆→反思→计划→行动」。

## 我们下了什么

Windows 路径限制，**只稀疏拉取认知核心**，没下整包 RPG 地图素材（`environment/` 超大且路径过长）：

| 路径 | 用途 |
|---|---|
| `reverie/backend_server/persona/cognitive_modules/` | **核心**：`perceive` / `retrieve` / `reflect` / `plan` / `execute` / `converse` |
| `reverie/backend_server/persona/memory_structures/` | 联想记忆、scratch（工作记忆）、空间记忆 |
| `reverie/backend_server/persona/prompt_template/` | 规划/反思等 prompt 模板（可对照改写成我们的 ActorPacket） |
| `README.md` / `requirements.txt` | 官方说明与依赖 |

完整跑 Smallville 可视化还需要 `environment/frontend_server`（未下）。**填角色、读决策环，本目录足够。**

## 你们要「填东西」看哪

官方角色种子一般在完整仓的：

`environment/frontend_server/storage/<sim名>/personas/<角色名>/bootstrap_memory/`

本稀疏副本**没有**这些 storage 样例。填法两条路：

1. **对照代码填到我们库**：把「日常计划 / 反思 / 记忆流」字段映射到 `slow_memory` + `want_now` + 未来 reflection 表（推荐，不跑他们的 Django）。
2. **要跑官方 demo**：另开目录完整 clone（先开 Windows 长路径），再按官方 README 写 `utils.py`（API key）。

## 和我们项目的对应（抄思路用）

| Generative Agents | 我们现有 / 该补 |
|---|---|
| associative memory + retrieve | `slow_memory` + cue∪cos+emo |
| reflect | **缺**（高 salience 后写回一句私有结论） |
| plan / daily schedule | 场卡 `want_now`（偏场面）；缺长线自更新 |
| execute / converse | `call_actor_packet` + `ActorDecision` |
| scratch | session 工作记忆 / BodyFrame |

## Git

本目录已加入 `.gitignore`（第三方整仓不进主线）。需要版本化时再单独决定。
