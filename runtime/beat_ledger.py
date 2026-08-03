#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨视角「已发生记账」内核（P5 核心 · 纯函数、引擎零依赖）。

问题：一个共享物理帧（如中心医院）有多条视角线。同一 run 内，任一视角
完成某 must_happen 项，就意味着它引用的物理 beat 已在这个世界里发生过。
别的视角随后进入同一帧时，这些 beat 不应再作为「必须演出」重演一遍，
而应折叠成导演的一句背景转述（「你赶到时，手术室外的青年已经在装失忆了」）。

本模块只做「给定帧卡 + 账本 + 进入的视角 → 哪些 must_happen 还要演、
哪些折叠为背景」这一步纯函数，供引擎 load_card / must_happen 结算处调用。

═══ 不变量（scripts/tests/test_beat_ledger.py 红闸把守，生手必踩）═══
1. 幂等 key = (frame_id, beat_id)。**不是卡名、不是 run 号、不是 must_happen 项 id。**
   医院两视角对同一 BE5 的记账必须互相看见；拿卡名当 key＝跨视角失效（红样本1）。
2. 折叠判定：一条 must_happen 项折叠 ⟺ `frame_beat` **非空** 且其所有 beat 均已 done。
   纯视角项 `frame_beat == []` **永不折叠**（view-local，如 ZH7）。
   ⚠ 生手陷阱：`all([]) is True`，天真实现会把纯视角项误折叠（红样本2）。
3. append-only：completed 只增不减；对已 done 的 beat 再 mark 幂等无副作用。
   run≥1 只追加，不得回改（红样本3）。
4. run 隔离：completed 按 run 分桶。run 是周目、**不是时间轴**，不跨 run 复用（红样本4）。

账本结构（session 可持久化，纯 JSON）：
    {"1": ["zhongxin_hospital_shared_ch16_ch17::BE1", ...], "2": [...]}
    键=str(run)，值=beat_key 列表（内部按集合用）。
"""
from __future__ import annotations

from typing import Any


def beat_key(frame_id: str, beat_id: str) -> str:
    """稳定幂等键。当前用 (frame_id, beat_id)：beat_id 在帧内唯一、稳定。
    （远期理想键是 event_uid；因 BE7/BE8 尚缺库 uid，先用帧内 beat_id 兜底，
    待 uid 回填后可平滑切换——切换只改本函数。）"""
    return f"{frame_id}::{beat_id}"


def _run_bucket(ledger: dict, run: int) -> list:
    return ledger.setdefault(str(run), [])


def mark_done(ledger: dict, run: int, frame_id: str, beat_ids: list[str]) -> dict:
    """把若干 beat 标记为已发生。append-only、幂等。返回同一 ledger（就地增改）。"""
    bucket = _run_bucket(ledger, run)
    seen = set(bucket)
    for bid in beat_ids:
        k = beat_key(frame_id, bid)
        if k not in seen:  # 幂等：已在则跳过，绝不删
            bucket.append(k)
            seen.add(k)
    return ledger


def completed_beats(ledger: dict, run: int, frame_id: str) -> set[str]:
    """本 run、本帧已发生的 beat_id 集合。"""
    prefix = f"{frame_id}::"
    return {
        k[len(prefix):]
        for k in ledger.get(str(run), [])
        if k.startswith(prefix)
    }


def item_folds(item: dict, done_ids: set[str]) -> bool:
    """一条 must_happen 项是否应折叠为背景。见不变量 2。"""
    beats = item.get("frame_beat")
    if not beats:  # 纯视角项 [] 或缺失：永不折叠
        return False
    return all(b in done_ids for b in beats)


def resolve_view(frame_card: dict, view_id: str, ledger: dict, run: int) -> dict:
    """进入某视角时结算 must_happen。
    返回 {"live": [仍需演出的项], "folded": [{id, frame_beat, desc, narrate_context}]}。
    folded 的 desc 交由导演转述为「已发生的背景」，不再作为必演。"""
    frame = frame_card.get("frame") or {}
    frame_id = frame.get("frame_id", "")
    view = (frame_card.get("views") or {}).get(view_id) or {}
    done = completed_beats(ledger, run, frame_id)
    live: list[dict] = []
    folded: list[dict] = []
    for item in view.get("must_happen", []):
        if item_folds(item, done):
            folded.append({
                "id": item.get("id"),
                "frame_beat": list(item.get("frame_beat") or []),
                "desc": item.get("desc", ""),
                "narrate_context": f"[已发生·导演背景转述] {item.get('desc', '')}",
            })
        else:
            live.append(item)
    return {"live": live, "folded": folded}


def complete_view_item(ledger: dict, run: int, frame_card: dict, view_id: str, item_id: str) -> dict:
    """便捷：某视角完成了某 must_happen 项 → 把它引用的 frame_beat 记为已发生。"""
    frame = frame_card.get("frame") or {}
    frame_id = frame.get("frame_id", "")
    view = (frame_card.get("views") or {}).get(view_id) or {}
    for item in view.get("must_happen", []):
        if item.get("id") == item_id:
            return mark_done(ledger, run, frame_id, list(item.get("frame_beat") or []))
    raise KeyError(f"view {view_id} 无 must_happen 项 {item_id}")


def is_append_only(before: dict, after: dict) -> bool:
    """校验 after 相对 before 只增不减（session 持久化前的自检钩子）。"""
    for run_key, keys in before.items():
        if not set(keys) <= set(after.get(run_key, [])):
            return False
    return True
