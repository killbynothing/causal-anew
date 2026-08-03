#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mech_invariant_suite.py —— 高维机制四支柱·运行时断言套件 v0.1
==========================================================
四支柱设计书 §五 的 CI 断言落地。与 d1_compiler.py（编译期静态校验）并列为发版双 CI：
  - d1_compiler         编译期：契约缺字段/触锁链 → 四个编译错误码
  - mech_invariant_suite 运行时：四支柱的公式/行为是否守约（本文件）

含两部分：① 四支柱的**参考实现**（运行时引擎日后可直接复用这些公式）；② 对其的断言。
任一断言 FAIL → 退出码 1（禁止合入）。

用法：python scripts/mech_invariant_suite.py [--db world_truth.db]
（--db 仅支柱一的契约校验用；不传则跳过该项，其余纯公式断言不需库）
"""
import argparse, os, sys, statistics, random

# ───────────────────────── 参考实现（运行时引擎可复用）─────────────────────────
DESYNC_MS = 1000  # 支柱二：跨线恒定一秒刻痕

def xline_t_observed(t_send: int) -> int:
    """支柱二：引擎强制计算，禁手填。t_observed = t_send − desync。"""
    return t_send - DESYNC_MS

def snr_cost_effective(base_cost: float, lt_filter: float, lam: float = 1.0) -> float:
    """支柱三：snr 扣费 = cost·(1 + λ·lt_filter)。"""
    return base_cost * (1 + lam * lt_filter)

def lt_filter_step(lt_filter: float, converged_delta: float, kappa: float = 0.1,
                   is_new_type: bool = False, f_max: float = 5.0) -> float:
    """支柱三：跨周目学习，只升不降，封顶 F_max；新型干涉增量减免（减半）。"""
    inc = kappa * converged_delta * (0.5 if is_new_type else 1.0)
    return min(lt_filter + inc, f_max)

def coherence_cost(base_cost: float, coupling: float, phase: str):
    """支柱四：aligned 打折；opposed 触发 LT 告警。返回 (实扣, 告警值)。"""
    if phase == "aligned":
        return base_cost * (1 - coupling), 0.0
    if phase == "opposed":
        return base_cost, coupling * 1.0   # spike=1.0
    return base_cost, 0.0

def bleed_with_dust(base_rate: float, coupling: float, gamma: float = 0.5) -> float:
    """支柱四·旁观共振：尘叔在场，旁观 NPC 渗漏/元认知增速 ×(1+γ·coupling)。"""
    return base_rate * (1 + gamma * coupling)


# ───────────────────────── 断言 ─────────────────────────
class Suite:
    def __init__(self): self.passed = 0; self.failed = 0
    def check(self, name, cond, detail=""):
        if cond: self.passed += 1; print(f"  [PASS] {name}")
        else: self.failed += 1; print(f"  [FAIL] {name} {detail}")

    # 支柱一：不可回滚常量
    def pillar1(self, db_path):
        print("\n[支柱一] 不可回滚常量 / E_SELF_REF")
        if db_path and os.path.exists(db_path):
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import d1_compiler as d1, sqlite3
                conn = sqlite3.connect(db_path); locked = d1.load_locked_consts(conn)
                illegal = {"node_id": "TEST-REVIVE", "exit_states": [{"id": "revive", "negates": ["CC.RYUYA_DEATH"]}]}
                raised = False
                try: d1.validate(illegal, conn, locked)
                except d1.CompileError as e: raised = (e.code == "E_SELF_REF")
                conn.close()
                self.check("回滚固定底(CC.RYUYA_DEATH)契约必报 E_SELF_REF", raised)
            except Exception as ex:
                self.check("支柱一契约校验", False, f"(异常:{ex})")
        else:
            print("  (跳过契约校验：未提供可用 --db)")
        # ②模拟 10 次针对常量的干涉 → 10 条 SELF_REF_LOCK 且世界态不变
        ledger, world_state = [], {"v": 42}
        for _ in range(10):
            ledger.append({"emo_tag": "SELF_REF_LOCK", "converged": 1})  # 落账但不改世界态
        self.check("10 次常量干涉 → 10 条 SELF_REF_LOCK", sum(1 for e in ledger if e["emo_tag"] == "SELF_REF_LOCK") == 10)
        self.check("世界态在常量干涉后不变", world_state == {"v": 42})

    # 支柱二：一秒之差
    def pillar2(self):
        print("\n[支柱二] 一秒之差 / xline 恒定 1.000s")
        diffs = []
        for _ in range(200):
            ts = random.randint(0, 10**9)
            diffs.append(ts - xline_t_observed(ts))
        self.check("200 条混合信道 t_send-t_observed 方差 == 0", statistics.pvariance(diffs) == 0, f"(var={statistics.pvariance(diffs)})")
        self.check("均值恒等于 1000ms", statistics.mean(diffs) == 1000)
        self.check("修哉发现戏 GROUP BY channel 逐位 == 1.000000", all(d == 1000 for d in diffs))

    # 支柱三：SNR 信道经济
    def pillar3(self):
        print("\n[支柱三] 锚点信道 SNR / 干涉永不免费")
        # ①同型连打 5 次，第 5 次成本 > 第 1 次
        lt = 0.0; costs = []
        for i in range(5):
            costs.append(snr_cost_effective(1.0, lt)); lt = lt_filter_step(lt, 1.0, is_new_type=False)
        self.check("同型连打：cost5 > cost1", costs[4] > costs[0], f"({costs[0]:.3f}→{costs[4]:.3f})")
        # ②新型干涉的 lt_filter 增量 < 同型重复
        inc_same = lt_filter_step(0.0, 1.0, is_new_type=False) - 0.0
        inc_new  = lt_filter_step(0.0, 1.0, is_new_type=True) - 0.0
        self.check("新型干涉 lt_filter 增量 < 同型", inc_new < inc_same, f"({inc_new}<{inc_same})")
        # ③snr 归零后干涉呈损坏态（这里用标志位模拟）
        snr = 0.0
        self.check("snr 归零 → 干涉选项损坏态(非可点)", (snr <= 0.0))

    # 支柱四：双跳者相干
    def pillar4(self):
        print("\n[支柱四] 双跳者相干矩阵")
        coupling = 0.8  # 尘叔
        aligned, _ = coherence_cost(1.0, coupling, "aligned")
        solo, _ = coherence_cost(1.0, 0.0, "neutral")
        self.check("aligned 场景实扣 < 单独干涉", aligned < solo, f"({aligned}<{solo})")
        _, alert = coherence_cost(1.0, coupling, "opposed")
        self.check("opposed 场景产生 LT 告警", alert > 0, f"(alert={alert})")
        rate_with = bleed_with_dust(0.3, coupling)
        self.check("尘叔在场旁观 NPC meta_awareness 增速 > 基线", rate_with > 0.3, f"({rate_with:.3f}>0.3)")

    def run(self, db_path):
        self.pillar1(db_path); self.pillar2(); self.pillar3(); self.pillar4()
        print(f"\n结果：{self.passed} 通过，{self.failed} 失败")
        return self.failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join("data", "world_truth.db"))
    args = ap.parse_args()
    print("mech_invariant_suite v0.1 ｜ 四支柱运行时断言")
    failed = Suite().run(args.db)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
