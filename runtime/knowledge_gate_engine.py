#!/usr/bin/env python3
"""
知识图谱门控引擎 v0.2 —— 接入 world_truth.db（库赢版）
=====================================================
v0.1 → v0.2 变更：
- 数据源从独立的 knowledge_graph_ch1_20.json 改为直接读 world_truth.db
  的三张表：propositions / knowledge_schedule / knowledge_runtime。
  → 门控自此覆盖全程（不再只到 Ch.20），且与角色圣经的「知识时间表」
    共用同一份真相源（圣经由 generate_bibles.py 渲染同样这两张表）。
- spoiler_tier 分层：3=CRITICAL(硬锁) / 2=HIGH(门控) / 1=TRACKED / 0=SOFT(TEMP细碎软知识)。
  仅对 tier>=GATE_MIN_TIER(默认2) 的命题做门控与泄漏扫描；0 级软知识
  只进「角色确知事实」用于人设，不拦截、不进黑名单（否则黑名单会被
  几百条 TEMP_ 噪声淹没）。
- 黑名单(does_NOT_know) 改为从 knowledge_schedule 反推：在第 N 章，
  凡 tier>=2 且该意识此刻尚未 learn 的命题，即为它此刻不该提及的。

职责（与 v0.1 一致）：
1. 查"意识X在第Y章知道什么"（query）
2. 校验 NPC 输出是否泄漏不该知道的命题（validate_output）
3. 组装注入提示词的合法知识切片（assemble_context_slice）
4. 命题传播的门控（propagate，可落 knowledge_runtime）
5. 全角色知识状态报告（generate_report）

用法：
    eng = KnowledgeGateEngine("world_truth.db")          # run=0 正典
    eng.query("C.kakashi.WMAIN", chapter=78)
    eng.validate_output("C.xiuzai.WMAIN", 10, "……跃迁……")
    eng.assemble_context_slice("C.kakashi.WMAIN", 77)
"""

import sqlite3
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from prompt_pipeline import resolve_knowledge


# ─────────────────── tier 约定（与 import_db 种子数据一致）───────────────────
TIER_NAME = {3: "CRITICAL", 2: "HIGH", 1: "TRACKED", 0: "SOFT"}
GATE_MIN_TIER = 2          # 仅门控/扫描 tier >= 2 的真秘密
BLOCK_TIER = 3             # tier==3 泄漏 → BLOCK；tier==2 → WARN

# 高 tier 命题的泄漏扫描关键词（DB 无 keywords 列，这里集中维护；
# 未列出的 tier>=2 命题回退为从 statement 抽词）。
CRITICAL_KEYWORDS = {
    "P.RTW131_IDENTITY":    ["RTW-131", "RTW131", "人造人", "实验体", "初代"],
    "P.SEIMEI_MACHINE":     ["晴明君", "人造机体", "搭载", "黑发卡卡西是机器", "异世界修哉的大脑"],
    "P.DUST_CREATOR":       ["尘叔创建", "Dust", "世界政府是尘叔", "跃迁者创建"],
    "P.FIRST_WORLD_PROMISE":["第一世界", "斯德哥尔摩大火", "带你回来"],
    "P.GF_DEATH_TRUTH":     ["推下楼", "龙也推", "苏颖被推", "亲手推"],
    "P.RYUYA_DEATH_TRUTH":  ["假死", "弑父", "龙也杀父", "杀了正义"],
    "P.RTW_EXISTS":         ["世界政府", "RTW组织", "RTW"],
    "P.WEICHU_WIDOW":       ["遗孀", "龙也的妻子", "龙也的遗孀"],
    "P.LEAP_EXISTS":        ["意识跃迁", "跃迁技术", "意识转移"],
    "P.RYUYA_ALIVE":        ["龙也没死", "龙也还活着", "龙也假死"],
}

# 传播可靠度（来源角色 → 置信度衰减）；缺省 0.8
RELIABILITY = {
    "C.kakashi.WMAIN": 0.98, "C.xiuzai.WMAIN": 0.95, "C.zhangchen.WMAIN": 0.85,
    "C.dust.W1": 1.0, "~柳絮": 0.7, "~斑驳": 0.6,
}


@dataclass
class Proposition:
    prop_id: str
    statement: str
    tier: int
    canon_src: str = ""
    keywords: list = field(default_factory=list)

    @property
    def tier_name(self) -> str:
        return TIER_NAME.get(self.tier, str(self.tier))

    def __post_init__(self):
        if not self.keywords:
            self.keywords = CRITICAL_KEYWORDS.get(self.prop_id) or self._fallback_keywords()

    def _fallback_keywords(self) -> list:
        """未在 CRITICAL_KEYWORDS 中登记的高 tier 命题，从陈述里粗提名词性片段。"""
        if self.tier < GATE_MIN_TIER:
            return []
        # 取陈述里的人名/专名候选（连续中文 3-8 字的片段，去重取前 3）
        cands = re.findall(r"[一-龥A-Za-z0-9·]{3,8}", self.statement)
        seen, out = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c); out.append(c)
            if len(out) >= 3:
                break
        return out


class KnowledgeGateEngine:
    def __init__(self, db_path: str = os.path.join("data", "world_truth.db"), run: int = 0):
        """db_path: world_truth.db；run: 周目（0=正典基线，>=1 叠加 knowledge_runtime）。"""
        self.db_path = db_path
        self.run = run
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.audit_log: list = []
        self._props: dict[str, Proposition] = {}
        self._load_propositions()

    def close(self):
        self.conn.close()

    # ─────────────────── 加载 ───────────────────
    def _load_propositions(self):
        for r in self.conn.execute("SELECT prop_id, statement, spoiler_tier, canon_src FROM propositions"):
            self._props[r["prop_id"]] = Proposition(
                prop_id=r["prop_id"], statement=r["statement"],
                tier=r["spoiler_tier"], canon_src=r["canon_src"] or "",
            )

    def _schedule_sources(self, cons_id: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT prop_id, source_desc FROM knowledge_schedule WHERE cons_id=?",
            (cons_id,),
        )
        return {r["prop_id"]: r["source_desc"] or "" for r in rows}

    # ─────────────────── 查询 ───────────────────
    def query(self, cons_id: str, chapter: int) -> dict:
        """该意识截至 chapter 的知识状态：知道什么 + 此刻被门控封锁什么。"""
        knows = []
        resolved = resolve_knowledge(cons_id, chapter, self.db_path)
        sources = self._schedule_sources(cons_id)
        for r in resolved.get("unlocked", []):
            prop = self._props.get(r["prop_id"])
            tier = prop.tier if prop else 0
            knows.append({
                "prop_id": r["prop_id"],
                "statement": r["statement"],
                "tier": tier,
                "tier_name": TIER_NAME.get(tier, str(tier)),
                "acquired_at": f"Ch.{r['learn_ch']}",
                "source": sources.get(r["prop_id"], ""),
                "confidence": 1.0,
            })
        # 周目运行时增量（run>=1）
        if self.run > 0:
            rt = """SELECT kr.prop_id, p.statement, p.spoiler_tier, kr.confidence
                    FROM knowledge_runtime kr JOIN propositions p ON kr.prop_id = p.prop_id
                    WHERE kr.run = ? AND kr.cons_id = ?"""
            known_ids = {k["prop_id"] for k in knows}
            for r in self.conn.execute(rt, (self.run, cons_id)):
                if r["prop_id"] not in known_ids:
                    knows.append({
                        "prop_id": r["prop_id"], "statement": r["statement"], "tier": r["spoiler_tier"],
                        "tier_name": TIER_NAME.get(r["spoiler_tier"], str(r["spoiler_tier"])),
                        "acquired_at": f"run{self.run}", "source": "运行时获知", "confidence": r["confidence"],
                    })
        blacklist = self._blacklist(cons_id, chapter, {k["prop_id"] for k in knows})
        return {
            "character": cons_id, "as_of_chapter": chapter,
            "knows": knows, "does_NOT_know": blacklist,
            "total_known": len(knows), "total_blocked": len(blacklist),
        }

    def _blacklist(self, cons_id: str, chapter: int, known_ids: set) -> list:
        """tier>=GATE_MIN_TIER 且此刻未知 → 黑名单（按 tier 降序）。"""
        bl = [(pid, p.tier) for pid, p in self._props.items()
              if p.tier >= GATE_MIN_TIER and pid not in known_ids]
        bl.sort(key=lambda x: -x[1])
        return [pid for pid, _ in bl]

    # ─────────────────── 校验输出 ───────────────────
    def validate_output(self, cons_id: str, chapter: int, output_text: str) -> dict:
        state = self.query(cons_id, chapter)
        violations = []
        for prop_id in state["does_NOT_know"]:
            prop = self._props.get(prop_id)
            if not prop:
                continue
            for kw in prop.keywords:
                if kw and kw in output_text:
                    sev = "CRITICAL_VIOLATION" if prop.tier >= BLOCK_TIER else "HIGH_VIOLATION"
                    violations.append({
                        "prop_id": prop_id, "keyword_matched": kw, "tier": prop.tier,
                        "tier_name": prop.tier_name, "severity": sev, "statement": prop.statement,
                    })
                    self.audit_log.append({
                        "event": "OUTPUT_VIOLATION", "chapter": chapter, "cons": cons_id,
                        "prop_id": prop_id, "keyword": kw, "blocked": prop.tier >= BLOCK_TIER,
                    })
                    break
        result = "PASS"
        if any(v["tier"] >= BLOCK_TIER for v in violations):
            result = "BLOCK"
        elif violations:
            result = "WARN"
        return {
            "result": result, "character": cons_id, "chapter": chapter,
            "violations": violations, "violation_count": len(violations),
            "action": {"BLOCK": "BLOCK_AND_REGENERATE", "WARN": "LOG_AND_REVIEW", "PASS": "ALLOW"}[result],
        }

    # ─────────────────── 上下文组装 ───────────────────
    def assemble_context_slice(self, cons_id: str, chapter: int) -> dict:
        state = self.query(cons_id, chapter)
        knows = sorted(state["knows"], key=lambda x: (-x["tier"], -x["confidence"]))
        lines = [f"## {cons_id} 的知识状态（截至 Ch.{chapter}）", "### 你确定知道的事实："]
        for k in knows:
            conf = f"[置信度:{k['confidence']:.0%}]" if k["confidence"] < 1.0 else ""
            soft = "（背景认知）" if k["tier"] < GATE_MIN_TIER else ""
            lines.append(f"- {k['statement']} {soft}{conf}")
        lines.append("\n### 绝对禁止提及或暗示（你此刻并不知道）：")
        critical_blocks = []
        for bp in state["does_NOT_know"]:
            prop = self._props.get(bp)
            if not prop:
                continue
            if prop.tier >= BLOCK_TIER:
                lines.append(f"- [硬锁] {prop.statement}")
                critical_blocks.append(bp)
            else:
                lines.append(f"- [门控] {prop.statement}")
        return {
            "character": cons_id, "chapter": chapter,
            "known_count": len(knows), "blocked_count": len(state["does_NOT_know"]),
            "inject_text": "\n".join(lines), "critical_blocks": critical_blocks,
        }

    # ─────────────────── 传播 ───────────────────
    def propagate(self, from_cons: str, to_cons: str, prop_id: str,
                  chapter: int, method: str = "told_by", persist: bool = False) -> dict:
        prop = self._props.get(prop_id)
        if not prop:
            return {"result": "ERROR", "reason": f"命题 {prop_id} 不存在"}
        # CRITICAL：硬锁，需导演层 unlock
        if prop.tier >= BLOCK_TIER:
            self.audit_log.append({"event": "PROPAGATION_BLOCKED", "chapter": chapter,
                                   "from": from_cons, "to": to_cons, "prop_id": prop_id, "blocked": True})
            return {"result": "BLOCKED", "tier_name": prop.tier_name,
                    "reason": "CRITICAL 命题需导演层 unlock，不可经普通传播"}
        # HIGH：来源须确实持有
        if prop.tier == 2:
            src = self.query(from_cons, chapter)
            if prop_id not in {k["prop_id"] for k in src["knows"]}:
                return {"result": "BLOCKED", "reason": f"{from_cons} 自身在 Ch.{chapter} 尚不知道 {prop_id}"}
        conf = RELIABILITY.get(from_cons, 0.8)
        if persist:
            self.conn.execute(
                "INSERT OR REPLACE INTO knowledge_runtime(run,cons_id,prop_id,acquired_event,confidence) VALUES (?,?,?,?,?)",
                (max(self.run, 1), to_cons, prop_id, None, conf))
            self.conn.commit()
        self.audit_log.append({"event": "PROPAGATION_SUCCESS", "chapter": chapter,
                               "from": from_cons, "to": to_cons, "prop_id": prop_id, "blocked": False})
        return {"result": "PROPAGATED", "to": to_cons, "prop_id": prop_id, "confidence": conf,
                "note": "已落 knowledge_runtime" if persist else "仅内存（persist=False）"}

    # ─────────────────── 报告 ───────────────────
    def generate_report(self, chapter: int, cons_ids: Optional[list] = None) -> str:
        if cons_ids is None:
            cons_ids = [r["cons_id"] for r in self.conn.execute(
                "SELECT DISTINCT cons_id FROM knowledge_schedule ORDER BY cons_id")]
        lines = [f"# 知识门控报告 — 截至 Ch.{chapter}（run={self.run}）", ""]
        for c in cons_ids:
            st = self.query(c, chapter)
            hard = [b for b in st["does_NOT_know"] if self._props[b].tier >= BLOCK_TIER]
            lines.append(f"## {c}　已知 {st['total_known']} ｜ 门控封锁 {st['total_blocked']}（其中硬锁 {len(hard)}）")
        return "\n".join(lines)


def open_engine(db_path: str = os.path.join("data", "world_truth.db"), run: int = 0) -> KnowledgeGateEngine:
    return KnowledgeGateEngine(db_path, run=run)


# ─────────────────── CLI ───────────────────
if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "world_truth.db")
    eng = KnowledgeGateEngine(db)
    print("=" * 60)
    print(f"知识门控引擎 v0.2（库：{db}，run={eng.run}）")
    print("=" * 60)
    for c in ["C.kakashi.WMAIN", "C.xiuzai.WMAIN", "C.zhangchen.WMAIN"]:
        for ch in (20, 78, 113):
            st = eng.query(c, ch)
            print(f"\n[{c} @ Ch.{ch}] 知道 {st['total_known']} ｜ 封锁 {st['total_blocked']}")
            for k in st["knows"][:6]:
                print(f"    ✓ [{k['tier_name']}] {k['statement'][:24]} ← {k['acquired_at']}")
    print("\n--- 泄漏校验：卡卡西 Ch.20 说出'人造人'(此时还不知道) ---")
    r = eng.validate_output("C.kakashi.WMAIN", 20, "其实我怀疑自己是个人造人实验体")
    print("  结果:", r["result"], "｜动作:", r["action"])
    for v in r["violations"]:
        print(f"    ⚠ [{v['tier_name']}] {v['prop_id']} (命中:'{v['keyword_matched']}')")
    print("\n--- 同一句话在 Ch.78(已知)应放行 ---")
    print("  结果:", eng.validate_output("C.kakashi.WMAIN", 78, "其实我怀疑自己是个人造人实验体")["result"])
    eng.close()
