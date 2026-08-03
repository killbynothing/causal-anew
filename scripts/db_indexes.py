#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared secondary indexes for world_truth.db hot paths."""
from __future__ import annotations

import sqlite3

INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_canon_locks_speaker_cons ON canon_locks(speaker_cons)",
    "CREATE INDEX IF NOT EXISTS idx_slow_memory_cons_id ON slow_memory(cons_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_ch_anchor ON events(ch_anchor)",
]


def ensure_indexes(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for ddl in INDEX_DDL:
        # import_db 先建立核心身份表，events 由后续转录管线创建；
        # 不能因为延后表不存在而留下半成品真值库。
        if " ON events(" in ddl:
            exists = cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            if not exists:
                continue
        cur.execute(ddl)
    conn.commit()
