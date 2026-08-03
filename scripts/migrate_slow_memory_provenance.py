# -*- coding: utf-8 -*-
"""Migrate canon-sourced slow memories without confusing disclosure time with ownership time."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "world_truth.db"
ZHANGCHEN = "C.zhangchen.WMAIN"

# These four unsourced prototype assets were either fabricated, premature, or not core memory.
OBSOLETE_ANCHORS = (
    "十六中正门地砖/冰冷",
    "肖羽的血腥味/风",
    "雷切的高温/窒息",
    "鼻梁矫正/钝痛",
)

# available_ch is character ownership time. event_uid is provenance/disclosure evidence.
# projection_text is the actor-safe early projection; reveal_ch unlocks canonical text to actors.
CANON_MEMORIES = (
    {
        "anchor": "苏颖生前/鲜明日常",
        "text": "苏颖很漂亮，学习一般，爱八卦，人缘却特别好；她叫他“阿尘”的声音，是那段普通日常里最鲜明的一部分。",
        "salience": 0.96,
        "emo_tag": "warmth_grief_fork",
        "event_uid": "E059-03",
        "available_ch": 0,
        "projection_text": "有个爱说笑、在人群里总不缺朋友的女孩留下的日常碎片，偶尔会让他在笑声里短暂停一下。",
        "reveal_ch": 59,
    },
    {
        "anchor": "苏颖最后来电/坠楼",
        "text": "世界政府的电话追逼把他压到近乎崩溃；他烦躁地挂断苏颖的来电，那成了最后一次听见她的声音。后来苏颖从十六中坠楼，而他知道是龙也把她推了下去。",
        "salience": 1.0,
        "emo_tag": "grief_guilt_rage",
        "event_uid": "E059-03",
        "available_ch": 0,
        "projection_text": "急促的电话铃、没来得及好好说完的一句话，和校门口冷雨贴在皮肤上的感觉，会让他的笑意忽然变薄。",
        "reveal_ch": 59,
    },
    {
        "anchor": "封闭囚禁/两年逃出",
        "text": "他曾被带进一个封闭的地方，被逼着写完全不想写的东西；用了两年才找到逃出的办法，之后又在各处游荡逃命。",
        "salience": 0.99,
        "emo_tag": "captivity_despair",
        "event_uid": "E029-04",
        "available_ch": 0,
        "projection_text": "封闭房间的白光、写不完的纸页和长期睡不安稳的警觉，仍会让他本能地先找出口。",
        "reveal_ch": 29,
    },
)


def _event_ids_by_uid(conn: sqlite3.Connection) -> dict[str, int]:
    wanted = {item["event_uid"] for item in CANON_MEMORIES}
    found: dict[str, int] = {}
    for event_id, run, payload in conn.execute("SELECT event_id, run, payload FROM events WHERE run=0"):
        try:
            uid = str(json.loads(payload or "{}").get("event_uid") or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if uid in wanted:
            found[uid] = int(event_id)
    missing = sorted(wanted - set(found))
    if missing:
        raise RuntimeError(f"missing slow-memory provenance events: {', '.join(missing)}")
    return found


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(slow_memory)")}
        for column, ddl in (
            ("available_ch", "INTEGER"),
            ("projection_text", "TEXT"),
            ("reveal_ch", "INTEGER"),
        ):
            if column not in columns:
                conn.execute(f"ALTER TABLE slow_memory ADD COLUMN {column} {ddl}")

        event_ids = _event_ids_by_uid(conn)
        placeholders = ",".join("?" for _ in OBSOLETE_ANCHORS)
        conn.execute(
            f"DELETE FROM slow_memory WHERE run=0 AND cons_id=? AND anchor IN ({placeholders})",
            (ZHANGCHEN, *OBSOLETE_ANCHORS),
        )
        for item in CANON_MEMORIES:
            existing = conn.execute(
                "SELECT mem_id FROM slow_memory WHERE run=0 AND cons_id=? AND anchor=?",
                (ZHANGCHEN, item["anchor"]),
            ).fetchone()
            values = (
                item["text"],
                float(item["salience"]),
                item["emo_tag"],
                event_ids[item["event_uid"]],
                int(item["available_ch"]),
                item["projection_text"],
                int(item["reveal_ch"]),
            )
            if existing:
                conn.execute(
                    """
                    UPDATE slow_memory
                    SET text=?, salience=?, emo_tag=?, src_event=?, available_ch=?, projection_text=?, reveal_ch=?
                    WHERE mem_id=?
                    """,
                    (*values, int(existing[0])),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO slow_memory
                        (run, cons_id, text, anchor, salience, emo_tag, src_event, available_ch, projection_text, reveal_ch)
                    VALUES (0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ZHANGCHEN,
                        item["text"],
                        item["anchor"],
                        float(item["salience"]),
                        item["emo_tag"],
                        event_ids[item["event_uid"]],
                        int(item["available_ch"]),
                        item["projection_text"],
                        int(item["reveal_ch"]),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    migrate(db_path)
    print(f"[OK] sourced slow-memory migration applied: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
