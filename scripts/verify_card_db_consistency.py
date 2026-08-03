#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_card_db_consistency.py —— 卡↔库一致性闸（M1 止血件）

背景（见 docs/盲区排查_unknown_unknowns_2026-07-07.md §M1）：
红线1 说 data/world_truth.db 是唯一真值源，但运行时逐拍消费的是手写卡
runtime/free_stage_card_*.json，库只在卡编译器 (generate_cards.py) 和
contracts 校验时被读。已发生过两次卡/库分叉（海豚名"波波"vs 原著"小蓝"；
contracts 引真值而库里没事件）。本闸补上"卡↔库全量一致性"这一层，
把靠自觉变成会报红的机器检查。

设计原则：
  - 硬错误级（红，导致 exit 1）：
      H1 卡引用的 event_uid / prop_id 在 world_truth.db 对应表中不存在。
      H2 卡 exits[].target_card 指向的文件不存在。
      H3 knowledge_gate 的"允许谈论"文本里出现了某个在场角色尚未学到
         （knowledge_schedule.learn_ch > 卡的 ch_anchor）的正典命题原文
         （知识非未来化）。
  - 软警告级（WARN，不影响 exit code）：
      W1 卡内专名（persona_cards[cons_id].name）与生成器canonical映射
         不一致，或命中已知错误别名（如海豚"波波"应为"小蓝"）。
      W2 clock 与 scene_frame.when 的时间描述矛盾（登记簿 C3：
         when 写"下午"但 clock 是 <12 点的时刻，反之亦然）。
  - 存量不红：首跑时已经存在的 H 级不一致写入
    scripts/card_db_consistency_whitelist.json 白名单（带原因），
    闸只堵**新增**漂移——同一 (card, check, ref) 组合若已在白名单里，
    降级为 WHITELISTED，不算失败；不在白名单里的新发现才会让本脚本 exit 1。
  - 降级：某个检查依赖的表/字段在当前 db schema 里不存在时，SKIP 该检查
    并记录原因，不猜 schema、不硬编码绕过。

跳过范围：只扫 runtime/ 目录下直接的 free_stage_card_*.json，
不递归进 runtime/card_drafts/（编译器草案，未定稿）与任何 _archive/ 路径
（历史存档卡）。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS_DIR = ROOT / "runtime"
DEFAULT_DB_PATH = ROOT / "data" / "world_truth.db"
DEFAULT_WHITELIST_PATH = ROOT / "scripts" / "card_db_consistency_whitelist.json"

EVENT_UID_RE = re.compile(r"\bE\d{3}-\d{2}\b")
# Allow dotted facets: P.VOICE... / P.ARCH... / REL.IDENTITY... / REL.HOLD...
PROP_ID_RE = re.compile(r"\b(?:P|REL)(?:\.[A-Za-z0-9_]+)+\b")

ALLOW_MARKERS = (
    "可以谈论",
    "可谈论",
    "可以谈",
    "允许谈论",
    "允许:",
    "此刻知道",
    "可自然谈",
    "身份口径",
)
FORBID_MARKERS = ("禁止", "不得", "不可")

# generate_cards.py 里的 canonical 展示名映射（get_display_name），
# 手写卡应当与之一致；这里复用同一份映射作为专名一致性基线。
CANONICAL_NAMES = {
    "C.kakashi.WMAIN": "坂本晴明",
    "C.akito.WMAIN": "川口秋人",
    "C.xiuzai.WMAIN": "折原修哉",
}

# 已知错误别名 -> 正确名（人裁定稿见 STATUS 2026-07-06 续16：海豚名统一为"小蓝"）
BANNED_ALIASES = {
    "波波": "海豚应为原著名「小蓝」（STATUS 2026-07-06 续16 定稿）",
}

MORNING_MARKERS = ("上午", "凌晨", "早上", "清晨", "拂晓")
AFTERNOON_MARKERS = ("下午", "晚上", "傍晚", "夜里", "深夜", "黄昏")


def iter_card_files(cards_dir: Path) -> list[Path]:
    """只取 cards_dir 直接子文件，天然跳过 _archive/ 与 card_drafts/ 子目录。"""
    files = sorted(cards_dir.glob("free_stage_card_*.json"))
    out = []
    for f in files:
        parts = {p.lower() for p in f.parts}
        if "_archive" in parts or "card_drafts" in parts:
            continue
        out.append(f)
    return out


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class DbIndex:
    """从 world_truth.db 里按实际 schema 抽取本闸需要的几张表；缺表/缺列则记录降级原因。"""

    def __init__(self, db_path: Path):
        self.skip_notes: list[str] = []
        self.event_uids: set[str] = set()
        self.prop_ids: set[str] = set()
        self.prop_statements: dict[str, str] = {}
        # cons_id -> list[(prop_id, learn_ch)]
        self.knowledge_schedule: dict[str, list[tuple[str, int]]] = {}
        self.have_events = False
        self.have_propositions = False
        self.have_knowledge_schedule = False

        if not db_path.exists():
            self.skip_notes.append(f"数据库不存在: {db_path}")
            return

        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}

            if "events" in tables:
                cols = {r[1] for r in cur.execute("PRAGMA table_info(events)")}
                if "payload" in cols:
                    self.have_events = True
                    for (payload_str,) in cur.execute("SELECT payload FROM events"):
                        try:
                            payload = json.loads(payload_str) if payload_str else {}
                        except Exception:
                            continue
                        uid = payload.get("event_uid")
                        if uid:
                            self.event_uids.add(uid)
                else:
                    self.skip_notes.append("events 表缺少 payload 列，跳过 event_uid 存在性检查")
            else:
                self.skip_notes.append("events 表不存在，跳过 event_uid 存在性检查")

            if "propositions" in tables:
                cols = {r[1] for r in cur.execute("PRAGMA table_info(propositions)")}
                if {"prop_id", "statement"}.issubset(cols):
                    self.have_propositions = True
                    for prop_id, statement in cur.execute(
                        "SELECT prop_id, statement FROM propositions"
                    ):
                        self.prop_ids.add(prop_id)
                        self.prop_statements[prop_id] = statement
                else:
                    self.skip_notes.append(
                        "propositions 表缺少 prop_id/statement 列，跳过知识条目存在性与非未来化检查"
                    )
            else:
                self.skip_notes.append(
                    "propositions 表不存在，跳过知识条目存在性与非未来化检查"
                )

            if "knowledge_schedule" in tables:
                cols = {r[1] for r in cur.execute("PRAGMA table_info(knowledge_schedule)")}
                if {"cons_id", "prop_id", "learn_ch"}.issubset(cols):
                    self.have_knowledge_schedule = True
                    for cons_id, prop_id, learn_ch in cur.execute(
                        "SELECT cons_id, prop_id, learn_ch FROM knowledge_schedule"
                    ):
                        self.knowledge_schedule.setdefault(cons_id, []).append(
                            (prop_id, learn_ch)
                        )
                else:
                    self.skip_notes.append(
                        "knowledge_schedule 表缺少 cons_id/prop_id/learn_ch 列，跳过知识非未来化检查"
                    )
            else:
                self.skip_notes.append(
                    "knowledge_schedule 表不存在，跳过知识非未来化检查"
                )
        finally:
            conn.close()


def get_present_chars(card: dict) -> list[str]:
    present = card.get("present")
    if isinstance(present, list) and present:
        return present
    frame = card.get("scene_frame") or {}
    cons_present = frame.get("cons_present")
    if isinstance(cons_present, list):
        return cons_present
    return []


def classify_knowledge_gate_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    allow_lines, forbid_lines = [], []
    for line in lines:
        if any(m in line for m in FORBID_MARKERS):
            forbid_lines.append(line)
        elif any(m in line for m in ALLOW_MARKERS):
            allow_lines.append(line)
    return allow_lines, forbid_lines


def check_event_and_prop_refs(rel: str, raw_text: str, db: DbIndex) -> list[dict]:
    findings = []
    if db.have_events:
        for uid in sorted(set(EVENT_UID_RE.findall(raw_text))):
            if uid not in db.event_uids:
                findings.append(
                    {
                        "level": "ERROR",
                        "check": "event_uid_exists",
                        "ref": uid,
                        "card": rel,
                        "message": f"卡引用 event_uid={uid}，但 world_truth.db events 表(run=0)里不存在",
                    }
                )
    if db.have_propositions:
        for pid in sorted(set(PROP_ID_RE.findall(raw_text))):
            if pid not in db.prop_ids:
                findings.append(
                    {
                        "level": "ERROR",
                        "check": "prop_id_exists",
                        "ref": pid,
                        "card": rel,
                        "message": f"卡引用 prop_id={pid}，但 world_truth.db propositions 表里不存在",
                    }
                )
    return findings


def check_exits(rel: str, card_path: Path, card: dict) -> list[dict]:
    findings = []
    exits = card.get("exits")
    if not isinstance(exits, list):
        return findings
    for exit_spec in exits:
        if not isinstance(exit_spec, dict):
            continue
        target = exit_spec.get("target_card")
        if not target:
            continue
        target_path = (ROOT / target) if not Path(target).is_absolute() else Path(target)
        if not target_path.exists():
            findings.append(
                {
                    "level": "ERROR",
                    "check": "exit_target_exists",
                    "ref": target,
                    "card": rel,
                    "message": f"卡 exits[].target_card={target} 指向的文件不存在",
                }
            )
    return findings


def check_knowledge_future(rel: str, card: dict, db: DbIndex, skip_notes: list[str]) -> list[dict]:
    findings: list[dict] = []
    if not (db.have_propositions and db.have_knowledge_schedule):
        return findings  # 已经在 DbIndex 里记录过整体降级原因

    ch_anchor = card.get("ch_anchor")
    present = get_present_chars(card)
    kg_lines = (card.get("memory_layers") or {}).get("knowledge_gate") or []
    if ch_anchor is None or not present or not kg_lines:
        skip_notes.append(
            f"{rel}: 缺 ch_anchor/present/knowledge_gate 字段之一，跳过知识非未来化检查"
        )
        return findings

    allow_lines, _forbid_lines = classify_knowledge_gate_lines(kg_lines)
    if not allow_lines:
        skip_notes.append(
            f"{rel}: knowledge_gate 未见可识别的\"允许谈论\"结构化行，跳过知识非未来化字符串级校验"
        )
        return findings

    for cons in present:
        for prop_id, learn_ch in db.knowledge_schedule.get(cons, []):
            if learn_ch <= ch_anchor:
                continue
            statement = db.prop_statements.get(prop_id)
            if not statement:
                continue
            for line in allow_lines:
                if statement in line:
                    findings.append(
                        {
                            "level": "ERROR",
                            "check": "knowledge_not_future",
                            "ref": f"{cons}:{prop_id}",
                            "card": rel,
                            "message": (
                                f"{cons} 要到 ch{learn_ch} 才学到的命题 {prop_id}"
                                f"（{statement}）出现在本卡(ch_anchor={ch_anchor})"
                                f"knowledge_gate 的允许谈论行里"
                            ),
                        }
                    )
    return findings


def check_name_and_alias(rel: str, card: dict, raw_text: str) -> list[dict]:
    findings = []
    persona_cards = card.get("persona_cards") or {}
    for cons_id, pc in persona_cards.items():
        expected = CANONICAL_NAMES.get(cons_id)
        if expected is None:
            continue
        name = pc.get("name") if isinstance(pc, dict) else None
        if name and name != expected:
            findings.append(
                {
                    "level": "WARN",
                    "check": "persona_name_matches_canon",
                    "ref": cons_id,
                    "card": rel,
                    "message": f"{cons_id} 的 persona_cards.name='{name}'，与 canonical 展示名'{expected}'不一致",
                }
            )
    for alias, reason in BANNED_ALIASES.items():
        if alias in raw_text:
            findings.append(
                {
                    "level": "WARN",
                    "check": "banned_alias",
                    "ref": alias,
                    "card": rel,
                    "message": f"卡内出现已废弃别名 '{alias}'：{reason}",
                }
            )
    return findings


def check_clock_when(rel: str, card: dict) -> list[dict]:
    findings = []
    clock = card.get("clock")
    when = (card.get("scene_frame") or {}).get("when")
    if not clock or not when:
        return findings
    m = re.match(r"^(\d{1,2}):(\d{2})", str(clock).strip())
    if not m:
        return findings
    hour = int(m.group(1))
    has_morning = any(mk in when for mk in MORNING_MARKERS)
    has_afternoon = any(mk in when for mk in AFTERNOON_MARKERS)
    if has_morning and hour >= 12:
        findings.append(
            {
                "level": "WARN",
                "check": "clock_when_consistent",
                "ref": f"clock={clock}",
                "card": rel,
                "message": (
                    f"scene_frame.when='{when}' 含晨间用语，但 clock={clock} 的小时数>=12"
                    "（登记簿 C3：when 与 clock 需单一来源，此处疑似矛盾）"
                ),
            }
        )
    if has_afternoon and hour < 12:
        findings.append(
            {
                "level": "WARN",
                "check": "clock_when_consistent",
                "ref": f"clock={clock}",
                "card": rel,
                "message": (
                    f"scene_frame.when='{when}' 含下午/夜间用语，但 clock={clock} 的小时数<12"
                    "（登记簿 C3：when 与 clock 需单一来源，此处疑似矛盾）"
                ),
            }
        )
    return findings


def load_whitelist(whitelist_path: Path) -> tuple[set[tuple[str, str, str]], list[dict]]:
    if not whitelist_path.exists():
        return set(), []
    data = json.loads(whitelist_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    keys = {(e["card"], e["check"], e["ref"]) for e in entries}
    return keys, entries


def check_all(
    cards_dir: Path = DEFAULT_CARDS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    whitelist_path: Path | None = DEFAULT_WHITELIST_PATH,
) -> dict:
    db = DbIndex(db_path)
    whitelist_keys: set[tuple[str, str, str]] = set()
    if whitelist_path is not None:
        whitelist_keys, _ = load_whitelist(whitelist_path)

    hard_findings: list[dict] = []
    whitelisted_findings: list[dict] = []
    warn_findings: list[dict] = []
    skip_notes: list[str] = list(db.skip_notes)
    cards_checked: list[str] = []

    for card_path in iter_card_files(cards_dir):
        try:
            rel = str(card_path.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            # 卡不在仓库 ROOT 下（例如测试用临时目录里的红样本卡），
            # 退化为直接用文件名，不影响一致性检查本身。
            rel = str(card_path).replace("\\", "/")
        cards_checked.append(rel)
        try:
            card = load_json(card_path)
        except Exception as e:
            hard_findings.append(
                {
                    "level": "ERROR",
                    "check": "card_is_valid_json",
                    "ref": rel,
                    "card": rel,
                    "message": f"卡文件不是合法 JSON: {e}",
                }
            )
            continue
        raw_text = card_path.read_text(encoding="utf-8")

        all_findings = []
        all_findings += check_event_and_prop_refs(rel, raw_text, db)
        all_findings += check_exits(rel, card_path, card)
        all_findings += check_knowledge_future(rel, card, db, skip_notes)
        all_findings += check_name_and_alias(rel, card, raw_text)
        all_findings += check_clock_when(rel, card)

        for f in all_findings:
            if f["level"] == "WARN":
                warn_findings.append(f)
            else:
                key = (f["card"], f["check"], f["ref"])
                if key in whitelist_keys:
                    f2 = dict(f)
                    f2["level"] = "WHITELISTED"
                    whitelisted_findings.append(f2)
                else:
                    hard_findings.append(f)

    return {
        "cards_checked": cards_checked,
        "hard_findings": hard_findings,
        "whitelisted_findings": whitelisted_findings,
        "warn_findings": warn_findings,
        "skip_notes": skip_notes,
    }


def main() -> int:
    result = check_all()

    print(f"verify_card_db_consistency :: 扫描 {len(result['cards_checked'])} 张卡")
    for note in result["skip_notes"]:
        print(f"[SKIP] {note}")

    for f in result["whitelisted_findings"]:
        print(f"[WHITELISTED] {f['card']} [{f['check']}] {f['message']}")

    for f in result["warn_findings"]:
        print(f"[WARN] {f['card']} [{f['check']}] {f['message']}")

    for f in result["hard_findings"]:
        print(f"[FAIL] {f['card']} [{f['check']}] {f['message']}")

    n_hard = len(result["hard_findings"])
    n_wl = len(result["whitelisted_findings"])
    n_warn = len(result["warn_findings"])
    print(
        f"\n  FAIL {n_hard} | WHITELISTED {n_wl} | WARN {n_warn} | "
        f"SKIP {len(result['skip_notes'])} | cards {len(result['cards_checked'])}"
    )

    if n_hard:
        print("\n[red] 发现未登记的卡↔库不一致，请修正卡/库，或经人裁后写入 "
              "scripts/card_db_consistency_whitelist.json 并注明原因")
        return 1

    print("\n[green] 卡↔库一致性检查通过（存量不一致均已登记在白名单）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
