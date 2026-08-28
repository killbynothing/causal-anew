# -*- coding: utf-8 -*-
"""刀 4：EndRun 结算单。幂等关局、固定底仍挡、回执无情感、reset 不关周目。"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.delta_db import append_delta_rows
from runtime.end_run import close_run
from runtime.run_registry import open_run

DDL = """
CREATE TABLE delta_ledger(
  delta_id INTEGER PRIMARY KEY, run INTEGER NOT NULL, node_id TEXT,
  description TEXT, converged INTEGER DEFAULT 0, emo_tag TEXT, src_event INTEGER);
CREATE TABLE delta_sediment (
  sid INTEGER PRIMARY KEY,
  node_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  cons_id TEXT,
  weight REAL NOT NULL,
  src_run INTEGER NOT NULL,
  src_delta TEXT NOT NULL,
  revoked INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  CHECK (kind IN ('precedent', 'scar', 'unlock', 'witness')),
  CHECK (src_run >= 1),
  CHECK (revoked IN (0, 1))
);
CREATE TABLE run_meta (
  run INTEGER PRIMARY KEY,
  parent_run INTEGER NOT NULL,
  kind TEXT NOT NULL,
  fork_event TEXT,
  inherit_level INTEGER NOT NULL,
  player_line TEXT NOT NULL DEFAULT 'a_qi',
  opening_id TEXT,
  player_profile_hash TEXT,
  opened_at TEXT,
  closed_at TEXT,
  final_delta_summary TEXT
);
CREATE TABLE causal_constants (
  const_id   TEXT PRIMARY KEY,
  prop_id    TEXT,
  lock_type  TEXT,
  dependency_chain TEXT NOT NULL,
  canon_src  TEXT
);
"""


def _temp_db(tmp: Path) -> Path:
    path = tmp / "truth.db"
    con = sqlite3.connect(str(path))
    con.executescript(DDL)
    con.commit()
    con.close()
    open_run(path, opening_id="pline_ryuya_cafe", player_line="aqi")
    return path


def _exit_event(run_no: int = 1) -> dict:
    return {
        "type": "normal_exit",
        "run_no": run_no,
        "scene_id": "RYUYA_CAFE_PROLOGUE",
        "desc": "normal_exit: mh 已全齐(RP1, RP3)，玩家正常离场",
        "verdict": "normal_exit_recorded",
        "emo_tag": "grief",
    }


def test_close_run_writes_receipt_without_emotion(tmp_path):
    db = _temp_db(tmp_path)
    append_delta_rows(db, [_exit_event()])
    sheet = close_run(db, 1, opening_id="pline_ryuya_cafe")
    assert sheet["run"] == 1
    assert sheet["opening_id"] == "pline_ryuya_cafe"
    assert sheet["closed_at"]
    assert sheet["n_delta"] >= 1
    assert sheet["done"][0]["node_id"] == "RYUYA_CAFE_PROLOGUE"
    assert "mh 已全齐" in sheet["done"][0]["text"]
    blob = json.dumps(sheet, ensure_ascii=False)
    assert "感动" not in blob
    assert "emo_tag" not in blob
    con = sqlite3.connect(str(db))
    try:
        closed = con.execute("SELECT closed_at FROM run_meta WHERE run=1").fetchone()[0]
        n_sed = con.execute("SELECT COUNT(*) FROM delta_sediment WHERE src_run=1").fetchone()[0]
    finally:
        con.close()
    assert closed
    assert n_sed == sheet["n_sediment"]


def test_close_run_is_idempotent(tmp_path):
    db = _temp_db(tmp_path)
    append_delta_rows(db, [_exit_event()])
    a = close_run(db, 1)
    b = close_run(db, 1)
    assert a["closed_at"] == b["closed_at"]
    con = sqlite3.connect(str(db))
    try:
        n_meta = con.execute("SELECT COUNT(*) FROM run_meta").fetchone()[0]
        n_sed = con.execute("SELECT COUNT(*) FROM delta_sediment WHERE src_run=1").fetchone()[0]
    finally:
        con.close()
    assert n_meta == 1
    assert n_sed == a["n_sediment"] == b["n_sediment"]


def test_close_run_still_blocks_fixed_bottom(tmp_path):
    db = _temp_db(tmp_path)
    con = sqlite3.connect(str(db))
    con.execute(
        "INSERT INTO causal_constants VALUES ('CC.TEST', NULL, 'self_reference', "
        "'[\"FIXED_NODE\"]', 'test')"
    )
    con.commit()
    con.close()
    append_delta_rows(
        db,
        [
            {
                "type": "violation",
                "run_no": 1,
                "scene_id": "FIXED_NODE",
                "desc": "try soften fixed bottom",
                "emo_tag": "grief",
            }
        ],
    )
    sheet = close_run(db, 1)
    assert sheet["n_rejected_fixed"] == 1
    assert sheet["n_sediment"] == 0
    assert sheet["rejected_fixed"][0]["node_id"] == "FIXED_NODE"


def test_close_run_refuses_run_zero(tmp_path):
    db = _temp_db(tmp_path)
    try:
        close_run(db, 0)
        raise AssertionError("run=0 must not close")
    except ValueError:
        pass


def test_session_end_closes_run_reset_does_not(tmp_path):
    from runtime import free_stage_prototype as proto

    db = _temp_db(tmp_path)
    append_delta_rows(db, [_exit_event()])
    session = proto.FreeStageSession(
        session_id="end-run",
        state_dir=tmp_path / "sessions",
        load_existing=False,
        run_no=1,
        truth_db=db,
        caller=lambda **_: '{"turns":[],"mh_progress":[],"director_note":"t"}',
    )
    session._mark_ended()
    assert session.ended
    assert session.run_receipt["run"] == 1
    con = sqlite3.connect(str(db))
    try:
        closed = con.execute("SELECT closed_at FROM run_meta WHERE run=1").fetchone()[0]
        n_before = con.execute("SELECT COUNT(*) FROM run_meta").fetchone()[0]
    finally:
        con.close()
    assert closed
    session.reset()
    con = sqlite3.connect(str(db))
    try:
        n_after = con.execute("SELECT COUNT(*) FROM run_meta").fetchone()[0]
        still_closed = con.execute("SELECT closed_at FROM run_meta WHERE run=1").fetchone()[0]
    finally:
        con.close()
    assert n_before == n_after == 1
    assert still_closed
    assert session.ended is False


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        fn = globals()[name]
        if "tmp_path" in fn.__code__.co_varnames:
            with tempfile.TemporaryDirectory() as tmp:
                fn(Path(tmp))
        else:
            fn()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
