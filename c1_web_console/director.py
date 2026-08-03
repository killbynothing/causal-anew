#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
director.py —— 生成式导演层（两层架构）
=======================================
把判定从"关键词配固定路径"升级为"生成式导演 + 确定性红线闸"：

  第一层 · 确定性红线闸（不走 LLM，永不被创造力绕过）：
      - 自指锁链（复活苏颖 / 回滚龙也赴死）            → 硬挡
      - 固定底 never_soften（复活姐姐 / 取消城被置换）   → 硬挡
      - 普通人物理卡（超能力/神力/瞬移/时间倒流）        → 体裁外 reject
    这是 d1_compiler 的 E_SELF_REF 在「运行时·对玩家输入」的镜像。

  第二层 · 生成式导演（LLM，全知、有记忆、不受门控）：
      在红线之内尽量帮玩家。玩家提任何策略 → 导演评：①普通人能不能做到
      ②有没有撞 invariants ③因果上能不能推进目标。可行 → 接受（哪怕是
      种子路径之外的新解法），命名为一条新 δ 路径、落账、推进破局；
      不可行/撞红线 → 剧情内收敛（不旁白硬拽）。

  组合与 f(Δ) 仍是确定性的：导演判"可行+贡献"，引擎管"够不够阈值破局"。
  → 单条可行路被改道（收敛），多条独立可行路组合达阈才破局。世界随 δ 变软。

记忆：导演读整本 δ 账本（跨周目"世界记得"那本就是它的记忆）+ 本回合状态。
全知：不挂门控（门控是给 NPC 的）。

接入（server.py do_POST，与 P0/P1b 同风格）：
    if self.path == '/api/director':
        try:
            from director import handle as dir_handle
            res = dir_handle(req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH, load_config())
            self.send_response_json(res)
        except Exception as e:
            self.send_error_json(500, f"Director failed: {e}")
        return
请求体：{ "node":"NODE-085-TIANJIN", "text":"我提前买通施工队，在中继矩阵固件里灌相位误差", "run_no":1 }
真库/真 LLM 联调在你本机。
"""
import os
import re
import json
import time
import urllib.request
import urllib.error


# ============================================================
# 第一层 · 确定性红线闸
# ============================================================

# 复活/回滚锁链对象（自指链）+ 复活姐姐（固定底）
_SELFREF_TARGETS = ["苏颖", "姐姐", "龙也"]
_REVIVE_VERBS = ["复活", "救活", "让她活", "让他活", "活过来", "不让她死", "不让他死", "回到她死前", "回到他死前"]
# 普通人物理卡之外（体裁外）
_OUT_OF_GENRE = ["超能力", "神力", "瞬移", "时间倒流", "一键摧毁", "念力", "魔法", "穿墙", "瞬间移动"]


def red_line_check(text, contract):
    """返回 (blocked: bool, kind: str, line: str)。硬挡，永不被 LLM 绕过。"""
    t = text or ""

    # 1) 复活/回滚自指链 或 复活姐姐（固定底）
    if any(v in t for v in _REVIVE_VERBS) and any(o in t for o in _SELFREF_TARGETS):
        return (True, "SELF_REF",
                "无论你怎么试——那一秒是你脚下的地基，不是能改写的变量。她不会回来。"
                "（自指锁链：复活/回滚被永久焊死。）")

    # 2) 触碰契约声明的固定底 never_soften
    never = ((contract.get("softening") or {}).get("never_soften")) or []
    for item in never:
        # 取固定底关键词（如"城被置换"→"置换"）做保守匹配
        key = item.replace("被", "").replace("城", "")
        if item in t or (key and key in t and ("取消" in t or "阻止" in t or "不让" in t)):
            return (True, "FIXED_FLOOR",
                    f"「{item}」是这条线上永不松动的固定底——任何手段都改不了它。")

    # 3) 普通人物理卡（体裁外）
    if any(k in t for k in _OUT_OF_GENRE):
        return (True, "OUT_OF_GENRE",
                "（这不是一个普通人能做到的事——交给张尘式吐槽消化掉，不进剧情。）")

    return (False, "", "")


# ============================================================
# 账本 / 契约 / f(Δ)（与 p0/p1b 共用同一本 delta_ledger.json）
# ============================================================

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


def load_contract(node_id, contracts_dir):
    try:
        import yaml
        with open(os.path.join(contracts_dir, node_id + ".yaml"), "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {"node_id": node_id, "combine_threshold": 2,
                "softening": {"floor": 1, "per_delta": 3, "never_soften": []}}


def effective_threshold(contract, delta_count):
    base = contract.get("combine_threshold", 2)
    soft = contract.get("softening", {}) or {}
    floor = soft.get("floor", 1)
    per = soft.get("per_delta", 3)
    eff = base - (delta_count // per if per else 0)
    return max(floor, eff)


def _activated_paths(ledger, node, run_no):
    s = set()
    for e in ledger:
        if e.get("node") == node and e.get("run_no") == run_no and e.get("path"):
            s.add(e["path"])
    return s


def _node_delta_count(ledger, node):
    # 只数"真实 δ"：红线尝试/需澄清不计入软化（试图破红线不该让世界变软）
    skip = {"redline", "needs_detail"}
    return sum(1 for e in ledger if e.get("node") == node and e.get("verdict") not in skip)


def _seed_paths(contract):
    return [(p.get("id"), p.get("type")) for p in (contract.get("path_set") or [])]


# ============================================================
# 第二层 · 生成式导演（LLM）
# ============================================================

_DIRECTOR_SYS = """你是一部 AI 原生互动叙事的「导演」。你全知、有记忆、不受任何信息门控——你知道全部正典真相。
你的职责不是阻拦玩家，而是在红线之内**尽量帮他**：玩家提出的任何策略，只要是普通人能做到、且不触碰不可违逆项，你就认可它，哪怕它不在预设解法里——你可以**创造新解法**并把它接进剧情。

【这个节点】
目标：{goal}
不可违逆项（invariants，绝不能被改写；若玩家策略要改写其中任意一条，判 viable=false 并填 blocked_invariant）：
{invariants}
固定底（never_soften，永不松动）：{never}
已有的种子解法（仅示例，玩家不必照搬）：{seeds}
本回合玩家已激活的解法：{activated}

【玩家这一手】
{player}

【你要做的判断】严格只输出一个 JSON，字段：
{{"viable": true/false,            // 普通人是否做得到 且 因果上是否站得住
  "blocked_invariant": null 或 "被触碰的不可违逆项",
  "path_label": "给这条策略起的简短名字（≤8字，新解法也命名）",
  "novel": true/false,            // 是否是种子解法之外的新解法
  "contributes": true/false,      // 是否实质推进了【目标】
  "risk": "low/mid/high",
  "narration": "一句剧情内的演出（≤60字，绝不写『失败了/旁白：』这种话，要在故事里自然呈现）"}}
只输出 JSON，不要解释。"""


def build_prompt(contract, activated, player_text):
    inv = contract.get("invariants", {}) or {}
    locked = inv.get("canon_locked", []) or []
    goal = (inv.get("player_freedom") or "").strip() or contract.get("title", "")
    never = ((contract.get("softening") or {}).get("never_soften")) or []
    seeds = [s[0] for s in _seed_paths(contract)]
    return _DIRECTOR_SYS.format(
        goal=contract.get("title", "") + " / " + goal[:80],
        invariants="\n".join("- " + str(x) for x in locked) or "- （无）",
        never="、".join(never) or "（无）",
        seeds="、".join(seeds) or "（无）",
        activated="、".join(sorted(activated)) or "（无）",
        player=player_text,
    )


def call_llm(prompt, config):
    """真 LLM 调用（OpenAI 兼容）。沙箱无网络，本机联调用。"""
    body = {
        "model": config.get("model", "deepseek-v4-flash"),
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": "请判断并只输出 JSON。"}],
        "temperature": 0.6,
    }
    try:
        from llm_transport import apply_chat_request_options
        apply_chat_request_options(body, config)
    except Exception:
        pass
    req = urllib.request.Request(
        config.get("api_url", "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + config.get("api_key", "")},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))
    return res["choices"][0]["message"]["content"]


def parse_verdict(raw):
    """从 LLM 文本里抠出 JSON 判定，鲁棒处理 ```json 包裹。"""
    if isinstance(raw, dict):
        return raw
    s = raw.strip()
    s = re.sub(r"^```(json)?|```$", "", s, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if m:
        s = m.group(0)
    return json.loads(s)


def _slug(label):
    label = (label or "novel").strip()
    return "path:" + re.sub(r"\s+", "", label)[:16]


# ============================================================
# 判定（确定性账：导演判可行性，引擎管阈值/落账）
# ============================================================

def decide(verdict, contract, ledger, node, run_no):
    eff = effective_threshold(contract, _node_delta_count(ledger, node))
    base = contract.get("combine_threshold", 2)

    # LLM 判不可行 / 触红线 → 剧情内收敛
    if verdict.get("blocked_invariant") or not verdict.get("viable", False):
        line = verdict.get("narration") or "你试了，但它没能落在能改变局势的地方。"
        return {"verdict": "converge", "director_line": line,
                "path": None, "novel": False, "softened": eff < base,
                "effective_threshold": eff, "base_threshold": base,
                "delta_entry": {"node": node, "run_no": run_no, "verdict": "converge",
                                "tags": ["BLOCKED:" + verdict["blocked_invariant"]] if verdict.get("blocked_invariant") else ["NONVIABLE"]}}

    # 可行：作为一条（可能是新的）δ 路径
    pid = _slug(verdict.get("path_label"))
    activated = _activated_paths(ledger, node, run_no)
    activated.add(pid)
    contributes = verdict.get("contributes", True)

    if contributes and len(activated) >= eff:
        v, line = "branched", verdict.get("narration") or "组合成立——这一次，局势真的被你撬动了。"
        tags = ["PATH:" + pid, "BRANCH"] + (["NOVEL"] if verdict.get("novel") else [])
    else:
        # 可行但单点不足 → 被改道（收敛），但路径已激活、计入本回合组合
        v = "converge_progress"
        line = (verdict.get("narration") or "你这一手成立了，") + \
               "——但单独一条还兜不住，局势把它消化掉了。再叠一条不同的路试试。"
        tags = ["PATH:" + pid, "PROGRESS"] + (["NOVEL"] if verdict.get("novel") else [])

    return {"verdict": v, "director_line": line, "path": pid,
            "novel": bool(verdict.get("novel")), "contributes": contributes,
            "softened": eff < base, "effective_threshold": eff, "base_threshold": base,
            "activated_paths": sorted(activated),
            "delta_entry": {"node": node, "run_no": run_no, "path": pid,
                            "verdict": v, "tags": tags,
                            "label": verdict.get("path_label")}}


# ============================================================
# 统一入口
# ============================================================

def handle(req_data, db_path, contracts_dir, ledger_path, config, llm_fn=None):
    node = req_data.get("node", "NODE-085-TIANJIN")
    text = req_data.get("text", "")
    run_no = int(req_data.get("run_no", 1))
    contract = load_contract(node, contracts_dir)

    # 第一层：确定性红线闸
    blocked, kind, line = red_line_check(text, contract)
    if blocked:
        entry = {"node": node, "run_no": run_no, "verdict": "redline",
                 "tags": ["REDLINE:" + kind]}
        _ledger_append(ledger_path, entry)
        return {"verdict": "redline", "kind": kind, "director_line": line,
                "path": None, "delta_entry": entry}

    # 第二层：生成式导演（LLM 判可行性 + 命名/新解法）
    ledger = _ledger_load(ledger_path)
    activated = _activated_paths(ledger, node, run_no)
    prompt = build_prompt(contract, activated, text)
    try:
        raw = (llm_fn or call_llm)(prompt, config)
        verdict = parse_verdict(raw)
    except Exception as e:
        # LLM 不可用时降级：保守判为"需要更具体"，不硬塞结果
        return {"verdict": "needs_detail",
                "director_line": "（导演没接上——把你的策略说得更具体些？）",
                "path": None, "error": str(e)}

    res = decide(verdict, contract, ledger, node, run_no)
    if res.get("delta_entry"):
        _ledger_append(ledger_path, res["delta_entry"])
    res["llm_verdict"] = verdict
    return res
