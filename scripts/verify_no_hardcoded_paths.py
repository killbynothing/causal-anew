#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guard high-value entry files against stale absolute workspace paths."""

from __future__ import annotations

import re
import sys
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    # 新仓不再搬 generate_mermaid（旧仓分析工具）；高价值入口改为规则三件套
    ROOT / "AGENTS.md",
    ROOT / "docs" / "plans" / "INDEX.md",
    ROOT / "STATUS.md",
    ROOT / "WORKFLOW.md",
]

PATTERNS = [
    re.compile(r"令人绝望的开始啊"),
    re.compile(r"file:///c:/users/11869/desktop/", re.IGNORECASE),
    re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+11869[\\/]+Desktop[\\/]+", re.IGNORECASE),
]

SCRIPT_DB_PATH_ALLOWLIST = {
    ROOT / "scripts" / "check_node.py",  # WT_DB env help/default is intentionally cwd-relative.
    ROOT / "scripts" / "update_db_from_qa.py",  # CLI default retained for legacy one-off tool.
    ROOT / "scripts" / "verify_no_hardcoded_paths.py",  # Contains the guard pattern itself.
}


def _script_db_path_failures() -> list[str]:
    failures: list[str] = []
    for path in (ROOT / "scripts").glob("*.py"):
        if path in SCRIPT_DB_PATH_ALLOWLIST:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            if path.name.startswith("_"):
                continue
            failures.append(f"{path.relative_to(ROOT)} cannot be parsed: {exc}")
            continue
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value.replace("\\", "/")
            if "world_truth.db" not in value:
                continue
            if _is_safe_data_db_literal(node, parents):
                continue
            if value == "world_truth.db" or value.endswith("/world_truth.db") and "/data/world_truth.db" not in value:
                failures.append(
                    f"{path.relative_to(ROOT)} has non-data world_truth.db literal at line {getattr(node, 'lineno', '?')}"
                )
                break
    return failures


def _is_safe_data_db_literal(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur = node
    for _ in range(5):
        parent = parents.get(cur)
        if parent is None:
            return False
        if _expr_contains_literal(parent, "data"):
            return True
        cur = parent
    return False


def _expr_contains_literal(node: ast.AST, text: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and child.value == text:
            return True
    return False


def main() -> int:
    failures: list[str] = []
    for path in TARGETS:
        if not path.exists():
            failures.append(f"missing target: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            if pattern.search(text):
                failures.append(f"{path.relative_to(ROOT)} still contains {pattern.pattern}")
                break
    failures.extend(_script_db_path_failures())

    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        return 1

    print("[PASS] no hardcoded legacy workspace paths in high-value entry files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
