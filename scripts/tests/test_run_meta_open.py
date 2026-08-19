# -*- coding: utf-8 -*-
"""刀 2：开局写 run_meta，run 递增。reset 不是新周目。session.save 不写真值库。"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SERVER_DIR = ROOT / "web"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from runtime import run_registry
from runtime import free_stage_prototype as proto
import server

DDL_RUN_META = """
CREATE TABLE IF NOT EXISTS run_meta (
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
  final_delta_summary TEXT,
  CHECK (run >= 1),
  CHECK (kind IN ('fresh', 'beta', 'fork')),
  CHECK (inherit_level IN (0, 1, 2))
);
"""


def _temp_run_db(tmp: Path) -> Path:
    path = tmp / "run_meta.db"
    con = sqlite3.connect(str(path))
    con.executescript(DDL_RUN_META)
    con.commit()
    con.close()
    return path


def test_open_run_starts_at_one_and_increments(tmp_path):
    db = _temp_run_db(tmp_path)
    a = run_registry.open_run(db, opening_id="pline_ryuya_cafe", player_line="aqi")
    b = run_registry.open_run(db, opening_id="aline_tiananmen", player_line="aqi")
    assert a["run"] == 1
    assert b["run"] == 2
    assert a["kind"] == "fresh"
    assert a["parent_run"] == 0
    assert a["inherit_level"] == 0
    assert a["closed_at"] is None
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute("SELECT run FROM run_meta ORDER BY run").fetchall()
    finally:
        con.close()
    assert [r[0] for r in rows] == [1, 2]


def test_open_run_refuses_run_zero(tmp_path):
    db = _temp_run_db(tmp_path)
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO run_meta (run, parent_run, kind, inherit_level, player_line, opened_at) "
            "VALUES (0, 0, 'fresh', 0, 'a_qi', '2026-08-17T00:00:00Z')"
        )
        con.commit()
        raise AssertionError("run=0 insert must fail CHECK")
    except sqlite3.IntegrityError:
        pass
    finally:
        con.close()
    row = run_registry.open_run(db, opening_id="pline_ryuya_cafe")
    assert row["run"] == 1


def test_create_session_registers_incrementing_runs(tmp_path):
    db = _temp_run_db(tmp_path)
    config = {"api_key": "", "api_url": "", "model": "mock"}
    first = server.handle_free_stage_request(
        {
            "op": "create_session",
            "session_id": "run-a",
            "opening_id": "pline_ryuya_cafe",
            "player_template_id": "aqi",
        },
        config,
        state_dir=tmp_path,
        caller=proto.fixed_selftest_actor,
        truth_db=db,
    )
    second = server.handle_free_stage_request(
        {
            "op": "create_session",
            "session_id": "run-b",
            "opening_id": "aline_tiananmen",
            "player_template_id": "aqi",
        },
        config,
        state_dir=tmp_path,
        caller=proto.fixed_selftest_actor,
        truth_db=db,
    )
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["run_no"] == 1
    assert second["run_no"] == 2
    assert first["surface"]["run"] == 1
    stored = proto.FreeStageSession(
        session_id="run-a",
        state_dir=tmp_path,
        config=config,
        caller=proto.fixed_selftest_actor,
    )
    assert stored.run_no == 1
    assert stored.world_cursor["run"] == 1


def test_resume_keeps_run_and_reset_does_not_open_another(tmp_path):
    db = _temp_run_db(tmp_path)
    config = {"api_key": "", "api_url": "", "model": "mock"}
    created = server.handle_free_stage_request(
        {
            "op": "create_session",
            "session_id": "keep-run",
            "opening_id": "pline_ryuya_cafe",
            "player_template_id": "aqi",
        },
        config,
        state_dir=tmp_path,
        caller=proto.fixed_selftest_actor,
        truth_db=db,
    )
    assert created["run_no"] == 1
    session = proto.FreeStageSession(
        session_id="keep-run",
        state_dir=tmp_path,
        config=config,
        caller=proto.fixed_selftest_actor,
    )
    session.reset()
    session.save()
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM run_meta").fetchone()[0]
    finally:
        con.close()
    assert n == 1
    resumed = proto.FreeStageSession(
        session_id="keep-run",
        state_dir=tmp_path,
        config=config,
        caller=proto.fixed_selftest_actor,
    )
    assert resumed.run_no == 1


def test_session_save_does_not_write_run_meta(tmp_path):
    db = _temp_run_db(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    session = proto.FreeStageSession(
        session_id="g1-run-meta",
        state_dir=tmp_path / "sessions",
        runtime_state_path=tmp_path / "runtime_state.db",
        load_existing=False,
        caller=lambda **_: '{"turns":[],"mh_progress":[],"director_note":"test"}',
    )
    session.branch_progress.append("choiceA_brace")
    session.save()
    after = hashlib.sha256(db.read_bytes()).hexdigest()
    assert before == after
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM run_meta").fetchone()[0]
    finally:
        con.close()
    assert n == 0


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
