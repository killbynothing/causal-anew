#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_migration.py —— M-1：把 A1 迁移固化进一键刷新管线
用法：
    python apply_migration.py                 # 默认对 ./world_truth.db 应用 ./A1_migration.sql
    python apply_migration.py --db X --sql Y  # 自定义路径
管线接入：在 import_db.py 之后固定追加本脚本（见文末说明）。
幂等性：可重复执行。fronting_canon 的 B5 行在重放前先清理，避免 AUTOINCREMENT 重复插入。
"""
import argparse, sqlite3, sys, os
from db_indexes import ensure_indexes

# 重放前清理项：这些数据会被迁移脚本完整重新插入
PRE_CLEAN = [
    ("fronting_canon", "DELETE FROM fronting_canon WHERE canon_src LIKE '%B5决议%'"),
]

# 迁移后必须成立的后置条件（任一失败即整体回退并报错）
POST_CHECKS = [
    ("fronting_canon 应有 6 条 B5 前台裁决",
     "SELECT COUNT(*) FROM fronting_canon WHERE canon_src LIKE '%B5决议%'", 6),
    ("source_manifest 应有 4 条摄入清单",
     "SELECT COUNT(*) FROM source_manifest", 4),
    ("尘叔 Restart 免疫应为 0.8",
     "SELECT restart_immunity FROM bleed_config WHERE cons_id='C.dust.W1'", 0.8),
    ("occupancy#2 应为 jump_in",
     "SELECT occ_mode FROM occupancy WHERE occ_id=2", "jump_in"),
    ("B5 衍生命题应有 4 条",
     "SELECT COUNT(*) FROM propositions WHERE canon_src LIKE 'B5决议%'", 4),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join("data", "world_truth.db"))
    ap.add_argument("--sql", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "A1_migration.sql"))
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"[FAIL] 找不到数据库：{args.db}")
    if not os.path.exists(args.sql):
        sys.exit(f"[FAIL] 找不到迁移脚本：{args.sql}")

    sql_text = open(args.sql, encoding="utf-8").read()
    db = sqlite3.connect(args.db)
    cur = db.cursor()

    # 1) 幂等预清理（表不存在时跳过）
    for table, stmt in PRE_CLEAN:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass  # 首次执行该表尚不存在
    db.commit()

    # 2) 执行迁移
    try:
        db.executescript(sql_text)
    except Exception as e:
        db.rollback()
        sys.exit(f"[FAIL] 迁移执行失败，已回退：{e}")

    # 3) 后置条件校验
    failed = []
    for name, query, expect in POST_CHECKS:
        got = cur.execute(query).fetchone()
        got = got[0] if got else None
        ok = (abs(got - expect) < 1e-9) if isinstance(expect, float) else (got == expect)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}：{got}")
        if not ok:
            failed.append(name)
    db.close()

    if failed:
        sys.exit(f"[FAIL] {len(failed)} 项后置条件未满足，请勿继续下游任务：{failed}")
    db = sqlite3.connect(args.db)
    ensure_indexes(db)
    db.close()
    print(f"[OK] 迁移应用完成且幂等校验通过：{args.db}")

if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────────────────────
# 管线接入说明（写给维护 import_db.py 的人）：
# 一键刷新顺序改为：
#   python build_corpus.py
#   python extract_*.py（全部）
#   python import_db.py          # 清空重建（只建语料与基础真值）
#   python apply_migration.py    # ★ 新增固定步骤：补齐 v0.9.2 全表 + B5 正典
#   python prepare_a2_samples.py
#   python generate_bibles.py
# 在 apply_migration.py 进入管线之前，禁止单独重跑 import_db.py。
# ─────────────────────────────────────────────────────────────
