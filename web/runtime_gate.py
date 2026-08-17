#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runtime_gate.py —— 运行时门控自更新（Q1）
==========================================
现有门控是 Worldline-0 的静态时间表（谁何时知道什么）。玩家进来后，
他的行动会制造新事件，NPC 会"当场知道/事后听说"——门控必须**运行时自更新**：

  玩家/δ 事件 → 生成「运行时命题」→ propagate 给在场 NPC（其余按传播规则延迟）
            → 本回合后续，这些 NPC 的"已解锁集"随之扩大
            → 门控集 = 原著基线 ∪ 本回合习得
  重置：按 run_no 自动周目隔离——换周目=新 run_no=干净基线（人不记得，对齐累积/重置设计）

与现有 leak_check 配合：NPC 不能说出"既非原著解锁、本回合也没习得"的真相。
即门控从"静态时间表"升成"基线 + 运行时累积、每周目重置"。

接入（server.py）：
    if self.path == '/api/runtime_gate':
        try:
            from runtime_gate import handle as rg_handle
            res = rg_handle(req_data, DB_PATH)
            self.send_response_json(res)
        except Exception as e:
            self.send_error_json(500, f"Runtime gate failed: {e}")
        return
典型用法：
  - 导演判玩家这一手成立、且会被某些 NPC 看到 → {op:"record", run_no, prop_id, statement, witnesses:[...]}
  - 传闻扩散 → {op:"propagate", run_no, prop_id, to:[...]}
  - NPC 出话前/后查泄露 → {op:"leakcheck", run_no, cons, ch, text}
  - 换周目 → {op:"reset", run_no}
真库联调在你本机。
"""
import os
import json
import time

# 复用现成引擎：canon 门控 + 泄露检测（不可用则降级为内置简版）
try:
    from npc_test_client import knowledge as _knowledge, leak_check as _leak_check
except Exception:
    _knowledge = None
    _leak_check = None

_STORE = os.path.join(os.path.dirname(__file__), "runtime_knowledge.json")


# ---------------- 运行时知识存储（按 run_no 周目隔离）----------------
def _load(store=None):
    p = store or _STORE
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(data, store=None):
    with open(store or _STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_event(run_no, prop_id, statement, witnesses, store=None):
    """玩家/δ 事件 → 运行时命题；在场 witnesses 当场习得。"""
    data = _load(store)
    run = data.setdefault(str(run_no), {})
    run[prop_id] = {
        "statement": statement,
        "learned_by": sorted(set(witnesses or [])),
        "born_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save(data, store)
    return run[prop_id]


def propagate(run_no, prop_id, to_cons, store=None):
    """传闻/接触扩散：让更多 NPC 习得该运行时命题。"""
    data = _load(store)
    run = data.setdefault(str(run_no), {})
    if prop_id not in run:
        return None
    learned = set(run[prop_id]["learned_by"]) | set(to_cons or [])
    run[prop_id]["learned_by"] = sorted(learned)
    _save(data, store)
    return run[prop_id]


def learned(run_no, cons, store=None):
    """该周目内，cons 已习得的运行时命题 {prop_id: statement}。"""
    run = _load(store).get(str(run_no), {})
    return {pid: v["statement"] for pid, v in run.items() if cons in v.get("learned_by", [])}


def reset(run_no, store=None):
    """换周目：清掉该 run 的运行时知识（人不记得）。"""
    data = _load(store)
    data.pop(str(run_no), None)
    _save(data, store)
    return True


# ---------------- 门控合成：基线 ∪ 运行时习得 ----------------
def _canon(cons, ch, db_path):
    """取原著基线 (unlocked, locked)；每项是 (prop_id, statement)。引擎不可用→空。"""
    if _knowledge is None:
        return [], []
    import sqlite3
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    try:
        unlocked, locked = _knowledge(cur, cons, ch)
    finally:
        db.close()
    return list(unlocked), list(locked)


def gate_snapshot(run_no, cons, ch, db_path, store=None):
    """返回本回合该 NPC 的有效门控：基线 unlocked + 运行时习得 → 仍锁的 locked。"""
    unlocked, locked = _canon(cons, ch, db_path)
    rt = learned(run_no, cons, store)                 # {prop_id: statement}
    rt_ids = set(rt.keys())
    # 有效已解锁 = 原著解锁 ∪ 运行时习得；有效仍锁 = 原著锁 − 运行时习得
    eff_locked = [(pid, st) for (pid, st) in locked if pid not in rt_ids]
    eff_unlocked = [(pid, st) for (pid, st) in unlocked] + [(pid, st) for pid, st in rt.items()]
    return {
        "effective_unlocked": eff_unlocked,
        "effective_locked": eff_locked,
        "runtime_learned": rt,
    }


def leakcheck(run_no, cons, ch, text, db_path, store=None):
    """NPC 出话查泄露：只对'仍锁'的命题判泄露（本回合已习得的不算泄露）。"""
    snap = gate_snapshot(run_no, cons, ch, db_path, store)
    eff_locked = snap["effective_locked"]
    locked_statements = [st for (_pid, st) in eff_locked]
    if _leak_check is not None:
        try:
            hits = _leak_check(text, eff_locked, db_path)
        except Exception:
            hits = _simple_leak(text, locked_statements)
    else:
        hits = _simple_leak(text, locked_statements)
    return {"leak": bool(hits), "hits": hits,
            "runtime_learned_count": len(snap["runtime_learned"]),
            "effective_locked_count": len(eff_locked)}


def _simple_leak(text, locked_statements):
    """内置简版泄露：命中仍锁命题的强特征片段即判泄露（引擎不可用时兜底）。"""
    t = text or ""
    hits = []
    for st in locked_statements:
        s = st or ""
        # 取命题中较长的特征子串做保守匹配
        for token in _keytokens(s):
            if token and token in t:
                hits.append(st)
                break
    return hits


def _keytokens(s):
    # 简单切出 3~6 字特征片段（保守，宁漏不误）
    s = "".join(ch for ch in s if ch not in " ，。、：；「」（）()")
    return [s[i:i + 4] for i in range(0, max(1, len(s) - 3), 4)] if len(s) >= 4 else [s]


# ---------------- 统一入口 ----------------
def handle(req_data, db_path):
    op = req_data.get("op", "query")
    run_no = req_data.get("run_no", 1)
    if op == "record":
        info = record_event(run_no, req_data["prop_id"], req_data.get("statement", ""),
                            req_data.get("witnesses", []))
        return {"ok": True, "prop": info}
    if op == "propagate":
        info = propagate(run_no, req_data["prop_id"], req_data.get("to", []))
        return {"ok": info is not None, "prop": info}
    if op == "reset":
        reset(run_no)
        return {"ok": True}
    if op == "leakcheck":
        return leakcheck(run_no, req_data["cons"], int(req_data.get("ch", 84)),
                        req_data.get("text", ""), db_path)
    if op == "query":
        return gate_snapshot(run_no, req_data["cons"], int(req_data.get("ch", 84)), db_path)
    return {"error": f"unknown op {op}"}
