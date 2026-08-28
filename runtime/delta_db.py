# -*- coding: utf-8 -*-
"""刀 3：δ 事件进 world_truth.db 的 delta_ledger 表（只追加，run>=1）。

映射（不改 schema，富 JSON 整体进 description）：
  run         ← event.run_no
  node_id     ← event.scene_id（缺省 event.node）
  description ← json.dumps(event)
  converged   ← 1 当 type == "normal_exit"，否则 0
  emo_tag     ← event.emo_tag（可缺省）
  src_event   ← NULL（正典 event 关联是刀 4+ 的事）

settle_run.py 直接消费本表。web/delta_ledger.json 保留为人读追溯件（双写）。
玩时表不进 world_truth.sql 指纹（见 verify_db_rebuild_from_dump.MUTABLE_TABLES）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _event_row(event: dict[str, Any]) -> tuple[int, str, str, int, str | None]:
    raw_run = event.get("run_no", 1)
    run_no = int(1 if raw_run is None or raw_run == "" else raw_run)
    node_id = str(event.get("scene_id") or event.get("node") or "")
    description = json.dumps(event, ensure_ascii=False, sort_keys=True)
    converged = 1 if str(event.get("type", "")) == "normal_exit" else 0
    emo_tag = event.get("emo_tag") or None
    return run_no, node_id, description, converged, emo_tag


def append_delta_rows(db_path: Path | str, events: list[dict[str, Any]]) -> int:
    """把 δ 事件追加进 delta_ledger 表，返回新增行数。

    run=0 正典只读，整批拒绝；按 (run, description) 精确查重保证幂等。
    """
    if not events:
        return 0
    rows = [_event_row(event) for event in events]
    if any(run_no < 1 for run_no, *_ in rows):
        raise ValueError("run=0 is read-only; delta_ledger only accepts run>=1")

    con = sqlite3.connect(str(db_path))
    inserted = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        for run_no, node_id, description, converged, emo_tag in rows:
            dup = con.execute(
                "SELECT 1 FROM delta_ledger WHERE run=? AND description=? LIMIT 1",
                (run_no, description),
            ).fetchone()
            if dup is not None:
                continue
            con.execute(
                "INSERT INTO delta_ledger (run, node_id, description, converged, emo_tag, src_event) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (run_no, node_id, description, converged, emo_tag),
            )
            inserted += 1
        con.commit()
        return inserted
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def dual_write_delta_events(
    ledger_path: Path | str,
    events: list[dict[str, Any]],
    db_path: Path | str,
) -> list[dict[str, Any]]:
    """JSON 追溯件照旧 + 库表为 settle 权威输入。

    库写失败不中断游玩（账本缺一条 < 玩家断线），只记警告。
    JSON 层先拒 run=0，库层再拒一次。
    """
    from scene_delta import append_delta_events as append_json

    data = append_json(ledger_path, events)
    try:
        append_delta_rows(db_path, events)
    except Exception as exc:
        print(f"[delta_db] WARN δ 进库失败（游玩不中断）: {exc}")
    return data
