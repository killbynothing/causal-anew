# -*- coding: utf-8 -*-
"""Alignment side-track: jsonl schema. Torch fit is optional."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_preference_head import run_dry, run_fit
from scripts.pipeline.build_preference_pairs import DEFAULT_OUT, PAIRS, load_jsonl, write_jsonl


def test_write_and_schema():
    path = write_jsonl(DEFAULT_OUT)
    rows = load_jsonl(path)
    assert len(rows) == len(PAIRS)
    ids = {r["id"] for r in rows}
    assert "no_thought_leak" in ids
    assert "no_spoiler" in ids
    assert run_dry(path) == 0


def test_optional_torch_fit_or_skip():
    write_jsonl(DEFAULT_OUT)
    rc = run_fit(DEFAULT_OUT)
    assert rc == 0


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
