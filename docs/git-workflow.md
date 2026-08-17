# GIT 工作流 —— 分支 / 合并 / 文件落位规范

> 给**人**和 **Agent** 同一份真相:代码怎么进库、分支怎么开、新文件放哪。
> 写法对齐 loop 精神:每条规则尽量「机器可验证 + 有降级」。
> 与 `world_truth.db` 冲突的表述,以库为准。本文只管「git 与文件落位」,不碰剧情真值。

---

## 0. 一分钟心智模型(给不熟 git 的人)

- **commit(提交)** = 存档点。每个 loop 收尾压一个干净存档。
- **branch(分支)** = 一条独立的存档线,改坏了不影响 `main`。
- **merge(合并)** = 把两条线系在一起,**保留分叉历史**(真实、安全,但线多会乱)。
- **rebase(变基)** = 把自己的提交"搬到最新 main 后面重新落地",**历史变一条直线**(干净,但**改写了提交**)。
- **worktree** = 同一个仓库、同时签出多条分支到不同文件夹,**多 Agent 并行互不踩**。

**merge vs rebase 一句话**:rebase 让历史好看(整理自己还没分享的提交),merge 让历史真实(合并大家共享的东西)。

---

## 1. 红线(违反则停)

1. **`main` 永远绿灯**:只有 `python scripts/verify.py --quick` 🟢 才能合入。CI(`.github/workflows/verify.yml`)与 pre-commit 双重把关。
2. **`main` 绝不 rebase**,绝不 force-push `main`。rebase 只用于「自己本地、还没 push、还没人用」的分支。
3. **特性分支合回 `main` 用 squash merge**:一个 loop 压成一笔,main 历史保持线性、一 loop 一提交。
4. **不入库的东西就是不入库**(见第 4 节落位表):编译产物 `__pycache__/*.pyc`、运行态 `web/states/`、`scene_log.jsonl`、`config.json`、`scratch/` 一律 gitignore。
5. **行尾统一 LF**:仓库有 `.gitattributes`(`* text=auto eol=lf`)。新机器/新文件不准把行尾翻成 CRLF 制造假改动。
6. **db 入库策略以本文第 5 节为准**,改策略属 ★★★,需人裁决。

---

**远程唯一地址**：`https://github.com/killbynothing/causal-anew.git`（`origin`）。之后都 push 这里。

提交标题给 GitHub 目录页看：`feat|fix|docs|chore: 短句`。不要把 loop 名、场次黑话、一长串「×」写进标题。细节放正文。

## 2. 分支模型(轻量,不用 git-flow)

| 分支 | 用途 | 命名 |
|---|---|---|
| `main` | 唯一长期分支,永远可跑(绿灯) | `main` |
| 特性分支 | 一个 loop / 一个并行 Agent 一条,短命,合完即删 | `loop/<代号>-<简述>`,如 `loop/a1-节点量产`、`loop/b-数字人pipeline` |

**单 Agent / 当前主线(Loop B)**:可直接在 `main` 上小步提交,保持绿灯即可——不强制开分支。
**多 Agent 并行(Loop A1)**:必须开分支 + worktree(下节)。

---

## 3. 多 Agent 并行 = worktree(对应 CLAUDE.md「上 worktree」)

```bash
# 为两个并行 loop 各开一个独立工作树(物理隔离,互不踩文件)
git worktree add ../eu-loop-a1 -b loop/a1-节点量产
git worktree add ../eu-loop-b  -b loop/b-数字人pipeline

git worktree list      # 查看所有工作树
git worktree remove ../eu-loop-a1   # 合并完清理
```

每个 Agent 在自己的 worktree 里干活 → 跑 `verify.py --quick` 绿 → 合回 main(squash)。
**做/验分开**:写代码的 Agent 不自评;合入前由另一 Agent 或脚本验。

---

## 4. 文件落位规范(让 Agent 知道「新东西放哪」)

> 默认原则:**根目录只放规则与总纲,过程性内容一律进 `docs/`。** 新建文件前先对照此表。

| 这是什么 | 放哪 | 入库? |
|---|---|---|
| 全局规则/红线/路由 | `AGENTS.md`（唯一规则源）+ `CLAUDE.md`（兼容入口，只指向前者） | ✅ |
| 当前真相 / 进度 | `STATUS.md` | ✅ |
| 总纲/SOP(loop总纲、workflow、心跳、本文) | 根目录 | ✅ |
| 计划 / 设计稿 / 诊断 / 思路过程 | `docs/plans/`,命名 `YYYY-MM-DD_主题.md` | ✅ |
| 架构仲裁文档 | `design/` | ✅ |
| 对话记录 / 临时草稿(`对话*.txt` 之类) | `docs/对话归档/`,或若纯临时 → `scratch/`(不入库) | 视情况 |
| 代码:运行时 | `runtime/` | ✅ |
| 代码:脚本/验证器 | `scripts/`(验证器进 `verify.py`) | ✅ |
| 代码:Web 控制台 | `web/`(但 `states/`、`*.jsonl` 不入库) | 部分 |
| 节点契约 | `contracts/*.yaml` | ✅ |
| 角色圣经(库的投影,勿手改) | `characters/` | ✅ |
| 生成的事件卡 | `obsidian_events/` | ✅(纯生成,改库后重渲染) |
| 真值库 | `data/world_truth.db` | 见第 5 节 |
| 编译产物 / 运行态 / 密钥 | `__pycache__/`、`states/`、`scene_log.jsonl`、`config.json`、`scratch/` | ❌ gitignore |

**Loop 落位铁律**:不确定放哪 → 先看本表 → 还不确定 → 进 `docs/` 并在 PR/提交说明里说一句,不要堆根目录。

---

## 5. world_truth.db 入库策略（已决策:选 A Git LFS）

**2026-06-21 裁决**:验证了选项 B（重建确定性）,`import_db.py` 单独跑后 events/propositions/node_contracts 行数不一致,重建不确定,退回选项 A。`world_truth.db` 已通过 `.gitattributes` 配置为 LFS 跟踪。

- **A. Git LFS ✅（当前）** —— db 仍版本化,走 LFS,主历史不膨胀。协作者需安装 `git-lfs`。
- **B. 当可重建产物,不入库** —— 前提是 `import_db.py` + 全部 transcribe 脚本能确定性重建完整 db（含 events/propositions/node_contracts）,当前不满足。
- **C. 维持现状** —— 已放弃,`.git` 两天涨 12M。

> 改策略属 ★★★,需人裁决。若日后补全重建脚本可切换到 B。

---

## 6. 标准动作速查

```bash
# 开一个 loop 分支
git switch -c loop/a1-节点量产

# 干活,小步提交(提交信息: 类型(范围): 说明)
git add -A && git commit -m "feat(node): ..."

# 合回 main 前:必须绿
python scripts/verify.py --quick

# 整理自己还没 push 的零散提交(可选,只对本地分支)
git rebase -i main

# 合回 main(压成一笔)
git switch main && git merge --squash loop/a1-节点量产 && git commit
git branch -d loop/a1-节点量产
```

**提交信息约定**(沿用现有历史风格):`feat / fix / docs / test / chore(范围): 说明`。

---

## 验证清单

- [ ] `main` 上 `python scripts/verify.py --quick` 🟢
- [ ] `git ls-files | grep -c '\.pyc$'` == 0
- [ ] `git status -s | wc -l` 无 CRLF 假改动(`.gitattributes` 生效)
- [ ] 新建文件位置符合第 4 节落位表
