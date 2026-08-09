#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify world_truth.db completeness against细剖 sources and contracts."""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import sys

try:
    import yaml
except ImportError:
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "data", "world_truth.db")
DEFAULT_SOURCES = os.path.join(ROOT, "analysis", "细剖事件表")
DEFAULT_CONTRACTS = os.path.join(ROOT, "contracts")
EVENT_UID_RE = re.compile(r"^E(\d{3})-(\d{2})$")
CH_GAP_CHAPTERS = (22, 47)
EXPECTED_COUNTS = {
    "events_run0": 565,
    # 2026-08-03 tiananmen cast +39 → 447
    # 2026-08-07 zhangchen knife1 +25 → 472
    # 2026-08-08 ryuya P.VOICE +8 → 480
    # 2026-08-08 cafe voice +2 (ex_casual/ex_married_soft) → 482
    # 2026-08-08 entrust portraits +2 voice (ex_brother/ex_entrust_soft) → 484
    "propositions": 484,
    "node_contracts": 5,
}


def parse_event_tables(sources_dir: str) -> tuple[set[str], dict[str, str], list[str]]:
    """Return (event_uids, knowledge_by_uid, errors)."""
    uids: set[str] = set()
    knowledge_by_uid: dict[str, str] = {}
    errors: list[str] = []
    pattern = os.path.join(sources_dir, "*细剖事件表.md")
    for path in sorted(glob.glob(pattern)):
        if "B1" in os.path.basename(path):
            continue
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except OSError as exc:
            errors.append(f"{path}: read failed ({exc})")
            continue
        header: list[str] | None = None
        for lineno, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if not parts:
                continue
            if all(re.match(r"^[-:]+$", p) for p in parts if p):
                continue
            if header is None:
                header = parts
                continue
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            uid = row.get("event_uid", "").strip()
            if not uid or uid == "event_uid":
                continue
            if not EVENT_UID_RE.match(uid):
                errors.append(f"{path}:{lineno}: invalid event_uid '{uid}'")
                continue
            if uid in uids:
                errors.append(f"{path}:{lineno}: duplicate event_uid '{uid}'")
            uids.add(uid)
            kb = row.get("知识变动", "").strip()
            if kb and kb not in {"无", "-", "暂无"}:
                knowledge_by_uid[uid] = kb
    return uids, knowledge_by_uid, errors


def load_contract_node_ids(contracts_dir: str) -> set[str]:
    ids: set[str] = set()
    for path in glob.glob(os.path.join(contracts_dir, "NODE-*.yaml")):
        if yaml is None:
            text = open(path, encoding="utf-8").read()
            m = re.search(r"^node_id:\s*(\S+)", text, re.MULTILINE)
            if m:
                ids.add(m.group(1))
            continue
        data = yaml.safe_load(open(path, encoding="utf-8"))
        if isinstance(data, dict) and data.get("node_id"):
            ids.add(str(data["node_id"]))
    return ids


def ch_gap_ok(sources_dir: str, conn: sqlite3.Connection) -> list[str]:
    issues: list[str] = []
    for ch in CH_GAP_CHAPTERS:
        note = os.path.join(sources_dir, f"Ch{ch}_no_events.md")
        has_events = conn.execute(
            "SELECT 1 FROM events WHERE run=0 AND ch_anchor=? LIMIT 1",
            (ch,),
        ).fetchone()
        if has_events:
            continue
        if not os.path.isfile(note):
            issues.append(f"Ch{ch}: no events in DB and missing {os.path.relpath(note, ROOT)}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify truth DB completeness")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--sources", default=DEFAULT_SOURCES)
    parser.add_argument("--contracts", default=DEFAULT_CONTRACTS)
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print(f"FAIL: database not found: {args.db}")
        return 1

    source_uids, knowledge_by_uid, parse_errors = parse_event_tables(args.sources)
    if parse_errors:
        print("FAIL: source parse errors:")
        for err in parse_errors:
            print(f"  - {err}")
        return 1

    conn = sqlite3.connect(args.db)
    db_uids: set[str] = set()
    for event_id, payload in conn.execute("SELECT event_id, payload FROM events WHERE run=0"):
        uid = None
        if payload:
            try:
                import json
                data = json.loads(payload)
                uid = data.get("event_uid")
            except Exception:
                uid = None
        if not uid:
            ch = event_id // 100
            seq = event_id % 100
            uid = f"E{ch:03d}-{seq:02d}"
        db_uids.add(str(uid))
    db_props = {row[0] for row in conn.execute("SELECT prop_id FROM propositions")}
    db_sched_sources = {
        row[0]
        for row in conn.execute("SELECT DISTINCT source_desc FROM knowledge_schedule WHERE source_desc IS NOT NULL")
    }
    db_contracts = {
        row[0] for row in conn.execute("SELECT node_id FROM node_contracts")
    }
    yaml_contracts = load_contract_node_ids(args.contracts)

    def knowledge_covered(uid: str) -> bool:
        if uid in db_sched_sources:
            return True
        prefix = f"TEMP_{uid.replace('-', '_')}_"
        return any(pid.startswith(prefix) for pid in db_props)

    counts = {
        "events_run0": conn.execute("SELECT COUNT(*) FROM events WHERE run=0").fetchone()[0],
        "knowledge_schedule": conn.execute("SELECT COUNT(*) FROM knowledge_schedule").fetchone()[0],
        "propositions": conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0],
        "node_contracts": conn.execute("SELECT COUNT(*) FROM node_contracts").fetchone()[0],
    }

    failures: list[str] = []

    missing = sorted(source_uids - db_uids)
    extra = sorted(db_uids - source_uids)
    if missing:
        failures.append(f"events missing in DB ({len(missing)}): {', '.join(missing[:8])}{'...' if len(missing) > 8 else ''}")
    if extra:
        failures.append(f"events extra in DB ({len(extra)}): {', '.join(extra[:8])}{'...' if len(extra) > 8 else ''}")

    missing_kb = sorted(uid for uid in knowledge_by_uid if not knowledge_covered(uid))
    if missing_kb:
        failures.append(
            f"knowledge_schedule missing source_desc for {len(missing_kb)} events: "
            f"{', '.join(missing_kb[:8])}{'...' if len(missing_kb) > 8 else ''}"
        )
    if not db_props and knowledge_by_uid:
        failures.append("propositions table empty but source has knowledge changes")

    if yaml_contracts != db_contracts:
        failures.append(
            f"node_contracts mismatch yaml={sorted(yaml_contracts)} db={sorted(db_contracts)}"
        )

    failures.extend(ch_gap_ok(args.sources, conn))

    for key, expected in EXPECTED_COUNTS.items():
        actual = counts[key]
        if actual != expected:
            failures.append(f"count {key}: expected {expected}, got {actual}")

    conn.close()

    print(f"source_uids={len(source_uids)} db_events_run0={counts['events_run0']}")
    print(
        f"knowledge_schedule={counts['knowledge_schedule']} "
        f"propositions={counts['propositions']} node_contracts={counts['node_contracts']}"
    )

    if failures:
        print("FAIL: truth completeness:")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("OK: truth completeness verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
