# -*- coding: utf-8 -*-
"""Rubric five dimensions: golden fixtures must hang where expected."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.narrative_rubric import score_transcript
from scripts.eval_narrative_rubric import FIXTURE, load_cases, run_smoke


def test_fixture_file_exists():
    assert FIXTURE.is_file()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data.get("cases") or []) >= 5


def test_smoke_cli_pass():
    assert run_smoke() == 0


def test_each_case_expectations():
    for case in load_cases():
        report = score_transcript(case["session"])
        dims = report["dimensions"]
        for dim in case.get("expect_fail") or []:
            assert dims[dim]["pass"] is False, (case["id"], dim, dims[dim])
        for dim in case.get("expect_pass") or []:
            assert dims[dim]["pass"] is True, (case["id"], dim, dims[dim])


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
