#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1 contract: a real session save must not write to the canonical truth DB."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.free_stage_prototype import FreeStageSession


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_save_keeps_truth_db_readonly() -> None:
    truth_db = ROOT / "data" / "world_truth.db"
    before = digest(truth_db)
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        runtime_db = temp / "runtime_state.db"
        session = FreeStageSession(
            session_id="g1-truth-readonly",
            card_path=ROOT / "runtime" / "free_stage_card_highway.json",
            state_dir=temp / "sessions",
            runtime_state_path=runtime_db,
            load_existing=False,
            caller=lambda **_: json.dumps({"turns": [], "mh_progress": [], "director_note": "test"}),
        )
        session.branch_progress.append("choiceA_brace")
        session.save()
        assert digest(truth_db) == before
        assert runtime_db.exists()


if __name__ == "__main__":
    test_real_save_keeps_truth_db_readonly()
    print("PASS world truth remains readonly across real session save")
