# -*- coding: utf-8 -*-
"""刀 3：δ 事件进 delta_ledger 表。双写、幂等、run=0 拒绝、settle 能消费、固定底仍挡。"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.delta_db import append_delta_rows, dual_write_delta_events
from scripts.settle_run import settle

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
    con.execute(
        "INSERT INTO run_meta (run, parent_run, kind, inherit_level, player_line, opened_at) "
        "VALUES (1, 0, 'fresh', 0, 'a_qi', '2026-08-28T00:00:00Z')"
    )
    con.commit()
    con.close()
    return path


def _normal_exit_event() -> dict:
    return {
        "type": "normal_exit",
        "run_no": 1,
        "scene_id": "OPENING_TIANANMEN_002",
        "ch_anchor": 8,
        "desc": "normal_exit: mh 已全齐(TM1, TM2, TM3, TM4)，玩家正常离场",
        "delta": 0.0,
        "severity": 0,
        "handled": "normal",
        "verdict": "normal_exit_recorded",
        "ts": "2026-08-28T12:00:00",
    }


def _violation_event() -> dict:
    return {
        "type": "violation",
        "run_no": 1,
        "scene_id": "RYUYA_CAFE_PROLOGUE",
        "desc": "physical:physical_breach",
        "severity": 2,
        "handled": "blocked",
        "verdict": "violation_handled",
        "ts": "2026-08-28T12:01:00",
    }


def test_append_maps_fields(tmp_path):
    db = _temp_db(tmp_path)
    n = append_delta_rows(db, [_normal_exit_event(), _violation_event()])
    assert n == 2
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM delta_ledger ORDER BY delta_id").fetchall()
    finally:
        con.close()
    assert len(rows) == 2
    exit_row, vio_row = rows
    assert exit_row["run"] == 1
    assert exit_row["node_id"] == "OPENING_TIANANMEN_002"
    assert exit_row["converged"] == 1  # normal_exit = 做成的事
    assert vio_row["converged"] == 0
    payload = json.loads(exit_row["description"])
    assert payload["verdict"] == "normal_exit_recorded"  # 富 JSON 完整保留


def test_append_is_idempotent(tmp_path):
    db = _temp_db(tmp_path)
    assert append_delta_rows(db, [_normal_exit_event()]) == 1
    assert append_delta_rows(db, [_normal_exit_event()]) == 0
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM delta_ledger").fetchone()[0]
    finally:
        con.close()
    assert n == 1


def test_append_refuses_run_zero(tmp_path):
    db = _temp_db(tmp_path)
    bad = _normal_exit_event()
    bad["run_no"] = 0
    try:
        append_delta_rows(db, [_normal_exit_event(), bad])
        raise AssertionError("run=0 must be refused")
    except ValueError:
        pass
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM delta_ledger").fetchone()[0]
    finally:
        con.close()
    assert n == 0  # 整批拒绝，不留半批


def test_settle_consumes_ledger_rows(tmp_path):
    db = _temp_db(tmp_path)
    scar = _violation_event()
    scar["emo_tag"] = "fear"
    append_delta_rows(db, [_normal_exit_event(), scar])
    con = sqlite3.connect(str(db))
    try:
        out = settle(con, 1, apply=False)
    finally:
        con.close()
    assert out["run"] == 1
    assert out["n_delta"] == 2
    assert out["applied"] is False
    kinds = {item["kind"] for item in out["sediment"]}
    assert "scar" in kinds  # 带 emo_tag 的 δ 沉淀为疤


def test_settle_fixed_bottom_still_blocks(tmp_path):
    db = _temp_db(tmp_path)
    con = sqlite3.connect(str(db))
    con.execute(
        "INSERT INTO causal_constants VALUES ('CC.TEST', NULL, 'self_reference', "
        "'[\"FIXED_NODE\"]', 'test')"
    )
    con.commit()
    con.close()
    fixed = _violation_event()
    fixed["scene_id"] = "FIXED_NODE"
    fixed["emo_tag"] = "grief"
    append_delta_rows(db, [fixed])
    con = sqlite3.connect(str(db))
    try:
        out = settle(con, 1, apply=False)
    finally:
        con.close()
    assert out["n_rejected_fixed"] == 1
    assert out["n_sediment"] == 0  # 固定底不软化


def test_free_stage_wrapper_dual_writes(tmp_path):
    from runtime import free_stage_prototype as proto

    db = _temp_db(tmp_path)
    ledger = tmp_path / "delta_ledger.json"
    original = proto.WORLD_TRUTH_DB_PATH
    proto.WORLD_TRUTH_DB_PATH = db
    try:
        proto.append_delta_events(ledger, [_normal_exit_event()])
    finally:
        proto.WORLD_TRUTH_DB_PATH = original
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(data) == 1  # JSON 追溯件照旧
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM delta_ledger WHERE run=1").fetchone()[0]
    finally:
        con.close()
    assert n == 1  # 库表同步有账


def test_wrapper_refuses_run_zero(tmp_path):
    db = _temp_db(tmp_path)
    ledger = tmp_path / "delta_ledger.json"
    bad = _normal_exit_event()
    bad["run_no"] = 0
    try:
        dual_write_delta_events(ledger, [bad], db)
        raise AssertionError("run=0 must be refused")
    except ValueError:
        pass
    assert not ledger.exists()
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM delta_ledger").fetchone()[0]
    finally:
        con.close()
    assert n == 0


def test_dump_treats_playtime_delta_tables_as_mutable():
    import importlib.util

    path = ROOT / "scripts" / "verify_db_rebuild_from_dump.py"
    spec = importlib.util.spec_from_file_location("verify_db_rebuild_from_dump", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert {"run_meta", "delta_ledger", "delta_sediment"} <= set(mod.MUTABLE_TABLES)


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
