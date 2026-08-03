#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_pipeline.py -- Loop B: digital-person prompt assembly pipeline.

This module keeps persona presentation separate from truth/timeline gating:
persona markdown controls what can be shown to the model at a relationship
stage, while SQLite knowledge/canon tables still decide what the NPC knows.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONAS_DIR = ROOT / "runtime" / "personas"
DEFAULT_DB = ROOT / "data" / "world_truth.db"

SECRET_RE = re.compile(
    r"<!--\s*SECRET\s+level\s*=\s*(\d+)\s*-->(.*?)<!--\s*/SECRET\s*-->",
    re.DOTALL | re.IGNORECASE,
)

STAGE_LEVEL = {
    "stranger": 0,
    "acquaintance": 1,
    "trusted": 2,
    "core": 3,
}


def _table_cols(cur: sqlite3.Cursor, table: str) -> list[str]:
    try:
        return [row[1] for row in cur.execute(f'PRAGMA table_info("{table}")')]
    except sqlite3.Error:
        return []


def _connect(db_path: str | os.PathLike[str] | None) -> sqlite3.Connection | None:
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.exists():
        return None
    return sqlite3.connect(path)


def _parse_ch(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


def _strip_secret_blocks(text: str) -> tuple[str, list[tuple[int, str]]]:
    layers: list[tuple[int, str]] = []

    def repl(match: re.Match[str]) -> str:
        layers.append((int(match.group(1)), match.group(2).strip()))
        return ""

    surface = SECRET_RE.sub(repl, text).strip()
    return surface, layers


def resolve_persona(
    cons: str,
    relationship_stage: str,
    personas_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return persona text visible at a relationship stage."""
    stage = relationship_stage if relationship_stage in STAGE_LEVEL else "stranger"
    max_level = STAGE_LEVEL[stage]
    pdir = Path(personas_dir) if personas_dir else DEFAULT_PERSONAS_DIR
    path = pdir / f"{cons}.md"

    if not path.exists():
        return {
            "cons": cons,
            "stage": stage,
            "text": f"（{cons} 暂无可呈现人设；只以当前场景与已解锁知识回应。）",
            "layers": [],
            "source": str(path),
            "missing": True,
        }

    raw = path.read_text(encoding="utf-8")
    surface, layers = _strip_secret_blocks(raw)
    visible_layers = [(level, body) for level, body in layers if level <= max_level]
    parts = [surface] + [body for _, body in sorted(visible_layers, key=lambda x: x[0])]
    return {
        "cons": cons,
        "stage": stage,
        "text": "\n\n".join(part for part in parts if part).strip(),
        "layers": [level for level, _ in visible_layers],
        "source": str(path),
        "missing": False,
    }


def resolve_knowledge(
    cons: str,
    ch: int,
    db_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Read truth/timeline gates from knowledge_schedule + propositions."""
    db = _connect(db_path)
    if db is None:
        return {"cons": cons, "ch": ch, "unlocked": [], "locked": [], "db_available": False}
    try:
        cur = db.cursor()
        q = """
            SELECT p.prop_id, p.statement, k.learn_ch
            FROM knowledge_schedule k
            JOIN propositions p ON p.prop_id = k.prop_id
            WHERE k.cons_id=?
        """
        unlocked: list[dict[str, Any]] = []
        locked: list[dict[str, Any]] = []
        for prop_id, statement, learn_ch in cur.execute(q, (cons,)):
            row = {"prop_id": prop_id, "statement": statement, "learn_ch": _parse_ch(learn_ch)}
            if row["learn_ch"] is not None and row["learn_ch"] <= ch:
                unlocked.append(row)
            else:
                locked.append(row)
        return {"cons": cons, "ch": ch, "unlocked": unlocked, "locked": locked, "db_available": True}
    finally:
        db.close()


def resolve_voice(
    cons: str,
    ch_range: tuple[int, int],
    relationship_stage: str,
    db_path: str | os.PathLike[str] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Return chapter-filtered canon voice examples, never for strangers."""
    stage = relationship_stage if relationship_stage in STAGE_LEVEL else "stranger"
    if stage == "stranger":
        return {"cons": cons, "stage": stage, "quotes": [], "db_available": True}

    db = _connect(db_path)
    if db is None:
        return {"cons": cons, "stage": stage, "quotes": [], "db_available": False}

    start, end = ch_range
    try:
        cur = db.cursor()
        cols = _table_cols(cur, "canon_locks")
        if "speaker_cons" not in cols or "locked_text" not in cols:
            return {"cons": cons, "stage": stage, "quotes": [], "db_available": True}

        ch_col = next((c for c in ("ch_ref", "chapter", "ch") if c in cols), None)
        selected = ["locked_text"] + ([ch_col] if ch_col else [])
        rows = cur.execute(
            f"SELECT {', '.join(selected)} FROM canon_locks WHERE speaker_cons=? AND length(locked_text)>=2",
            (cons,),
        ).fetchall()
        quotes = []
        for row in rows:
            text = row[0]
            quote_ch = _parse_ch(row[1]) if ch_col else None
            if quote_ch is None or start <= quote_ch <= end:
                quotes.append({"text": text, "ch": quote_ch})
            if len(quotes) >= limit:
                break
        return {"cons": cons, "stage": stage, "quotes": quotes, "db_available": True}
    finally:
        db.close()


def resolve_scene(scene_config: dict[str, Any] | None) -> dict[str, Any]:
    """Render current scene and stranger introduction constraints."""
    cfg = scene_config or {}
    stage = cfg.get("player_stage") or cfg.get("relationship_stage") or "stranger"
    present = cfg.get("present_characters") or []
    present_text = "、".join(
        item.get("name") or item.get("cons") or "陌生人"
        for item in present
        if isinstance(item, dict)
    )
    lines = [
        f"地点: {cfg.get('location', '未知地点')}",
        f"当前事件: {cfg.get('current_beat', '暂无明确事件。')}",
    ]
    if present_text:
        lines.append(f"在场人物: {present_text}")

    if stage == "stranger":
        cover = cfg.get("cover_identity") or {}
        taboo = cfg.get("taboo_list") or []
        lines.extend(
            [
                "初遇协议: 你不认识面前这个人，只能依据外貌、当下行为和场景谨慎回应。",
                f"伪装身份: {cover.get('name', '普通旅人')}；{cover.get('backstory', '不主动披露私人背景。')}",
                "绝对禁忌: " + ("、".join(taboo) if taboo else "未解锁真相与私人底牌"),
                "名字规则: 对方未主动建立关系前，不叫出对方名字，不以熟人自居。",
            ]
        )
    return {"stage": stage, "text": "\n".join(lines), "config": cfg}


def _knowledge_lines(rows: Iterable[dict[str, Any]]) -> list[str]:
    return [f"- [{r.get('prop_id')}] {r.get('statement')}" for r in rows]


def compose(
    persona: dict[str, Any],
    knowledge: dict[str, Any],
    voice: dict[str, Any],
    scene: dict[str, Any],
    fsm: Any = None,
    anchors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose final prompt sections in a deterministic order."""
    anchors = anchors or []
    fsm_state = getattr(fsm, "state", "unknown")
    fsm_trust = getattr(fsm, "trust", "?")
    fsm_alert = getattr(fsm, "alert", "?")
    fsm_intimacy = getattr(fsm, "intimacy", "?")

    sections = [
        ("persona", "# 角色表层与关系可见层\n" + (persona.get("text") or "（无）")),
        (
            "knowledge",
            "# 真值库时间线门控\n"
            + "\n".join(_knowledge_lines(knowledge.get("unlocked", [])) or ["- （此刻无已解锁命题）"]),
        ),
        (
            "voice",
            "# 正典语气参考\n"
            + "\n".join(f"- {q['text']}" for q in voice.get("quotes", [])) if voice.get("quotes") else "# 正典语气参考\n- （初遇或无可用章节台词，不注入语癖）",
        ),
        (
            "fsm",
            "# 运行时关系状态\n"
            f"- State: {fsm_state}\n- Trust: {fsm_trust}\n- Alert: {fsm_alert}\n- Intimacy: {fsm_intimacy}",
        ),
        ("scene", "# 近因场景注入 depth=4\n" + (scene.get("text") or "（无场景）")),
        (
            "output",
            '# 输出协议\n只输出一个 JSON 对象: {"Meta_State": {...}, "Response": {"stage_direction": "...", "dialogue": "..."}}',
        ),
    ]
    system_prompt = "\n\n".join(text for _, text in sections)
    return {
        "system_prompt": system_prompt,
        "sections": [{"name": name, "text": text} for name, text in sections],
        "locked": knowledge.get("locked", []),
        "anchors": anchors,
    }
