#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "world_truth.db"
SQL_PATH = ROOT / "data" / "world_truth.sql"
REPORT_PATH = ROOT / "docs" / "refs" / "Z1b_world_truth_sql_rebuild_report_2026-07-08.md"
MUTABLE_TABLES = {"run_bonds"}


def dump_database(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        lines = [
            "-- world_truth.db canonical SQL dump",
            f"-- generated_at_utc: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "-- source: data/world_truth.db",
            "PRAGMA foreign_keys=OFF;",
            "BEGIN TRANSACTION;",
        ]
        for line in conn.iterdump():
            if line in {"BEGIN TRANSACTION;", "COMMIT;"}:
                continue
            if any(line.startswith(f'INSERT INTO "{table}"') for table in MUTABLE_TABLES):
                continue
            lines.append(line)
        lines.append("COMMIT;")
        return "\n".join(lines) + "\n"
    finally:
        conn.close()


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def table_fingerprint(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    columns = table_columns(conn, table)
    quoted_cols = ", ".join(f'"{col}"' for col in columns)
    order_cols = quoted_cols or "rowid"
    rows = conn.execute(f'SELECT {quoted_cols} FROM "{table}" ORDER BY {order_cols}').fetchall()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(list(row), ensure_ascii=False, sort_keys=False, default=str).encode("utf-8"))
        digest.update(b"\n")
    return {"rows": len(rows), "sha256": digest.hexdigest()}


def database_fingerprint(db_path: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            table: table_fingerprint(conn, table)
            for table in table_names(conn)
            if table not in MUTABLE_TABLES
        }
    finally:
        conn.close()


def rebuild_from_sql(sql_text: str, rebuilt_path: Path) -> None:
    conn = sqlite3.connect(str(rebuilt_path))
    try:
        conn.executescript(sql_text)
        conn.commit()
    finally:
        conn.close()


def run_mech_invariants(db_path: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mech_invariant_suite.py"), "--db", str(db_path)],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout


def build_report(original: dict[str, Any], rebuilt: dict[str, Any], mech_code: int, mech_output: str) -> str:
    original_tables = set(original)
    rebuilt_tables = set(rebuilt)
    table_mismatches = []
    for table in sorted(original_tables | rebuilt_tables):
        if original.get(table) != rebuilt.get(table):
            table_mismatches.append(table)
    ok = not table_mismatches and mech_code == 0
    lines = [
        "# Z1b world_truth.sql 重建差异报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}",
        f"- 源库：`data/world_truth.db`",
        f"- SQL dump：`data/world_truth.sql`",
        f"- 表数量：原库 {len(original)} / 重建 {len(rebuilt)}",
        f"- 排除的运行态可变表：`{', '.join(sorted(MUTABLE_TABLES))}`",
        f"- 结论：**{'PASS' if ok else 'FAIL'}**",
        "",
        "## 差异摘要",
        "",
    ]
    if table_mismatches:
        lines.extend(f"- `{table}` 指纹不一致：原库 `{original.get(table)}` / 重建 `{rebuilt.get(table)}`" for table in table_mismatches)
    else:
        lines.append("- 静态真值表级 row count + ordered row sha256 全部一致。")
    lines.extend(
        [
            "",
            "## 四支柱重建库验证",
            "",
            f"- exit_code：{mech_code}",
            "",
            "```text",
            mech_output.strip()[-4000:],
            "```",
            "",
            "## 待人裁边界",
            "",
            "- 本报告证明 SQL dump 可重建当前静态真值表并通过四支柱断言。",
            "- `run_bonds` 为运行态/玩家态可变表，不纳入静态真值零差异口径。",
            "- 是否让 `data/world_truth.db` 退出 git 跟踪，仍需 D2② 人裁后另行执行。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump world_truth.db to SQL and verify rebuild parity")
    parser.add_argument("--write-dump", action="store_true", help="write data/world_truth.sql before verifying")
    parser.add_argument("--report", default=str(REPORT_PATH), help="markdown report path")
    parser.add_argument("--no-report", action="store_true", help="do not write the markdown report")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[FAIL] missing {DB_PATH}")
        return 1

    sql_text = dump_database(DB_PATH)
    if args.write_dump:
        SQL_PATH.write_text(sql_text, encoding="utf-8")
        print(f"[OK] wrote {SQL_PATH}")
    elif SQL_PATH.exists():
        sql_text = SQL_PATH.read_text(encoding="utf-8")
    else:
        print(f"[FAIL] missing {SQL_PATH}; run with --write-dump first")
        return 1

    original_fp = database_fingerprint(DB_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        rebuilt_path = Path(tmp) / "world_truth_rebuilt.db"
        rebuild_from_sql(sql_text, rebuilt_path)
        rebuilt_fp = database_fingerprint(rebuilt_path)
        mech_code, mech_output = run_mech_invariants(rebuilt_path)

    if not args.no_report:
        report = build_report(original_fp, rebuilt_fp, mech_code, mech_output)
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"[OK] wrote {report_path}")

    mismatches = [table for table in sorted(set(original_fp) | set(rebuilt_fp)) if original_fp.get(table) != rebuilt_fp.get(table)]
    if mismatches:
        print(f"[FAIL] rebuild mismatches: {mismatches}")
        return 1
    if mech_code != 0:
        print("[FAIL] rebuilt db failed mech invariant suite")
        return 1
    print("[OK] world_truth.sql rebuild matches current db and passes mech invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
