#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild-time C16 truth corrections, sourced from Ch13-20 and the novel."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "world_truth.db"


def _load_event(conn: sqlite3.Connection, uid: str) -> tuple[int, dict]:
    for event_id, payload in conn.execute("SELECT event_id, payload FROM events WHERE run=0"):
        data = json.loads(payload)
        if data.get("event_uid") == uid:
            return int(event_id), data
    raise RuntimeError(f"missing run=0 event: {uid}")


def _write_event(
    conn: sqlite3.Connection,
    uid: str,
    *,
    location: str,
    witnesses: list[str],
    action: str,
    canon_src: str,
) -> None:
    event_id, payload = _load_event(conn, uid)
    payload["witnesses"] = witnesses
    payload["action"] = action
    payload["canon_src"] = canon_src
    payload["intervention_flag"] = ""
    conn.execute(
        "UPDATE events SET location_id=?, payload=? WHERE event_id=? AND run=0",
        (location, json.dumps(payload, ensure_ascii=False), event_id),
    )


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        _write_event(
            conn,
            "E015-05",
            location="快乐柠檬",
            witnesses=["C.zhangchen.WMAIN", "C.banbo.WMAIN", "C.yuxuan.WMAIN"],
            action="张尘在奶茶店重逢斑驳和雨璇并请吃布丁，魏初在暗中观察",
            canon_src="n1-69:L4656-4673",
        )
        _write_event(
            conn,
            "E016-04",
            location="快乐柠檬",
            witnesses=["C.zhangchen.WMAIN", "C.banbo.WMAIN", "C.yuxuan.WMAIN"],
            action="雨璇接到电话得知潘父在高速车祸受伤，张尘安抚并协助判断，斑驳陪同前往医院",
            canon_src="n1-69:L4820-4868",
        )

        wrong = conn.execute(
            "SELECT lock_id, context FROM canon_locks WHERE locked_text=?",
            ("这算是，偶遇么？",),
        ).fetchall()
        correct = ("L.yuxuan.wmain.0001", "C.yuxuan.WMAIN")
        if wrong != [(correct[0], '“这算是，偶遇么？”雨璇抬起手来朝张尘打了个招呼。')]:
            conn.execute("DELETE FROM canon_locks WHERE locked_text=?", ("这算是，偶遇么？",))
            # Removing the misplaced quote from wmain_quotes shifts later generated IDs by one.
            zhang_rows = conn.execute(
                "SELECT lock_id FROM canon_locks WHERE lock_id LIKE 'L.zhangchen.wmain.%'"
            ).fetchall()
            numbered = sorted(
                (int(lock_id.rsplit(".", 1)[1]), lock_id)
                for (lock_id,) in zhang_rows
                if int(lock_id.rsplit(".", 1)[1]) > 20
            )
            for number, old_id in numbered:
                new_id = f"L.zhangchen.wmain.{number - 1:04d}"
                conn.execute("UPDATE canon_locks SET lock_id=? WHERE lock_id=?", (new_id, old_id))
            conn.execute(
                "INSERT OR REPLACE INTO canon_locks(lock_id,node_id,ch_ref,locked_text,context,speaker_cons) "
                "VALUES(?,?,?,?,?,?)",
                (
                    correct[0],
                    None,
                    15,
                    "这算是，偶遇么？",
                    '“这算是，偶遇么？”雨璇抬起手来朝张尘打了个招呼。',
                    correct[1],
                ),
            )
        else:
            conn.execute(
                "UPDATE canon_locks SET speaker_cons=? WHERE lock_id=?",
                (correct[1], correct[0]),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    migrate(Path(args.db))
    print("PASS migrate_c16_truth_provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
