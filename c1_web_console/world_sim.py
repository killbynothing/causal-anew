#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
world_sim.py —— 离场角色与世界 tick 模拟（L2 因果导演层子系统）
================================================================
玩家离场时，其他意识按原著默认轨继续生活。被玩家涟漪波及的，
由导演生成新节拍并落 δ 账本；未波及的零 LLM 轨回放。
知识结算统一经 runtime_gate，保证门控一致性。

HTTP 接口（接入 server.py /api/world_tick）：
  请求: { "run_no":1, "from_ch":84, "to_ch":85, "active_delta":[...] }
  响应: { "ticked":[85], "events":[...], "knowledge_updates":[...], "world_state":{...} }

LOD 三档:
  Tier 0 — 玩家在场，交给 P0/P1 端点，本模块不管
  Tier 1 — 近场：轨回放为主，仅被扰动时委托导演
  Tier 2 — 远场：纯轨回放 + 事件桩，绝不调 LLM（铁律）

见设计文档: design/10_玩家层/离场角色与世界tick模拟_设计_v0.1.md
"""

import os
import json
import time
import sqlite3

# ---------------------------------------------------------------------------
# 路径常量（与 server.py 保持相对一致）
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_SCHEDULES_PATH   = os.path.join(_HERE, "schedules.json")
_WORLD_STATE_PATH = os.path.join(_HERE, "world_state.json")

# ---------------------------------------------------------------------------
# 复用现有零件
# ---------------------------------------------------------------------------
try:
    from p0_endpoints import ledger_append, ledger_load
except Exception as _e:
    # 降级兜底（server 环境应该能 import，沙箱里 fallback）
    def ledger_load(path):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def ledger_append(path, entry):
        data = ledger_load(path)
        entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        data.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data

try:
    import runtime_gate
    _HAS_GATE = True
except Exception:
    _HAS_GATE = False


# ---------------------------------------------------------------------------
# 日程表 & 世界状态 I/O
# ---------------------------------------------------------------------------

def _load_schedules():
    try:
        with open(_SCHEDULES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"schedules.json 读取失败: {e}")


def _load_world_state():
    if os.path.exists(_WORLD_STATE_PATH):
        try:
            with open(_WORLD_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_world_state(state):
    with open(_WORLD_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# LOD 档位判定
# ---------------------------------------------------------------------------

def _determine_tier(cons_id, sched, active_delta):
    """
    v0.1: 静态 tier_hint 优先。
    Tier 0 的 cons（玩家自己）跳过离场模拟。
    """
    hint = sched.get("tier_hint", 2)
    return hint


# ---------------------------------------------------------------------------
# 影响半径：该 cons 本拍是否被玩家 δ 波及
# ---------------------------------------------------------------------------

def _is_affected(cons_id, entry, active_delta, ch):
    """
    v0.1 规则：
      - delta.object 直接点名了这个 cons
      - cons_id 出现在 delta.witnesses 中
      - delta 发生的地点(where) + 章节(ch) 与本拍 entry 相同（同地同时）
    任意一条命中即视为波及。
    """
    where = entry.get("where", "")
    for delta in (active_delta or []):
        if delta.get("object") == cons_id:
            return True
        if cons_id in (delta.get("witnesses") or []):
            return True
        if delta.get("where") == where and delta.get("ch") == ch:
            return True
    return False


# ---------------------------------------------------------------------------
# 获取在场 witnesses（v0.1 简化：返回 cons 自己 + active_delta 的 witnesses）
# ---------------------------------------------------------------------------

def _get_witnesses(cons_id, ch, active_delta):
    """
    v0.1: 保守实现。原著轨回放时，在场者仅为 cons 自身。
    被扰动时，把 active_delta 里声明的 witnesses 也加进来（他们看见了同一场景）。
    未来可以从 occupancy 表拿同地点所有人。
    """
    ws = {cons_id}
    for d in (active_delta or []):
        for w in (d.get("witnesses") or []):
            ws.add(w)
    return sorted(ws)


# ---------------------------------------------------------------------------
# 知识结算
# ---------------------------------------------------------------------------

def _settle_knowledge(run_no, emits, witnesses, db_path, store=None):
    """
    把 emits 列表里的命题通过 runtime_gate 写入运行时知识库。
    返回 {cons: [prop_id, ...]} 形式的更新摘要。
    如果 runtime_gate 不可用，静默跳过（不崩溃，只是知识不写入）。
    """
    updates = {}
    if not emits or not _HAS_GATE:
        return updates

    for prop_id in emits:
        statement = _resolve_proposition(prop_id, db_path)
        if statement is None:
            # 命题库没有这条，生成一个占位 statement
            statement = f"[离场事件] {prop_id}"
        try:
            runtime_gate.record_event(run_no, prop_id, statement, witnesses, store=store)
            for w in witnesses:
                updates.setdefault(w, []).append(prop_id)
        except Exception as e:
            print(f"[world_sim] record_event 失败 prop={prop_id}: {e}")
    return updates


def _resolve_proposition(prop_id, db_path):
    """从 world_truth.db 读命题 statement；读不到返回 None。"""
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        db = sqlite3.connect(db_path)
        cur = db.cursor()
        cur.execute("SELECT statement FROM propositions WHERE prop_id=?", (prop_id,))
        row = cur.fetchone()
        db.close()
        return row[0] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 委托导演写"被扰动的新节拍"
# ---------------------------------------------------------------------------

def _director_offscreen(cons_id, ch, entry, active_delta, run_no, config,
                         db_path, contracts_dir, ledger_path):
    """
    构造离场请求，委托 director.handle 生成被扰动的新节拍。
    director 内含四支柱红线闸，生成内容自动合法。
    如果 director 不可用，降级返回原著节拍并标注 source=canon_fallback。
    """
    delta_summary = "; ".join(
        "{node}@{where}[{tags}]".format(
            node=d.get("node", "?"),
            where=d.get("where", "?"),
            tags=",".join(d.get("tags") or [])
        )
        for d in (active_delta or [])
    )

    req = {
        "node": f"OFFSCREEN-{cons_id}-CH{ch}",
        "text": (
            f"[离场模拟] {cons_id} 在第{ch}章于「{entry.get('where', '?')}」的日常，"
            f"因玩家行动（{delta_summary}）波及而改变。"
            f"原著中他/她应该：{entry.get('beat', '（无原著节拍）')}。"
            f"请写出被波及后实际发生的新节拍——一两句话，第三人称叙述，不写对话台词。"
        ),
        "run_no": run_no,
        "offscreen": True,
    }

    try:
        import director as _director
        res = _director.handle(req, db_path, contracts_dir, ledger_path, config)
        # director 返回结构里取文本；兼容不同 key
        beat_text = (
            res.get("beat")
            or res.get("narrative")
            or res.get("reply")
            or str(res)
        )
        emits = res.get("emits") or []
        tags  = res.get("tags") or ["offscreen_disturbed"]
        return {
            "beat": beat_text,
            "emits": emits,
            "tags": tags,
            "director_raw": res,
        }
    except Exception as e:
        print(f"[world_sim] director_offscreen 失败，降级为原著轨: {e}")
        return {
            "beat": entry.get("beat", ""),
            "emits": entry.get("emits") or [],
            "tags": ["canon_fallback"],
            "director_raw": None,
        }


# ---------------------------------------------------------------------------
# 主推进函数
# ---------------------------------------------------------------------------

def world_tick(run_no, from_ch, to_ch, active_delta,
               db_path=None, contracts_dir=None, ledger_path=None, config=None):
    """
    推进世界从 from_ch 到 to_ch（逐章节锚点）。
    返回 { ticked, events, knowledge_updates, world_state }
    """
    schedules   = _load_schedules()
    full_state  = _load_world_state()
    run_state   = full_state.setdefault(str(run_no), {})

    events          = []
    knowledge_map   = {}   # {cons_id: [prop_id, ...]}

    for ch in range(from_ch + 1, to_ch + 1):
        for cons_id, sched in schedules.items():
            # 跳过元数据字段（如 _note）
            if not isinstance(sched, dict):
                continue
            # Tier 0（玩家）跳过
            tier = _determine_tier(cons_id, sched, active_delta)
            if tier == 0:
                continue

            # 找这一章的日程项
            entry = next(
                (t for t in (sched.get("track") or []) if t.get("ch") == ch),
                None
            )
            if entry is None:
                continue

            # 判断是否被波及
            affected = (tier != 2) and _is_affected(cons_id, entry, active_delta, ch)

            if affected:
                # —— 被扰动：委托导演 ——
                result = _director_offscreen(
                    cons_id, ch, entry, active_delta, run_no, config or {},
                    db_path, contracts_dir, ledger_path
                )
                beat   = result["beat"]
                emits  = result["emits"]
                tags   = result["tags"]
                source = "director"

                # 落 δ 账本
                delta_entry = {
                    "node":    f"OFFSCREEN-{cons_id}-CH{ch}",
                    "cons":    cons_id,
                    "ch":      ch,
                    "run_no":  run_no,
                    "beat":    beat,
                    "tags":    tags,
                    "source":  "offscreen_disturbed",
                }
                if ledger_path:
                    try:
                        ledger_append(ledger_path, delta_entry)
                        delta_entry["delta_id"] = f"D-{cons_id}-{ch}-{run_no}"
                    except Exception as e:
                        print(f"[world_sim] ledger_append 失败: {e}")
            else:
                # —— 原著轨回放（零 LLM）——
                beat   = entry.get("beat", "")
                emits  = entry.get("emits") or []
                tags   = ["canon_replay"]
                source = "canon_replay"

            # 知识结算
            witnesses = _get_witnesses(cons_id, ch, active_delta if affected else [])
            kw = _settle_knowledge(run_no, emits, witnesses, db_path)
            for w, pids in kw.items():
                knowledge_map.setdefault(w, []).extend(pids)

            # 更新世界状态
            run_state[cons_id] = {
                "where":   entry.get("where", ""),
                "mood":    entry.get("mood_hint", ""),
                "last_ch": ch,
            }

            # 记录本拍事件
            ev = {
                "cons":   cons_id,
                "ch":     ch,
                "where":  entry.get("where", ""),
                "beat":   beat,
                "source": source,
                "emits":  emits,
            }
            if source == "director" and "delta_id" in delta_entry:
                ev["delta_id"] = delta_entry["delta_id"]
            events.append(ev)

    # 保存世界状态
    _save_world_state(full_state)

    return {
        "ticked":            list(range(from_ch + 1, to_ch + 1)),
        "events":            events,
        "knowledge_updates": [{"cons": k, "learned": v} for k, v in knowledge_map.items()],
        "world_state":       run_state,
    }


# ---------------------------------------------------------------------------
# HTTP 入口（供 server.py 调用）
# ---------------------------------------------------------------------------

def handle(req_data, db_path=None, contracts_dir=None, ledger_path=None, config=None):
    """
    统一 HTTP 入口。
    req_data 字段:
      run_no       int, 当前周目编号，默认 1
      from_ch      int, 推进起点（不含）
      to_ch        int, 推进终点（含）
      active_delta list[dict], 玩家本回合产生的活跃 δ 列表
    """
    run_no       = int(req_data.get("run_no", 1))
    from_ch      = int(req_data.get("from_ch", 84))
    to_ch        = int(req_data.get("to_ch", from_ch + 1))
    active_delta = req_data.get("active_delta") or []

    if to_ch <= from_ch:
        return {"error": f"to_ch({to_ch}) 必须大于 from_ch({from_ch})"}

    return world_tick(
        run_no=run_no,
        from_ch=from_ch,
        to_ch=to_ch,
        active_delta=active_delta,
        db_path=db_path,
        contracts_dir=contracts_dir,
        ledger_path=ledger_path,
        config=config,
    )


# ---------------------------------------------------------------------------
# CLI 快速测试（python world_sim.py）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=== world_sim 快速测试（零干涉，ch84→85）===")
    result = handle(
        {"run_no": 1, "from_ch": 84, "to_ch": 85, "active_delta": []},
        db_path=None,
        ledger_path=None,
        config={}
    )
    print(f"ticked: {result['ticked']}")
    for ev in result["events"]:
        print(f"  [{ev['source']}] {ev['cons']} ch{ev['ch']} @{ev['where']}")
        print(f"    beat: {ev['beat'][:60]}...")
        if ev.get("emits"):
            print("    emits:", ev["emits"])
    print("world_state:", len(result["world_state"]), "cons updated")
    print("=== done ===")
