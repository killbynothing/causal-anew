#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏线后台推进内核（P5 另一半 · 纯函数、引擎零依赖）。

玩家在场推进 A 线、世界游标随之前进时，玩家不在场的 B/C… 线要在后台按
**世界日历游标**推进（不是按玩家翻了几张卡）；推进产生的离屏事件按 run 追加进账本，
且**默认不泄给玩家**——只有当该事件的知识门 `learn_ch ≤ 玩家当前章` 且有合法信道时，
才回流进玩家可知层。这就是数字人六件套里的「知识门控 + 渗漏免疫」落到离屏推进上。

依赖 `world_calendar`（time_key / is_forward），与 P3 游标同源。

═══ 不变量（scripts/tests/test_offscreen_tick.py 红闸把守，生手必踩）═══
1. 按**游标差**推进：只触发时间落在游标区间 (from, to] 内的离屏事件。
   拿「玩家翻了几张卡」当推进量＝错（红样本 R1）。
2. run≥1 只追加、event_uid 幂等：同一区间重 tick 不得二次追加同一事件（红样本 R3）。
3. 游标单调：to 早于 from 的 tick 直接拒（复用 world_calendar.is_forward）（红样本 R4）。
4. **渗漏免疫**：离屏事件默认导演-only；`learn_ch > 玩家当前 ch_anchor` 的事件
   **绝不进玩家可知层**（红样本 R2）。这是硬底：宁可玩家暂时不知，不可泄。
5. 回流：玩家章推进到 `learn_ch` 且信道成立时，先前隐藏的离屏事件才转为可知（红样本 R5）。

数据（合成 fixture 演示；真实离屏线表是 ★★★ 内容，另行入库/数据文件）：
    schedule = [{"event_uid","ch_anchor","clock","learn_ch","desc","channel"?}, ...]
    ledger   = {"1": {"line_weichu": ["E018-03", ...]}}   # run→line→已触发 event_uid
"""
from __future__ import annotations

import world_calendar as wc
try:
    from runtime.runtime_state import append_storylet_event
except ImportError:
    append_storylet_event = None


def propose_actor_action(actor_cons: str, mind: dict, *, reachable: bool, target: str = "") -> dict | None:
    """Propose, never invent, one offscreen action from an existing goal/commitment."""
    motivation = mind.get("motivational_state", {}) if isinstance(mind, dict) else {}
    goals = [str(item).strip() for item in motivation.get("active_goals", []) if str(item).strip()]
    commitments = [str(item).strip() for item in motivation.get("commitments", []) if str(item).strip()]
    basis = commitments[0] if commitments else (goals[0] if goals else "")
    if not str(actor_cons).strip() or not basis or not reachable:
        return None
    return {"proposal_id": f"offscreen:{actor_cons}:{basis}", "actor_cons": actor_cons,
            "basis": "commitment" if commitments else "goal", "basis_text": basis,
            "target": str(target or ""), "reachable": True}


def resolve_actor_action(proposal: dict, *, observable_to: list[str] | None = None) -> dict:
    """Produce an appendable receipt; only named observers receive public consequence."""
    if not isinstance(proposal, dict) or not proposal.get("reachable"):
        raise ValueError("only reachable actor proposals may resolve")
    receipt_id = f"receipt:{proposal['proposal_id']}"
    return {"schema_version": "free_stage.offscreen_receipt.v1", "receipt_id": receipt_id,
            "actor_cons": proposal["actor_cons"], "basis": proposal["basis"],
            "public_consequence": {"kind": "actor_offscreen_action", "target": proposal.get("target", "")},
            "observable_to": [str(item) for item in (observable_to or []) if str(item).strip()]}


def persist_actor_receipt(runtime_db_path, *, run_no: int, worldline: str, receipt: dict) -> None:
    """Append a resolved offscreen action to the existing run-local ledger."""
    if append_storylet_event is None:
        raise RuntimeError("runtime_state append API is unavailable")
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "free_stage.offscreen_receipt.v1":
        raise ValueError("invalid offscreen receipt")
    append_storylet_event(runtime_db_path, run_no=run_no, worldline=worldline,
        event_id=str(receipt["receipt_id"]), storylet_id="offscreen_actor_action",
        event_type="offscreen_actor_action", payload=receipt)


def _event_key(event: dict) -> tuple[int, int]:
    return (int(event.get("ch_anchor", 0)), wc.minutes(event.get("clock")))


def due_events(schedule: list[dict], from_cursor: dict, to_cursor: dict) -> list[dict]:
    """时间落在游标区间 (from, to] 内的离屏事件（按游标差，非卡差）。"""
    if not wc.is_forward(from_cursor, to_cursor):
        raise ValueError("离屏 tick 的 to 游标早于 from：游标不得倒退")
    lo, hi = wc.time_key(from_cursor), wc.time_key(to_cursor)
    return [e for e in schedule if lo < _event_key(e) <= hi]


def _line_bucket(ledger: dict, run: int, line_id: str) -> list:
    return ledger.setdefault(str(run), {}).setdefault(line_id, [])


def tick_line(ledger: dict, run: int, line_id: str, schedule: list[dict],
              from_cursor: dict, to_cursor: dict) -> list[dict]:
    """推进某离屏线：触发区间内、尚未在账本中的事件，append event_uid。返回本次新触发事件。
    幂等：已触发的 event_uid 不再追加（不变量 2）。"""
    bucket = _line_bucket(ledger, run, line_id)
    fired_uids = set(bucket)
    newly: list[dict] = []
    for e in due_events(schedule, from_cursor, to_cursor):
        uid = e.get("event_uid")
        if uid not in fired_uids:
            bucket.append(uid)
            fired_uids.add(uid)
            newly.append(e)
    return newly


def is_visible(event: dict, player_cursor: dict, channels: set[str] | None = None) -> bool:
    """离屏事件是否可进玩家可知层。渗漏免疫硬底：learn_ch > 玩家当前章 一律 False。
    另可要求合法信道（event.channel ∈ channels）；未标 channel 则只看章门。"""
    learn_ch = event.get("learn_ch")
    if learn_ch is None:
        return False  # 未标知识门＝默认导演-only，不泄
    if int(learn_ch) > int(player_cursor.get("ch_anchor", 0)):
        return False  # ← 渗漏免疫硬底
    ch = event.get("channel")
    if ch is not None and (channels is None or ch not in channels):
        return False
    return True


def knowable_digest(events: list[dict], player_cursor: dict,
                    channels: set[str] | None = None) -> list[dict]:
    """从一批离屏事件里筛出此刻可回流给玩家的（回流），其余留导演-only。"""
    return [e for e in events if is_visible(e, player_cursor, channels)]


def director_only(events: list[dict], player_cursor: dict,
                  channels: set[str] | None = None) -> list[dict]:
    """补集：当前仍不可泄、只能导演内部持有的离屏事件。"""
    visible = {id(e) for e in knowable_digest(events, player_cursor, channels)}
    return [e for e in events if id(e) not in visible]


def is_append_only(before: dict, after: dict) -> bool:
    """校验离屏账本 after 相对 before 只增不减。"""
    for run_key, lines in before.items():
        for line_id, uids in lines.items():
            if not set(uids) <= set(after.get(run_key, {}).get(line_id, [])):
                return False
    return True


# 兼容旧 free_stage_prototype 的离屏生活接口。
# 新 P5 机制以 schedule/tick_line 为准；这两个函数只负责旧引擎的状态摘要与叙事钩子，
# 避免旧 free_stage 测试在 import 阶段因接口缺失而整体红灯。
def _elapsed_minutes(source_clock: str, target_clock: str) -> int:
    return max(0, wc.minutes(target_clock) - wc.minutes(source_clock))


def _physical_from_energy(energy: float) -> str:
    if energy < 0.28:
        return "critical"
    if energy < 0.48:
        return "hurt"
    if energy < 0.68:
        return "tired"
    return "steady"


def run_offscreen_ticks(
    source_clock: str,
    target_clock: str,
    tick_specs: dict,
    player_state: dict | None = None,
) -> dict:
    """旧 free_stage 的离屏生活推进摘要。

    返回 before/after/logs/tick_count/player_state。该接口不负责正典事件回流；
    正典离屏线仍走 tick_line/knowable_digest 的 schema。
    """
    elapsed = _elapsed_minutes(source_clock, target_clock)
    tick_count = max(1, elapsed // 30) if elapsed else 0
    base_player = dict(player_state or {})
    base_energy = float(base_player.get("energy", 0.78))
    # 时钟流逝不是体力消耗。只有卡/路线已记录的可见行程才会扣体力；
    # 否则“上午过去了”会把所有离场角色伪造为伤员。
    player_travel = max(0, int(base_player.get("travel_minutes", 0) or 0))
    drain = min(0.55, (player_travel // 30) * 0.03)
    player_after = dict(base_player)
    player_after["energy"] = round(max(0.05, base_energy - drain), 3)

    before: dict = {}
    after: dict = {}
    logs: list[dict] = []
    for cons_id, spec in (tick_specs or {}).items():
        inner = (spec or {}).get("inner_state") or {}
        start_energy = float((spec or {}).get("energy", base_energy))
        travel_minutes = max(0, int((spec or {}).get("travel_minutes", 0) or 0))
        actor_drain = min(0.55, (travel_minutes // 30) * 0.03)
        end_energy = round(max(0.05, start_energy - actor_drain), 3)
        before[cons_id] = {
            "energy": round(start_energy, 3),
            "physical": _physical_from_energy(start_energy),
            "mood": 0.0,
            "rumination": 0.0,
        }
        rumination = min(0.9, 0.18 + tick_count * 0.035) if inner.get("knot") else min(0.45, tick_count * 0.025)
        after[cons_id] = {
            "energy": end_energy,
            "physical": _physical_from_energy(end_energy),
            "mood": round(0.05 if inner.get("stance_to_player") == "友好热情" else 0.0, 3),
            "rumination": round(rumination, 3),
        }
        logs.append({
            "cons": cons_id,
            "elapsed_minutes": elapsed,
            "tag": "mundane",
            "text": "离屏时间继续流动，体力只按已记录的行程消耗。" if travel_minutes else "离屏时间平稳经过，没有记录到额外体力消耗。",
        })
    return {
        "before": before,
        "after": after,
        "logs": logs,
        "tick_count": tick_count,
        "player_state": player_after,
    }


def render_offscreen_narrative(cons_id: str, before: dict, after: dict, logs: list[dict]) -> list[str]:
    """把旧离屏生活状态转成 memory_context 可读条目。"""
    entries: list[str] = []
    matching_logs = [log for log in logs or [] if log.get("cons") == cons_id]
    if matching_logs:
        entries.append("[mundane] " + str(matching_logs[-1].get("text", "")).strip())
    before_energy = float((before or {}).get("energy", 0.78))
    after_energy = float((after or {}).get("energy", before_energy))
    physical = str((after or {}).get("physical", "")).strip()
    if physical in {"tired", "hurt", "critical"} or after_energy < before_energy:
        entries.append(f"[mundane] 这段不在场的时间让体力从 {before_energy:.2f} 降到 {after_energy:.2f}，状态变为 {physical or 'steady'}。")
    if float((after or {}).get("rumination", 0.0)) > 0.55:
        entries.append("[echo] 空白时间里，未说出口的心结被重新翻起。")
    return entries or ["[mundane] 离屏时间平稳经过，没有新的可见波澜。"]
