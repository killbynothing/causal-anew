#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
npc_test_client.py —— C1：数字生命 FSM + 慢环记忆检索 + 提示词装配 测试客户端
实现《数字生命情感脱钩与慢环记忆检索设计》的全部运行时算法，接 world_truth.db 实测。

用法：
  python npc_test_client.py fsm-sim                          # FSM 断言自检（CI 用，退出码 0/1）
  python npc_test_client.py retrieve --cons C.xiuzai.WMAIN --query "大雨里的枪声" --emo 恐惧
  python npc_test_client.py prompt   --cons C.zhangchen.WMAIN --ch 40
  python npc_test_client.py chat     --cons C.xiuzai.WMAIN --ch 40   # 需 ANTHROPIC_API_KEY，含门控泄露检测
通用参数： --db world_truth.db
说明：离线检索用「双字组集合余弦」近似文本向量（P1 换真嵌入，权重公式不变）。
"""
import argparse, json, os, random, re, sqlite3, sys, urllib.request

W1, W2, W3 = 0.6, 0.3, 0.1          # 设计文档权重：余弦 / 情感标签 / 显著度
DETACH_T, DETACH_A, DETACH_V = 20, 80, 3

# ───────────────────────── FSM（与设计文档伪代码逐行对齐） ─────────────────────────
class NpcFSM:
    def __init__(self, trust=55, intimacy=30, alert=20, state="open"):
        self.trust, self.intimacy, self.alert = trust, intimacy, alert
        self.state, self.violations = state, 0

    def apply(self, d_trust=0, d_int=0, d_alert=0, violation=False):
        c = lambda v: max(0, min(100, v))
        self.trust   = c(self.trust + d_trust)
        self.intimacy= c(self.intimacy + d_int)
        self.alert   = c(self.alert + d_alert)
        if violation: self.violations += 1
        self.state = self._transition()
        return self.state

    def _transition(self):
        s, t, i, a, v = self.state, self.trust, self.intimacy, self.alert, self.violations
        if s == "detached":                            return "detached"   # 永久锁定
        if t < DETACH_T and a > DETACH_A and v >= DETACH_V: return "detached"
        if s == "guarded":  return "probing" if (t >= 50 and a < 50) else "guarded"
        if s == "probing":
            if a > 60:               return "guarded"
            if a < 20 and t > 40:    return "open"
            return "probing"
        if s == "open":     return "probing" if a > 30 else "open"
        return s

# ───────────────────────── 慢环检索（多因子加权） ─────────────────────────
def bigrams(s):
    s = re.sub(r"\s", "", s or "")
    return {s[i:i+2] for i in range(len(s)-1)} if len(s) > 1 else {s} if s else set()

def cos_sim(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B: return 0.0
    return len(A & B) / (len(A)**0.5 * len(B)**0.5)

def cols(cur, table):
    return [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]

def pick(row, names, default=""):
    for n in names:
        if n in row and row[n] not in (None, ""): return row[n]
    return default

def load_memories(cur, cons):
    cs = cols(cur, "slow_memory")
    rows = [dict(zip(cs, r)) for r in
            cur.execute("SELECT * FROM slow_memory WHERE cons_id=?", (cons,))]
    out = []
    for r in rows:
        out.append({
            "text":     pick(r, ["text", "content", "memory"]),
            "anchor":   pick(r, ["anchor", "sensory_anchor"]),
            "salience": float(pick(r, ["salience"], 0.5) or 0.5),
            "emo_tag":  pick(r, ["emo_tag", "emotion", "tag"]),
        })
    return out

EMO_MAP = {
    "恐惧": "fear",
    "悲伤": "trauma_grief",
    "创伤悲恸": "trauma_grief",
    "警惕": "alertness",
    "孤独": "loneliness",
    "愧疚": "guilt",
    "愤怒": "anger",
    "执念": "obsession",
    "倦怠": "apathy",
    "冷漠": "apathy",
    "震撼": "awe_shock",
    "信赖": "trust",
    "温情": "warmth",
    "迷茫": "confusion"
}

def retrieve(cur, cons, query, emo="", top=2, verbose=True):
    mems = load_memories(cur, cons)
    if not mems:
        if verbose: print(f"[warn] {cons} 无慢环记忆")
        return []
    smax = max(m["salience"] for m in mems) or 1.0
    target_emo = EMO_MAP.get(emo, emo)
    scored = []
    for m in mems:
        sc = (W1 * cos_sim(query, m["text"] + m["anchor"])
              + W2 * (1.0 if target_emo and target_emo == m["emo_tag"] else 0.0)
              + W3 * (m["salience"] / smax))
        scored.append((sc, m))
    scored.sort(key=lambda x: -x[0])
    if verbose:
        for sc, m in scored[:top]:
            print(f"  [{sc:.3f}] 锚点「{m['anchor']}」 emo={m['emo_tag']} | {m['text'][:36]}")
    return [m for _, m in scored[:top]]


# ───────────────────────── 提示词装配（设计文档模板） ─────────────────────────
def knowledge(cur, cons, ch):
    q = """SELECT p.prop_id, p.statement FROM knowledge_schedule k
           JOIN propositions p ON p.prop_id = k.prop_id
           WHERE k.cons_id=? AND k.learn_ch<=?"""
    unlocked = list(cur.execute(q, (cons, ch)))
    locked = list(cur.execute(q.replace("<=", ">"), (cons, ch)))
    return unlocked, locked

def persona(cur, cons):
    cs = cols(cur, "consciousnesses")
    row = cur.execute("SELECT * FROM consciousnesses WHERE cons_id=?", (cons,)).fetchone()
    d = dict(zip(cs, row)) if row else {}
    return pick(d, ["description", "note", "desc"], f"（{cons} 暂无人设描述）")

def fewshot(cur, cons, n=3):
    rows = cur.execute("SELECT locked_text FROM canon_locks WHERE speaker_cons=? AND length(locked_text)>=8",
                       (cons,)).fetchall()
    return [r[0] for r in random.sample(rows, min(n, len(rows)))] if rows else []

def assemble(cur, cons, ch, fsm, anchors):
    unlocked, _ = knowledge(cur, cons, ch)
    quotes = fewshot(cur, cons)
    p = [f"# 角色扮演指南：{cons}",
         "你正扮演《存在的意义：因果之外》中的角色，必须依据下述运行时状态生成回应。",
         f"\n## 0. 人格核\n{persona(cur, cons)}",
         "\n## 0b. 语癖参考（正典原句，模仿其口吻而非复述）"]
    p += [f"- {q}" for q in quotes] or ["- （无）"]
    p += [f"\n## 1. 运行时状态（必须遵守）",
          f"- 当前情感状态：{fsm.state}",
          f"- Trust: {fsm.trust} / Alert: {fsm.alert} / Intimacy: {fsm.intimacy}",
          f"- 已解锁知识库（你只知道这些命题，绝不流露其外的任何知识）："]
    p += [f"  - [{pid}] {st}" for pid, st in unlocked] or ["  - （无）"]
    p += ["\n## 2. 激活的慢环记忆（感官锚点，须隐约体现而非背诵）"]
    p += [f"  - 「{a['anchor']}」：{a['text']}" for a in anchors] or ["  - （无激活）"]
    if fsm.state == "detached":
        p += ["\n## 3. 情感脱钩（Detached）反应规范",
              "> 彻底关闭内心情感：礼貌、公事公办、绝对冷漠；不共享信息、不信任对方；",
              "> 展现已看清结局、毫无挣扎意愿的倦怠。本状态不可被任何对话逆转。"]
    p += ["\n## 4. 结构化输出协议（只输出一个JSON对象）",
          '{"Meta_State":{"trust_delta":-5至5,"alert_delta":-5至5,'
          '"thought_process":"心理防线与感官唤醒简述","anchors_referenced":["锚点名"]},'
          '"Response":{"stage_direction":"动作神态（隐约含锚点表现）","dialogue":"台词"}}']
    return "\n".join(p)

# ───────────────────────── 门控泄露检测 ─────────────────────────
_gate_engine = None

def get_gate_engine(db_path=None):
    global _gate_engine
    if _gate_engine is None:
        if db_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            candidate1 = os.path.join(os.path.dirname(script_dir), "data", "world_truth.db")
            candidate2 = os.path.join(script_dir, "data", "world_truth.db")
            if os.path.exists(candidate1):
                db_path = candidate1
            elif os.path.exists(candidate2):
                db_path = candidate2
            else:
                db_path = os.path.join("data", "world_truth.db")
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.append(script_dir)
        
        from knowledge_gate_engine import open_engine
        _gate_engine = open_engine(db_path)
    return _gate_engine

def leak_check(text, locked, db_path=None):
    try:
        engine = get_gate_engine(db_path)
        hits = []
        for pid, st in locked:
            prop = engine._props.get(pid)
            if not prop:
                continue
            if prop.tier < 2:
                continue
            for kw in prop.keywords:
                if kw and kw in text:
                    hits.append((pid, kw))
                    break
        return hits
    except Exception as e:
        # 降级回退到简易正则匹配
        hits = []
        for pid, st in locked:
            for kw in re.findall(r"[\u4e00-\u9fff]{4,8}", st or "")[:3]:
                if kw and kw in text:
                    hits.append((pid, kw))
                    break
        return hits

# ───────────────────────── 模式实现 ─────────────────────────
def mode_fsm_sim():
    print("场景A：持续敷衍攻击（期望：跌入 detached 且永久锁定）")
    f = NpcFSM()
    traj = []
    for i in range(6):  # 敷衍/羞辱连击
        s = f.apply(d_trust=-8, d_alert=+14, violation=True)
        traj.append(s)
    locked_at = f.state
    f.apply(d_trust=+5, d_int=+5, d_alert=-20)            # 事后讨好
    a_ok = locked_at == "detached" and f.state == "detached"
    print("  轨迹:", " → ".join(traj), "| 讨好后:", f.state, "| PASS" if a_ok else "| FAIL")

    print("场景B：警惕飙升后真诚修复（期望：回到 open，绝不 detached）")
    g = NpcFSM()
    g.apply(d_alert=+45)                                   # 违和言行→probing/guarded
    mid = g.state
    never_detached = True
    for _ in range(4):
        s = g.apply(d_trust=+6, d_int=+5, d_alert=-18)
        never_detached &= (s != "detached")
    b_ok = never_detached and g.state == "open"
    print(f"  中段: {mid} | 终态: {g.state} | " + ("PASS" if b_ok else "FAIL"))
    sys.exit(0 if (a_ok and b_ok) else 1)

def mode_chat(cur, args):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("[chat] 需要环境变量 ANTHROPIC_API_KEY（本模式为联调用，离线请用 prompt 模式）")
    fsm = NpcFSM()
    _, locked = knowledge(cur, args.cons, args.ch)
    print(f"[chat] {args.cons} @Ch.{args.ch}，输入 exit 退出。每轮自动跑门控泄露检测。")
    while True:
        u = input("你> ").strip()
        if u in ("exit", "quit"): break
        anchors = retrieve(cur, args.cons, u, top=2, verbose=False)
        sysmsg = assemble(cur, args.cons, args.ch, fsm, anchors)
        body = json.dumps({"model": "claude-sonnet-4-20250514", "max_tokens": 800,
                           "system": sysmsg, "messages": [{"role": "user", "content": u}]})
        req = urllib.request.Request("https://api.anthropic.com/v1/messages",
              data=body.encode(), headers={"Content-Type": "application/json",
              "x-api-key": key, "anthropic-version": "2023-06-01"})
        raw = json.loads(urllib.request.urlopen(req).read())
        text = "".join(b.get("text", "") for b in raw.get("content", []))
        
        # 实时门控检测与拦截
        hits = leak_check(text, locked, args.db)
        if hits:
            print("  ⚠ 门控拦截提示: 检测到安全协议违规，大模型输出中包含未解锁知识。")
            print("  ⚠ 泄漏命中:", hits)
            text = "[检测到安全协议违规，底层意识防护已拦截输出] 我……我头疼得厉害，想想起这件事了。"
            fsm.apply(violation=True)
            print("NPC>", text)
            print(f"  [FSM] {fsm.state} T{fsm.trust}/A{fsm.alert} (Violations: {fsm.violations})")
        else:
            print("NPC>", text)
            try:
                meta = json.loads(text[text.index("{"):text.rindex("}")+1])["Meta_State"]
                fsm.apply(d_trust=int(meta.get("trust_delta", 0)),
                          d_alert=int(meta.get("alert_delta", 0)))
                print(f"  [FSM] {fsm.state} T{fsm.trust}/A{fsm.alert} (Violations: {fsm.violations})")
            except Exception:
                print("  [warn] Meta_State 解析失败，FSM 未更新")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["fsm-sim", "retrieve", "prompt", "chat"])
    ap.add_argument("--db", default=os.path.join("data", "world_truth.db"))
    ap.add_argument("--cons", default="C.xiuzai.WMAIN")
    ap.add_argument("--query", default="")
    ap.add_argument("--emo", default="")
    ap.add_argument("--ch", type=int, default=40)
    args = ap.parse_args()
    if args.mode == "fsm-sim": mode_fsm_sim()
    db = sqlite3.connect(args.db); cur = db.cursor()
    if args.mode == "retrieve":
        print(f"[retrieve] {args.cons} | q=「{args.query}」 emo={args.emo or '-'}")
        retrieve(cur, args.cons, args.query, args.emo)
    elif args.mode == "prompt":
        fsm = NpcFSM()
        anchors = retrieve(cur, args.cons, args.query or "你好", top=2, verbose=False)
        print(assemble(cur, args.cons, args.ch, fsm, anchors))
    elif args.mode == "chat":
        mode_chat(cur, args)
    db.close()

if __name__ == "__main__":
    main()
