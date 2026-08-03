#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界日历游标内核（P3 核心 · 纯函数、引擎零依赖）。

时间唯一真值 = 全局游标 cursor（住 session/player_state）。
时间维**只**由 `(ch_anchor, world_clock)` 决定；`run`(周目) 与 `worldline`(剧情宇宙)
与时间维**正交**，永不参与时间比较。

═══ 不变量（scripts/tests/test_world_calendar.py 红闸把守，生手必踩）═══
1. 维度分离：`time_key` 只吃 ch_anchor+world_clock。**拿 run 当时间轴**是 CLAUDE.md
   头号红线；同一时刻不同 run 的游标时间键必须相等（红样本 R1）。
2. 游标单调：转场只能前进或原地，**不得倒退**；backward advance 直接抛错（红样本 R2）。
3. 卡 clock 降级为「入场校验窗」：判断卡能否在当前游标进场，**不回写、不倒退游标**。
   进一张 clock 更早的卡（同帧不同视角，如医院 19:20 vs 22:40）游标不变（红样本 R3）。
4. 交接是数据不是旁白硬拽：handoff 规则 method 必须是「在场引导/偶然」，
   禁止 narrate_pull（把玩家硬拖回去），撞禁旁白硬拽红线（红样本 R4）。
5. 铁轨锚可达：任一落点必须能顺 handoff 图走到全线必到的铁轨锚（酒吧 E039）；
   落点不可达 = 死线，可达性 BFS 拦（红样本 R5）。

游标结构（session 可持久化、纯 JSON）：
    {"ch_anchor": 17, "world_clock": "22:40", "run": 1, "worldline": "WMAIN"}
world_clock 的正典绝对值（如 E016 车祸时刻）属 ⚠️ 待人裁，本内核不定值——
只依赖其结构性质（单调、窗内），故 22:40 vs 19:20 的悬案在机制层被窗吸收、不阻塞。
"""
from __future__ import annotations

from collections import deque
from typing import Any

TIME_DIMS = ("ch_anchor", "world_clock")
NON_TIME_DIMS = ("run", "worldline")
RAIL_ANCHOR = "E039_bar"  # 全线必到的铁轨锚（酒吧砸店），落点可达性的汇点
_ALLOWED_HANDOFF_METHODS = {"in_fiction_guided", "incidental"}  # 在场引导 / 偶然；禁 narrate_pull


def minutes(hhmm: str | None) -> int:
    if not hhmm:
        return 0
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def time_key(cursor: dict) -> tuple[int, int]:
    """时间维排序键。**只**含 ch_anchor + world_clock；刻意不含 run/worldline。"""
    return (int(cursor.get("ch_anchor", 0)), minutes(cursor.get("world_clock")))


def is_forward(old: dict, new: dict) -> bool:
    """new 相对 old 是否前进或原地（非倒退）。"""
    return time_key(new) >= time_key(old)


def advance(cursor: dict, ch_anchor: int | None = None, world_clock: str | None = None) -> dict:
    """转场推进游标。保留 run/worldline，只动时间维。倒退则抛错（不变量 2）。"""
    new = dict(cursor)
    if ch_anchor is not None:
        new["ch_anchor"] = ch_anchor
    if world_clock is not None:
        new["world_clock"] = world_clock
    if not is_forward(cursor, new):
        raise ValueError(
            f"游标不得倒退：{time_key(cursor)} → {time_key(new)}（run 不是时间轴，别拿它救场）"
        )
    return new


def with_run(cursor: dict, run: int) -> dict:
    """切周目：只改 run，时间键必须不变（证明 run ⊥ 时间）。"""
    new = dict(cursor)
    new["run"] = run
    return new


def admit_card(cursor: dict, card_clock: str | None, window: dict) -> bool:
    """卡能否在当前游标进场＝入场校验窗。卡 clock 落在帧窗内即可，
    **不要求游标等于卡 clock**（这正是 clock 降级的意义）。游标也须已进入该帧时段。"""
    lo, hi = minutes(window.get("start")), minutes(window.get("end"))
    c = minutes(card_clock)
    cur = minutes(cursor.get("world_clock"))
    card_in_window = lo <= c <= hi
    cursor_in_span = lo <= cur <= hi
    return card_in_window and cursor_in_span


def enter_card(cursor: dict, card_clock: str | None, window: dict) -> dict:
    """进场返回**原样游标**（不回写卡 clock、不倒退）。不可进场则抛错。"""
    if not admit_card(cursor, card_clock, window):
        raise ValueError(f"卡 clock {card_clock} 不在帧窗 {window} 或游标未到，拒绝进场")
    return dict(cursor)  # 关键：游标不因进一张更早的卡而改变


def entry_lit(cursor: dict, cond: dict) -> bool:
    """跨线 entry 是否被游标点亮。cond={'ch_anchor_min':int,'clock_min':'HH:MM'?}。"""
    ck = time_key(cursor)
    thr = (int(cond.get("ch_anchor_min", 0)), minutes(cond.get("clock_min")))
    return ck >= thr


def validate_handoff_rule(rule: dict) -> list[str]:
    """交接规则合法性；返回问题列表（空=合法）。核心拦 narrate_pull（不硬拽）。"""
    errs: list[str] = []
    when = rule.get("when") or {}
    if not when.get("source_line"):
        errs.append("缺 when.source_line")
    if not when.get("location"):
        errs.append("缺 when.location")
    win = when.get("ch_window")
    if not (isinstance(win, list) and len(win) == 2 and win[0] <= win[1]):
        errs.append(f"ch_window 非法或未升序: {win}")
    if not rule.get("lights"):
        errs.append("lights 为空（交接不点亮任何目标 entry 卡＝空转）")
    method = rule.get("method")
    if method not in _ALLOWED_HANDOFF_METHODS:
        errs.append(f"method {method!r} 非法：只允许在场引导/偶然，禁旁白硬拽 narrate_pull")
    return errs


def build_handoff_graph(rules: list[dict]) -> dict[str, set[str]]:
    """由 handoff 规则建有向图：source_line → 其 lights 指向的线/锚。"""
    graph: dict[str, set[str]] = {}
    for rule in rules:
        src = (rule.get("when") or {}).get("source_line")
        if not src:
            continue
        graph.setdefault(src, set()).update(rule.get("lights") or [])
    return graph


def reaches(graph: dict[str, set[str]], start: str, target: str = RAIL_ANCHOR) -> bool:
    """start 能否顺 handoff 图走到 target（默认铁轨锚）。BFS。"""
    seen = {start}
    q = deque([start])
    while q:
        node = q.popleft()
        if node == target:
            return True
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return target in seen
