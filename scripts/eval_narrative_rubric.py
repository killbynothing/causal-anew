#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Narrative rubric CLI. --smoke is deterministic (no LLM / GPU)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.narrative_rubric import DIMENSIONS, score_transcript

FIXTURE = ROOT / "scripts" / "tests" / "fixtures" / "narrative_rubric_cases.json"


def _radar(dims: dict) -> str:
    lines = ["dim                  score  pass  hits"]
    for name in DIMENSIONS:
        row = dims.get(name) or {}
        flag = "PASS" if row.get("pass") else "FAIL"
        hits = ",".join(row.get("hits") or [])[:48]
        lines.append(f"{name:<20} {float(row.get('score') or 0):5.2f}  {flag}  {hits}")
    return "\n".join(lines)


def load_cases() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def run_smoke() -> int:
    if not FIXTURE.is_file():
        print(f"FAIL missing fixture {FIXTURE}", file=sys.stderr)
        return 1
    failed = 0
    for case in load_cases():
        name = str(case.get("id") or "?")
        session = case.get("session") or {}
        expect_fail = set(case.get("expect_fail") or [])
        expect_pass = set(case.get("expect_pass") or [])
        report = score_transcript(session)
        dims = report["dimensions"]
        print(f"\n== {name}  mean={report['mean']} overall={'PASS' if report['pass'] else 'FAIL'} ==")
        print(_radar(dims))
        for dim in expect_fail:
            if dims.get(dim, {}).get("pass"):
                print(f"FAIL {name}: expected {dim} to fail")
                failed += 1
        for dim in expect_pass:
            if not dims.get(dim, {}).get("pass"):
                print(f"FAIL {name}: expected {dim} to pass, hits={dims.get(dim, {}).get('hits')}")
                failed += 1
    if failed:
        print(f"\nSMOKE FAIL {failed}")
        return 1
    print("\nSMOKE PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Narrative rubric (JD five dimensions)")
    parser.add_argument("--smoke", action="store_true", help="golden fixtures, no LLM")
    parser.add_argument("--transcript", type=str, default="", help="session JSON path")
    args = parser.parse_args(argv)
    if args.smoke or not args.transcript:
        return run_smoke()
    path = Path(args.transcript)
    session = json.loads(path.read_text(encoding="utf-8"))
    report = score_transcript(session)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(_radar(report["dimensions"]))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
