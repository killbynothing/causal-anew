# WORKFLOW —— 新仓每日怎么干（2026-08-03）

> 状态看 `STATUS.md`；规则看 `AGENTS.md`；排期看 `docs/plans/长期路线图_2026-08-03.md`。
> 本文只回答：坐下来按什么顺序、用什么命令。

---

## 1. 开工

1. 读 `STATUS.md` 最上条（当前真相）。
2. 读长期路线图当前阶段「做什么 / 你验什么」。
3. 不确定文件放哪 → `AGENTS.md` 落位表。

## 2. 干活

- 一个 loop 一件事；先写/挂验证器，再实现。
- 动库只走 `scripts/import_db.py` 迁移管线。
- 内容草案标 ★★★，人过目才入库。

## 3. 收尾四件套

1. `python scripts/verify.py --quick` 绿  
2. 报账（哪里是编的；目标=零）  
3. 更新 `STATUS.md`  
4. 计划文档同步（INDEX 已登记的才算存在）

## 4. 常用命令

```bash
python scripts/verify.py --quick
python scripts/mech_invariant_suite.py --db data/world_truth.db
python runtime/npc_test_client.py fsm-sim --db data/world_truth.db
```

## 5. 旧仓

旧仓桌面目录名：`令人充满希望的进行啊`（封存只读，路径见双根工作区）。Demo 在新仓未绿前可回旧仓玩。
