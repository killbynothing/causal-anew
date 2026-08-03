#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""心房阶闸内核（P6 · 纯函数、引擎零依赖、结构性防 Goodhart）。

张尘/卡卡西/修哉等重心角色的「心房阶 0-3」＝对玩家敞开程度。升阶**不能靠嘴甜**。
本内核把升阶判定钉在**结构化真实证据**上：
  - 玩家是否**真的在场**于指定「低谷事件」（来自 δ账本/session 记录的 event_uid 集）；
  - 玩家在该事件的**动作特征标签**（如 shielded/silent_company/took_blame）是否命中要求；
  - 是否触发**关门特征**（如 interrogate_wound/meta_concept/transactional）。
判定函数**根本不接收任何自由文本或情感字段**——嘴甜没有入口，从结构上防 Goodhart。

═══ 不变量（scripts/tests/test_heart_gate.py 红闸把守，生手必踩）═══
1. 防 Goodhart：升阶只读 `attended` / `action_tags` / `violations` 三类结构证据。
   说得再感人，若未在场或动作不对，不升阶（红样本 R1/R2）。
2. schema 硬禁：阶闸条件里出现 sentiment/keywords/tone 之类「靠说」的键＝非法配置，
   `schema_check` 直接拦（红样本 R6）——把「不许拿嘴甜当条件」写进 schema。
3. 不跳阶：一次结算至多升一阶；要到阶 N 必须阶 1..N 逐阶达标（红样本 R4）。
4. 关门回退：触发关门特征使高阶不再达标，结算回退到最高仍达标阶（红样本 R5）。
5. 纯函数确定性：同证据多次结算同结果。

表结构（真实三人低谷 uid/特征是 ★★★ 内容，另行入库；此处只定 schema）：
    tables = {
      "C.zhangchen.WMAIN": {"stages": {
        "1": {"requires": {"trough_event_uid": "E0XX", "presence": true,
                           "action_features": ["silent_company"], "min_features": 1},
              "closes_on": ["interrogate_past", "meta_concept", "transactional"]},
        "2": {...}, "3": {...}}}}
玩家证据（来自真实记录，无任何言语字段）：
    evidence = {"attended": {"E0XX", ...},
                "action_tags": {"E0XX": {"silent_company", ...}},
                "violations": {"transactional", ...}}
"""
from __future__ import annotations

# 阶闸条件里「靠说」的键一律非法：从 schema 层堵死 Goodhart
_FORBIDDEN_CONDITION_KEYS = {"sentiment", "keywords", "tone", "text", "utterance", "said"}
_REQUIRED_REQ_KEYS = {"trough_event_uid", "action_features"}


def schema_check(tables: dict) -> list[str]:
    """校验心房表结构合法；返回问题列表（空=合法）。核心：禁止用言语情感当升阶条件。"""
    errs: list[str] = []
    for char, spec in tables.items():
        stages = (spec or {}).get("stages") or {}
        if not stages:
            errs.append(f"{char}: 无 stages")
            continue
        for st, gate in stages.items():
            req = (gate or {}).get("requires") or {}
            bad = (set(req) | set(gate or {})) & _FORBIDDEN_CONDITION_KEYS
            if bad:
                errs.append(f"{char}/阶{st}: 禁止用言语情感键当升阶条件 {bad}（嘴甜不作数）")
            missing = _REQUIRED_REQ_KEYS - set(req)
            if missing:
                errs.append(f"{char}/阶{st}: requires 缺 {missing}")
            feats = req.get("action_features")
            if not (isinstance(feats, list) and feats):
                errs.append(f"{char}/阶{st}: action_features 须非空列表")
            mf = req.get("min_features", 1)
            if not (isinstance(mf, int) and mf >= 1):
                errs.append(f"{char}/阶{st}: min_features 须 ≥1")
            if "closes_on" in gate and not isinstance(gate["closes_on"], list):
                errs.append(f"{char}/阶{st}: closes_on 须为列表")
    return errs


def _gate_met(gate: dict, evidence: dict) -> bool:
    """单阶是否达标。只看结构证据；无任何言语入口。"""
    req = (gate or {}).get("requires") or {}
    uid = req.get("trough_event_uid")
    attended = set(evidence.get("attended") or ())
    if req.get("presence", True) and uid not in attended:
        return False  # 没真在场 → 不达标（嘴甜救不了）
    need = set(req.get("action_features") or ())
    got = set((evidence.get("action_tags") or {}).get(uid) or ())
    if len(need & got) < int(req.get("min_features", 1)):
        return False  # 动作特征不够
    closes = set(gate.get("closes_on") or ())
    if closes & set(evidence.get("violations") or ()):
        return False  # 触发关门特征 → 本阶不达标
    return True


def highest_qualified_stage(table: dict, evidence: dict) -> int:
    """该角色当前证据下能达标的最高阶（逐阶单调，遇第一个不达标即止）。阶 0 为默认底。"""
    stages = (table or {}).get("stages") or {}
    n = 0
    for st in sorted(stages, key=lambda s: int(s)):
        if _gate_met(stages[st], evidence):
            n = int(st)
        else:
            break
    return n


def evaluate(table: dict, current_stage: int, evidence: dict) -> int:
    """一次 memory-consolidation 结算后的新阶。
    - 至多升一阶（不跳阶）；
    - 若关门/证据不足使当前阶不再达标，回退到最高仍达标阶。"""
    qualified = highest_qualified_stage(table, evidence)
    if qualified < current_stage:
        return qualified  # 关门回退
    return min(current_stage + 1, qualified)  # 至多 +1


def would_advance_on_words_only(table: dict, current_stage: int) -> bool:
    """自检钩子：证明「只有言语、无在场无动作」永不升阶。恒返回 False 即达标。"""
    empty_evidence = {"attended": set(), "action_tags": {}, "violations": set()}
    return evaluate(table, current_stage, empty_evidence) > current_stage
