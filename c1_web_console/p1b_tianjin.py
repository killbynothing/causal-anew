#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p1b_tianjin.py —— P1b 天津微切片：puzzle 频道 + f(Δ) 世界变软
============================================================
独立模块，不改动 p0_endpoints.py（你正在那边做 P1a）。复用同一本 δ 账本
(delta_ledger.json) 与 parse_intent（可用则复用，不可用则本地兜底）。

演示两件事：
  1) puzzle 频道：单点干涉必被改道收敛；组合达阈才破局（零死亡）。
  2) f(Δ) 世界变软：累积 δ 越多，有效阈值越低（但有下限 floor，绝不白送）；
     于是"上一轮单点被改道"的同一手，多轮之后能独力兜住——世界对你松了劲。
     而"城被置换"是 never_soften 的固定底——救下人，城仍被置换。

接入（在 server.py do_POST，与 P0 同风格，再加一个路径）：
    if self.path == '/api/tianjin':
        try:
            from p1b_tianjin import handle as tj_handle
            res = tj_handle(req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH)
            self.send_response_json(res)
        except Exception as e:
            self.send_error_json(500, f"Tianjin endpoint failed: {e}")
        return

请求体：{ "text": "我切断全城电网", "run_no": 1 }   （也可直接传 "intent"）
真库联调在你本机（沙箱真库副本损坏）。
"""
import os
import json
import time

NODE = "NODE-085-TIANJIN"

# --- 复用 P0 的 parse_intent（若不可用则本地兜底，避免与 P1a 编辑耦合）---
try:
    from p0_endpoints import parse_intent as _p0_parse_intent
except Exception:
    _p0_parse_intent = None

_LANE_KEYWORDS = [
    ("hack",     ["黑", "入侵", "破解", "断电", "电网", "熄灯", "中继", "基站", "拆透镜"]),
    ("info",     ["查", "调取", "延迟", "推迟", "拖", "发射", "倒计时", "时序"]),
    ("social",   ["疏散", "广播", "地铁", "引导", "避难", "分流", "通知", "喊"]),
    ("physical", ["搬", "挡", "拉", "抱", "拦"]),
    ("presence", ["在", "站", "留", "看着", "等"]),
]
_OUT_OF_GENRE = ["复活", "超能力", "神力", "瞬移", "直接炸掉", "一键摧毁", "时间倒流"]


def parse_intent(text):
    if _p0_parse_intent is not None:
        try:
            return _p0_parse_intent(text)
        except Exception:
            pass
    text = (text or "").strip()
    lane = "social"
    for name, kws in _LANE_KEYWORDS:
        if any(k in text for k in kws):
            lane = name
            break
    return {"lane": lane, "flags": [], "raw": text, "risk": "mid"}


# --- 天津路径映射：把玩家这一手归到 α/γ/ε 之一（或非 puzzle 动作）---
_PATH_KEYWORDS = {
    "alpha_blackout": ["断电", "电网", "熄灯", "拆透镜", "中继", "基站", "emp"],
    "gamma_shelter":  ["疏散", "广播", "地铁", "引导", "避难", "高处", "分流"],
    "epsilon_delay":  ["延迟", "推迟", "拖", "发射", "倒计时", "时序"],
}


def map_path(text):
    text = text or ""
    for pid, kws in _PATH_KEYWORDS.items():
        if any(k in text for k in kws):
            return pid
    return None


# --- 账本（直接读写同一 delta_ledger.json，与 p0 解耦）---
def _ledger_load(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _ledger_append(path, entry):
    data = _ledger_load(path)
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    data.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


# --- 契约载入（优先 YAML，兜底内置）---
_FALLBACK = {
    "node_id": NODE,
    "combine_threshold": 2,
    "path_set": [
        {"id": "alpha_blackout", "type": "hack", "snr_cost": "high"},
        {"id": "gamma_shelter", "type": "social", "snr_cost": "mid"},
        {"id": "epsilon_delay", "type": "info", "snr_cost": "low"},
    ],
    "softening": {"floor": 1, "per_delta": 3, "never_soften": ["城被置换"]},
}
_SNR = {0: 0, "0": 0, None: 0, "low": 1, "mid": 2, "high": 3}


def load_contract(contracts_dir):
    try:
        import yaml
        with open(os.path.join(contracts_dir, NODE + ".yaml"), "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return _FALLBACK


def _snr_for_path(pid, contract):
    for p in contract.get("path_set", []) or []:
        if p.get("id") == pid:
            return _SNR.get(p.get("snr_cost", 0), 0)
    return 1


# --- f(Δ)：有效阈值随累积 δ / 跨周目 S 下降，但不低于 floor ---
def effective_threshold(contract, delta_count, *, node_id=None, db_path=None, sediment_S=None):
    try:
        from pathlib import Path
        from runtime.softening_params import effective_combine_threshold

        root = Path(__file__).resolve().parents[1]
        return effective_combine_threshold(
            contract if isinstance(contract, dict) else {},
            int(delta_count or 0),
            node_id=node_id or NODE,
            db_path=db_path or (root / "data" / "world_truth.db"),
            sediment_S=sediment_S,
        )
    except Exception:
        base = contract.get("combine_threshold", 2)
        soft = contract.get("softening", {}) or {}
        floor = soft.get("floor", 1)
        per = soft.get("per_delta", 3)
        eff = base - (delta_count // per if per else 0)
        return max(floor, eff)


# --- 本节点本轮已激活的不同路径 ---
def _activated_paths(ledger_path, run_no):
    paths = set()
    for e in _ledger_load(ledger_path):
        if e.get("node") == NODE and e.get("run_no") == run_no:
            pid = e.get("path")
            if pid:
                paths.add(pid)
    return paths


def _node_delta_count(ledger_path):
    return sum(1 for e in _ledger_load(ledger_path) if e.get("node") == NODE)


_CONVERGE = {
    "alpha_blackout": "你切断了全城电网——可断电只是把灾难改道：人群涌向地下，踩踏惨剧蔓延，活下来的被收进置换名单。革命一号没被你关掉。",
    "gamma_shelter":  "你把人往高处和地下引、黑进了广播——可没动透镜，γ 束仍清场。少数边缘暴露者没保住，余下的，被一并置换。",
    "epsilon_delay":  "你把发射推迟了几分钟——总部只是重排了时序。单走一手延迟，什么也没兜住。",
    None:             "你做了点什么，但它没落在能改变天津命运的着力点上。",
}
_BRANCH = (
    "组合成立——这一次，没有人死。\n"
    "但当尘埃落定，整座天津已被时空罩抽离、隔离：你救下了人，城却还是被置换了。\n"
    "活下来的，成了另一个世界的实验品。\n"
    "（你赢了，但有什么东西，并不对劲。）"
)
_REJECT = "（这不是一个普通人能做到的事——交给张尘式吐槽消化掉，不进剧情。）"


def get_tianjin_fallback_line(intent):
    lane = intent.get("lane", "")
    if lane == "physical":
        return "在庞大的时空置换能量巨流面前，微观个体的物理阻挡（如『推、挡、拉、抱』）如同螳臂当车。你的行动并未能影响宏观局势，天津依然被时空罩物理撕裂剥离。"
    elif lane == "info":
        return "时空置换倒计时仅剩数分钟，已没有富余的时间让你在数据网中慢吞吞地调取案卷。你的探查行动未能对即将发生的物理灾难产生任何干涉投射。"
    elif lane == "social":
        return "你试图在混乱的街头大喊劝说惊慌失措的人群，但空气撕裂的轰鸣掩盖了一切。没有针对性的疏散行动（如广播引导、地铁导流），你的口头呼喊被强光瞬间吞没。"
    elif lane == "presence":
        return "你只是静静地站在虚空中看着这一切发生。世界线的收敛以无情的方式在天津上空合拢。你留下来了，但你什么也没有改变。"
    return "你做了点什么，但它没落在能改变天津命运的着力点上。"


def adjudicate(text, run_no, contract, ledger_path):
    intent = parse_intent(text)
    raw = intent.get("raw", text or "")

    # 体裁外（开大）→ reject
    if any(k in raw for k in _OUT_OF_GENRE):
        return {
            "verdict": "reject", "director_line": _REJECT,
            "path": None, "snr_charged": 0,
            "effective_threshold": None, "activated_paths": [],
            "delta_entry": {"node": NODE, "run_no": run_no, "verdict": "reject",
                            "tags": ["OUT_OF_GENRE"]},
        }

    pid = map_path(raw)
    snr = _snr_for_path(pid, contract) if pid else 0

    # 先按"加入这一手之后"的状态判定
    before = _activated_paths(ledger_path, run_no)
    after = set(before)
    if pid:
        after.add(pid)

    dc = _node_delta_count(ledger_path)        # 含历史所有周目（f(Δ) 用）
    eff = effective_threshold(contract, dc, node_id=NODE)
    n_after = len(after)

    if pid and n_after >= eff:
        verdict = "branched_zero_death"
        line = _BRANCH
        tags = ["PATH:" + pid, "TIANJIN_ZERO_DEATH"]
    else:
        verdict = "converged"
        if pid:
            line = _CONVERGE[pid]
        else:
            line = get_tianjin_fallback_line(intent)
        tags = (["PATH:" + pid] if pid else []) + ["CONVERGED"]

    return {
        "verdict": verdict,
        "director_line": line,
        "path": pid,
        "snr_charged": snr,
        "effective_threshold": eff,
        "base_threshold": contract.get("combine_threshold", 2),
        "softened": eff < contract.get("combine_threshold", 2),
        "activated_paths": sorted(after),
        "delta_count": dc,
        "city_replaced": True,   # 固定底：城被置换，永不软化（即便 branch 也成立）
        "delta_entry": {"node": NODE, "run_no": run_no, "path": pid,
                        "verdict": verdict, "tags": tags},
    }


def handle(req_data, db_path, contracts_dir, ledger_path):
    run_no = int(req_data.get("run_no", 1))
    text = req_data.get("text", "")
    if not text and req_data.get("intent"):
        text = req_data["intent"].get("raw", "")
    contract = load_contract(contracts_dir)
    res = adjudicate(text, run_no, contract, ledger_path)
    if res.get("delta_entry"):
        _ledger_append(ledger_path, res["delta_entry"])
    return res
