#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0a runtime authority audit.

Read-only static audit of runtime/web/scripts Python writers plus verify registry
inventory. This deliberately reports uncertain alias paths instead of claiming
AST completeness.

It does NOT modify runtime state, world_truth.db, session files, or source files.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "docs" / "analysis" / "runtime_authority_map_2026-09-29.json"
DEFAULT_MD = ROOT / "docs" / "analysis" / "runtime_authority_map_2026-09-29.md"

FIELD_SPECS: dict[str, dict[str, str]] = {
    "completed": {"domain": "beat", "target_owner": "BeatReducer"},
    "_completed": {
        "domain": "beat",
        "target_owner": "BeatReducer",
        "semantic_fact": "completed",
    },
    "completed_by_card": {"domain": "beat", "target_owner": "BeatReducer"},
    "_completed_by_card": {
        "domain": "beat",
        "target_owner": "BeatReducer",
        "semantic_fact": "completed_by_card",
    },
    "completed_beats": {"domain": "beat", "target_owner": "BeatReducer"},
    "_completed_beats": {
        "domain": "beat",
        "target_owner": "BeatReducer",
        "semantic_fact": "completed_beats",
    },
    "canon_performance_state": {"domain": "beat", "target_owner": "BeatReducer"},
    "_canon_performance_state": {
        "domain": "beat",
        "target_owner": "BeatReducer",
        "semantic_fact": "canon_performance_state",
    },
    "branch_progress": {"domain": "world", "target_owner": "WorldCommit"},
    "scene_receipts": {"domain": "world", "target_owner": "WorldCommit"},
    "world_transactions": {"domain": "world", "target_owner": "WorldCommit"},
    "causal_receipts": {"domain": "world", "target_owner": "WorldCommit"},
    "run_observation_ledger": {"domain": "world", "target_owner": "WorldCommit"},
    "player_state": {"domain": "player_world", "target_owner": "WorldCommit"},
    "body_frames": {"domain": "world", "target_owner": "WorldCommit"},
    "world_cursor": {"domain": "world", "target_owner": "WorldCommit"},
    "private_inner_states": {"domain": "mind_legacy", "target_owner": "ActorMindReducer"},
    "prior_reflect_by_cons": {"domain": "mind_legacy", "target_owner": "ActorMindReducer"},
    "actor_minds": {"domain": "mind", "target_owner": "ActorMindReducer"},
    "fsm_by_cons": {"domain": "mind_projection", "target_owner": "ActorMindReducer"},
    "rel_state_by_cons": {"domain": "mind_projection", "target_owner": "ActorMindReducer"},
    "lifecycle_state": {"domain": "exit", "target_owner": "ExitLifecycle"},
    "ended": {"domain": "exit", "target_owner": "ExitLifecycle"},
    "_run_closed": {"domain": "exit", "target_owner": "ExitLifecycle"},
    "run_receipt": {"domain": "exit", "target_owner": "ExitLifecycle"},
    "_last_exit_intent_exit_spec": {"domain": "exit", "target_owner": "ExitPolicy"},
    "pending_entry": {"domain": "exit", "target_owner": "ExitPolicy"},
    "ryuya_flashback_return": {"domain": "exit", "target_owner": "ExitPolicy"},
    "utterance_queue": {"domain": "delivery", "target_owner": "DeliveryCommit"},
}

SQL_TABLE_SPECS: dict[str, dict[str, str]] = {
    "run_meta": {"domain": "exit_run", "target_owner": "ExitLifecycle/RunRegistry"},
    "delta_ledger": {"domain": "world_delta", "target_owner": "WorldCommit/Settlement"},
    "delta_sediment": {"domain": "world_delta", "target_owner": "Settlement"},
    "run_receipts": {"domain": "exit_run", "target_owner": "ExitLifecycle"},
}

REMOVAL_PHASE_BY_DOMAIN = {
    "beat": "P2c",
    "world": "P2c",
    "player_world": "P2",
    "mind_legacy": "P3",
    "mind": "P3",
    "mind_projection": "P3",
    "exit": "P1",
    "exit_run": "P1b",
    "delivery": "P2/P6",
    "world_delta": "P1b/P2",
}

MUTATING_METHODS = {
    "append", "extend", "insert", "update", "setdefault", "pop", "popitem",
    "clear", "remove", "discard", "add", "sort", "reverse",
}
MUTATING_HELPER_HINTS = (
    "apply", "append", "commit", "finalize", "mark", "mutate", "record",
    "resolve", "settle", "tick", "update", "write",
)
SQL_DML_RE = re.compile(
    r"\b(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Writer:
    semantic_fact: str
    domain: str
    target_owner: str
    path: str
    symbol: str
    line: int
    write_kind: str
    classification: str
    confidence: str
    detail: str = ""


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def classify(path: Path, symbol: str, *, uncertain: bool = False) -> str:
    rp = rel(path)
    low = symbol.lower()
    leaf = low.rsplit(".", 1)[-1]
    if "/tests/" in f"/{rp}" or rp.startswith("scripts/tests/"):
        return "test"
    if rp == "scripts/audit_runtime_authority.py":
        return "audit"
    if uncertain:
        return "unknown_alias"
    if leaf in {"__init__", "__post_init__"} or leaf.startswith("_init"):
        return "initialization"
    if any(tok in low for tok in ("migrate", "migration", "restore", "from_state", "_load", "load_")):
        return "load_migration"
    if any(tok in low for tok in ("projection", "observer", "snapshot", "serialize", "to_dict", "_state_payload")):
        return "projection"
    if rp.startswith("scripts/"):
        return "production_tooling"
    return "production"


def self_field(node: ast.AST) -> str | None:
    """Return a tracked attribute name regardless of the receiver variable.

    The historical name is kept for compatibility inside this script. P0a must
    catch writes such as session.ended outside FreeStageSession methods, not
    only self.ended.
    """
    while isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute) and node.attr in FIELD_SPECS:
        return node.attr
    return None


class AuthorityVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.scope: list[str] = []
        self.alias_stack: list[dict[str, str]] = [dict()]
        self.writers: list[Writer] = []

    @property
    def symbol(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    @property
    def aliases(self) -> dict[str, str]:
        return self.alias_stack[-1]

    def _record(
        self,
        field: str,
        node: ast.AST,
        kind: str,
        *,
        uncertain: bool = False,
        detail: str = "",
    ) -> None:
        spec = FIELD_SPECS[field]
        self.writers.append(
            Writer(
                semantic_fact=spec.get("semantic_fact", field),
                domain=spec["domain"],
                target_owner=spec["target_owner"],
                path=rel(self.path),
                symbol=self.symbol,
                line=int(getattr(node, "lineno", 0) or 0),
                write_kind=kind,
                classification=classify(self.path, self.symbol, uncertain=uncertain),
                confidence="medium" if uncertain else "high",
                detail=detail,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.scope.append(node.name)
        self.alias_stack.append(dict(self.aliases))
        self.generic_visit(node)
        self.alias_stack.pop()
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Any:
        self.scope.append(node.name)
        self.alias_stack.append({})
        self.generic_visit(node)
        self.alias_stack.pop()
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _targets(self, target: ast.AST) -> Iterable[str]:
        field = self_field(target)
        if field:
            yield field
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                yield from self._targets(item)

    def _capture_alias(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            return
        field = self_field(value)
        if field:
            self.aliases[target.id] = field

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            for field in self._targets(target):
                self._record(field, node, "assign")
            self._capture_alias(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        for field in self._targets(node.target):
            self._record(field, node, "ann_assign")
        if node.value is not None:
            self._capture_alias(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> Any:
        for field in self._targets(node.target):
            self._record(field, node, "aug_assign")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute):
            base_field = self_field(node.func.value)
            if base_field and node.func.attr in MUTATING_METHODS:
                self._record(base_field, node, f"method:{node.func.attr}")
            elif isinstance(node.func.value, ast.Name):
                alias_field = self.aliases.get(node.func.value.id)
                if alias_field and node.func.attr in MUTATING_METHODS:
                    self._record(
                        alias_field,
                        node,
                        f"alias_method:{node.func.attr}",
                        uncertain=True,
                        detail=f"local alias {node.func.value.id}",
                    )

        callee = dotted_name(node.func).split(".")[-1].lower()
        looks_mutating = any(hint in callee for hint in MUTATING_HELPER_HINTS)
        if looks_mutating:
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                field = self_field(arg)
                if field:
                    self._record(
                        field,
                        node,
                        "pass_to_mutating_helper",
                        uncertain=True,
                        detail=dotted_name(node.func),
                    )

        self.generic_visit(node)


class SqlVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.scope: list[str] = []
        self.writers: list[Writer] = []

    @property
    def symbol(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Any:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Constant(self, node: ast.Constant) -> Any:
        if not isinstance(node.value, str):
            return
        for match in SQL_DML_RE.finditer(node.value):
            op = re.sub(r"\s+", "_", match.group(1).lower())
            table = match.group(2)
            spec = SQL_TABLE_SPECS.get(table)
            if not spec:
                continue
            self.writers.append(
                Writer(
                    semantic_fact=f"sql:{table}",
                    domain=spec["domain"],
                    target_owner=spec["target_owner"],
                    path=rel(self.path),
                    symbol=self.symbol,
                    line=int(getattr(node, "lineno", 0) or 0),
                    write_kind=op,
                    classification=classify(self.path, self.symbol),
                    confidence="high",
                    detail="SQL DML",
                )
            )


def iter_python_files() -> Iterable[Path]:
    for base in ("runtime", "web", "scripts"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if "__pycache__" in parts:
                continue
            yield path


class CallsiteVisitor(ast.NodeVisitor):
    """Best-effort same-file caller index.

    This is intentionally not a whole-program call graph. It gives each direct
    writer a useful caller list while keeping unresolved dynamic dispatch honest.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.scope: list[str] = []
        self.calls: list[dict[str, Any]] = []

    @property
    def symbol(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Any:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> Any:
        callee = dotted_name(node.func)
        if callee:
            self.calls.append(
                {
                    "path": rel(self.path),
                    "caller": self.symbol,
                    "callee": callee,
                    "callee_leaf": callee.rsplit(".", 1)[-1],
                    "line": int(getattr(node, "lineno", 0) or 0),
                }
            )
        self.generic_visit(node)


def scan_callsites() -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(iter_python_files()):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            continue
        visitor = CallsiteVisitor(path)
        visitor.visit(tree)
        for call in visitor.calls:
            index[(call["path"], call["callee_leaf"])].append(
                {
                    "caller": call["caller"],
                    "line": call["line"],
                    "callee": call["callee"],
                    "confidence": "medium",
                }
            )
    return index


def scan_writers() -> tuple[list[Writer], list[dict[str, Any]]]:
    writers: list[Writer] = []
    parse_errors: list[dict[str, Any]] = []
    for path in sorted(iter_python_files()):
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            parse_errors.append({"path": rel(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        av = AuthorityVisitor(path)
        av.visit(tree)
        writers.extend(av.writers)
        sv = SqlVisitor(path)
        sv.visit(tree)
        writers.extend(sv.writers)

    dedup = {}
    for row in writers:
        key = (
            row.semantic_fact, row.path, row.symbol, row.line,
            row.write_kind, row.classification, row.detail,
        )
        dedup[key] = row
    return sorted(
        dedup.values(),
        key=lambda r: (r.semantic_fact, r.path, r.line, r.write_kind),
    ), parse_errors


def load_verify_module():
    path = ROOT / "scripts" / "verify.py"
    spec = importlib.util.spec_from_file_location("_authority_verify_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_inventory(run_quick: bool) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    module = load_verify_module()
    rows: list[dict[str, Any]] = []
    quick = [v for v in module.VALIDATORS if v.get("tier") == "quick"]
    for v in module.VALIDATORS:
        reason = module.skip_reason(v) if v.get("tier") == "quick" else None
        rows.append(
            {
                "id": v["id"],
                "tier": v["tier"],
                "need_file": v.get("need_file"),
                "need_file_exists": (
                    None if not v.get("need_file")
                    else (ROOT / v["need_file"]).exists()
                ),
                "precheck_status": "skip" if reason else ("runnable" if v["tier"] == "quick" else "full_not_run"),
                "skip_reason": reason,
                "actual_status": None,
            }
        )

    summary = None
    if run_quick:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify.py"), "--quick"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        match = re.search(r"PASS\s+(\d+)\s+\|\s+FAIL\s+(\d+)\s+\|\s+SKIP\s+(\d+)", proc.stdout)
        if not match:
            raise RuntimeError("could not parse verify --quick summary")
        passed, failed, skipped = map(int, match.groups())
        static_skips = sum(1 for r in rows if r["tier"] == "quick" and r["precheck_status"] == "skip")
        runnable = sum(1 for r in rows if r["tier"] == "quick" and r["precheck_status"] == "runnable")
        summary = {
            "exit_code": proc.returncode,
            "pass": passed,
            "fail": failed,
            "skip": skipped,
            "quick_registered": len(quick),
            "static_skip_count": static_skips,
            "static_runnable_count": runnable,
            "counts_match_precheck": skipped == static_skips and passed + failed == runnable,
        }
        if proc.returncode == 0 and failed == 0 and summary["counts_match_precheck"]:
            for row in rows:
                if row["tier"] != "quick":
                    continue
                row["actual_status"] = "skip" if row["precheck_status"] == "skip" else "pass"
        else:
            for row in rows:
                if row["tier"] == "quick" and row["precheck_status"] == "skip":
                    row["actual_status"] = "skip"
    return rows, summary


def build_report(run_quick: bool) -> dict[str, Any]:
    writers, parse_errors = scan_writers()
    callsites = scan_callsites()
    verify_rows, quick_summary = verify_inventory(run_quick)

    writer_rows: list[dict[str, Any]] = []
    by_fact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for writer in writers:
        row = asdict(writer)
        row["current_owner"] = writer.symbol
        row["scope"] = "db_runtime" if writer.semantic_fact.startswith("sql:") else "session_runtime"
        row["removal_phase"] = REMOVAL_PHASE_BY_DOMAIN.get(writer.domain, "P0b-review")
        leaf = writer.symbol.rsplit(".", 1)[-1]
        row["callers"] = [
            call for call in callsites.get((writer.path, leaf), [])
            if call["caller"] != writer.symbol
        ]
        writer_rows.append(row)
        by_fact[writer.semantic_fact].append(row)

    production_classes = {"production", "production_tooling"}
    unresolved = [row for row in writer_rows if row["classification"] == "unknown_alias"]
    production = [row for row in writer_rows if row["classification"] in production_classes]

    facts = {}
    for fact, spec in {**FIELD_SPECS, **{f"sql:{k}": v for k, v in SQL_TABLE_SPECS.items()}}.items():
        fact_rows = by_fact.get(fact, [])
        facts[fact] = {
            **spec,
            "removal_phase": REMOVAL_PHASE_BY_DOMAIN.get(spec["domain"], "P0b-review"),
            "writer_count": len(fact_rows),
            "production_writer_count": sum(1 for r in fact_rows if r["classification"] in production_classes),
            "unknown_alias_count": sum(1 for r in fact_rows if r["classification"] == "unknown_alias"),
            "writers": fact_rows,
        }

    return {
        "schema_version": "runtime.authority.audit.v1",
        "source_revision_note": "generated from current worktree; use git commit for immutable provenance",
        "scope": ["runtime/**/*.py", "web/**/*.py", "scripts/**/*.py"],
        "method": {
            "ast": "assign/subscript/mutating-method/local-alias/mutating-helper hints",
            "sql": "string-literal INSERT/UPDATE/DELETE/REPLACE for tracked runtime tables",
            "limitations": [
                "dynamic setattr/exec/eval and interprocedural alias mutation may be missed",
                "pass_to_mutating_helper and local alias mutations are marked unknown_alias, not claimed as proven writes",
                "non-Python writers are outside P0a scanner scope and require manual audit if they can mutate runtime state",
            ],
        },
        "facts": facts,
        "writers": writer_rows,
        "summary": {
            "writer_count": len(writers),
            "production_writer_count": len(production),
            "unknown_alias_count": len(unresolved),
            "parse_error_count": len(parse_errors),
            "facts_with_multiple_production_writers": sorted(
                fact for fact, data in facts.items() if data["production_writer_count"] > 1
            ),
            "facts_with_unknown_aliases": sorted(
                fact for fact, data in facts.items() if data["unknown_alias_count"] > 0
            ),
        },
        "parse_errors": parse_errors,
        "unknown_aliases": unresolved,
        "verify_inventory": verify_rows,
        "quick_run_summary": quick_summary,
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    q = report.get("quick_run_summary")
    lines = [
        "# P0a Runtime Authority Map · 2026-09-29",
        "",
        "> 自动生成的只读审计摘要。JSON 是机器原件；本页只做人读投影。",
        "",
        "## 摘要",
        "",
        f"- writer 记录：**{s['writer_count']}**；其中 production/tooling：**{s['production_writer_count']}**。",
        f"- uncertain alias：**{s['unknown_alias_count']}**。这些不是已证 writer，也不能当作已排除。",
        f"- AST 解析错误：**{s['parse_error_count']}**。",
        f"- 多 production writer 的事实：**{len(s['facts_with_multiple_production_writers'])}**。",
    ]
    if q:
        lines += [
            f"- 本次 quick：**{q['pass']} PASS / {q['fail']} FAIL / {q['skip']} SKIP**；登记 quick={q['quick_registered']}。",
            f"- quick 预检计数与实跑计数一致：**{q['counts_match_precheck']}**。",
        ]
    lines += [
        "",
        "## 五域与 writer",
        "",
        "| semantic fact | target owner | removal | prod writers | unknown aliases |",
        "|---|---|---|---:|---:|",
    ]
    for fact, data in report["facts"].items():
        lines.append(
            f"| `{fact}` | {data['target_owner']} | {data['removal_phase']} | {data['production_writer_count']} | {data['unknown_alias_count']} |"
        )

    lines += ["", "## 生产 writer 明细", ""]
    for fact, data in report["facts"].items():
        prod = [
            r for r in data["writers"]
            if r["classification"] in {"production", "production_tooling", "unknown_alias"}
        ]
        if not prod:
            continue
        lines.append(f"### `{fact}` → {data['target_owner']}")
        lines.append("")
        for r in prod:
            suffix = f" · {r['detail']}" if r.get("detail") else ""
            lines.append(
                f"- `{r['path']}:{r['line']}` · `{r['symbol']}` · "
                f"{r['write_kind']} · **{r['classification']}** · {r['confidence']}{suffix}"
            )
        lines.append("")

    lines += [
        "## Verify 登记 inventory",
        "",
        "| status | count |",
        "|---|---:|",
    ]
    counts = Counter(r["actual_status"] or r["precheck_status"] for r in report["verify_inventory"])
    for status, count in sorted(counts.items()):
        lines.append(f"| {status} | {count} |")
    lines += ["", "### SKIP 原因", ""]
    skip_reasons = Counter(
        r["skip_reason"] or "<none>"
        for r in report["verify_inventory"]
        if r["tier"] == "quick" and r["precheck_status"] == "skip"
    )
    for reason, count in skip_reasons.most_common():
        lines.append(f"- {count} × {reason}")

    lines += [
        "",
        "## 审计限制 / 红胶带",
        "",
        "- 本报告**不宣称 AST 完备**。动态 setattr/exec、跨函数别名写入和非 Python writer 需要后续 trace/人工调用链补证。",
        "- `unknown_alias` 必须在所属域切换前逐条解释或增加运行 trace；不能因为 production writer 数量看起来少就宣布收口。",
        "- 初始化、load/migration、projection 可以存在，但必须保持单向；本报告分类错误也要在 P0a 内修正。",
        "- 当前多 writer 是 P0a 的测绘结果，不是测试失败；到对应 P1/P2/P3 阶段会升级为 required=0 旁路。",
        "- 本扫描器只读源码和验证器登记，不写 world_truth.db、session、δ 或 runtime 状态。",
        "",
    ]
    return "\n".join(lines).rstrip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    ap.add_argument("--run-quick", action="store_true", help="Run verify --quick and attach current pass/fail/skip summary")
    ap.add_argument("--stdout", action="store_true", help="Print JSON to stdout instead of only writing files")
    args = ap.parse_args()

    report = build_report(args.run_quick)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report) + "\n", encoding="utf-8")
    if args.stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = report["summary"]
        print(
            f"authority audit: writers={s['writer_count']} "
            f"production={s['production_writer_count']} unknown_alias={s['unknown_alias_count']} "
            f"parse_errors={s['parse_error_count']}"
        )
        if report.get("quick_run_summary"):
            q = report["quick_run_summary"]
            print(f"quick: PASS {q['pass']} | FAIL {q['fail']} | SKIP {q['skip']}")
        print(args.json.relative_to(ROOT))
        print(args.markdown.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
