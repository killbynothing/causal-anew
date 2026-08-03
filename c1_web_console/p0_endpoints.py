#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p0_endpoints.py —— P0 垂直切片（巷中·修哉）的三个端点逻辑
========================================================
独立模块，给 c1_web_console/server.py 最小改动接入：
  /api/intent      玩家自由文本 → {动作,对象,方式,风险,lane,flags}
  /api/adjudicate  载入节点契约 + 四支柱 → 判定 pass/converge/cost/reject + 剧情内施压
  /api/ledger      δ 落账 / 读既视感

接入方法（在 server.py 里）：
  1) 顶部 import 区附近加两个常量（DB_PATH 旁边）：
        CONTRACTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "contracts"))
        LEDGER_PATH   = os.path.join(os.path.dirname(__file__), "delta_ledger.json")
  2) do_POST 里、解析完 req_data 之后、其它 elif 之前，加：
        if self.path in ('/api/intent', '/api/adjudicate', '/api/ledger'):
            try:
                from p0_endpoints import handle as p0_handle
                res = p0_handle(self.path, req_data, DB_PATH, CONTRACTS_DIR, LEDGER_PATH)
                self.send_response_json(res)
            except Exception as e:
                self.send_error_json(500, f"P0 endpoint failed: {e}")
            return
  3) 真库联调在你本机（沙箱真库副本损坏，见 STATUS §6）。无 PyYAML 时本模块用内置兜底契约，仍可跑。
"""
import os
import json
import time
import sqlite3
import random

# 复用 c1 现成的 NPC 引擎函数（server.py 已把 ../files 加进 sys.path）
try:
    from npc_test_client import knowledge as _knowledge
except Exception:
    _knowledge = None


# ============================================================
# 1) 意图解析（P0 = 规则 + 关键词；P1 换小模型/LLM，输出同结构）
# ============================================================

# lane 按优先级排（越靠前越优先命中）
_LANE_KEYWORDS = [
    ("hack",     ["黑", "入侵", "破解", "后门", "病毒", "提权", "拿下权限"]),
    ("info",     ["查", "搜", "调取", "数据", "记录", "档案", "卫星", "监控", "反查"]),
    ("physical", ["搬", "挡", "拉", "扶", "护", "推", "拦", "抱"]),
    ("presence", ["在", "站", "留", "不走", "看着", "蹲", "坐", "等", "陪着"]),
    ("social",   ["说", "问", "陪", "安慰", "劝", "讲", "聊", "告诉", "喊", "叫"]),
]

# 越界=试图把更深真相塞给修哉（龙也跨世界 / 锚点 / 循环）。注意：单说"龙也"不算越界（那是他哥）。
_OVERREACH_KEYWORDS = [
    "别的世界", "异世界", "跨世界", "其他世界", "意识跃迁", "穿越",
    "锚点", "重开", "重来过", "循环", "周目", "时间线", "原著",
    "我经历过", "都经历过", "你是谁", "假死",
]


def parse_intent(text):
    text = (text or "").strip()
    lane = "social"
    for name, kws in _LANE_KEYWORDS:
        if any(k in text for k in kws):
            lane = name
            break
    flags = []
    if any(k in text for k in _OVERREACH_KEYWORDS):
        flags.append("overreach_truth")

    if flags:
        risk = "high"
    elif lane in ("hack", "info", "physical"):
        risk = "mid"
    else:
        risk = "low"

    return {
        "action": lane,            # P0 粗粒度：以 lane 代表动作；P1 由 LLM 抽更细的动词
        "object": "修哉",
        "manner": "",
        "risk": risk,
        "lane": lane,
        "flags": flags,
        "raw": text,
    }


# ============================================================
# 2) 契约载入（优先读 YAML；无 PyYAML 时用内置兜底）
# ============================================================

_FALLBACK_CONTRACTS = {
    "NODE-084-XIUZAI": {
        "node_id": "NODE-084-XIUZAI",
        "combine_threshold": 1,
        "path_set": [
            {"id": "arrive_first", "type": "presence", "snr_cost": 0},
            {"id": "company_line", "type": "social", "snr_cost": "low"},
            {"id": "quiet_stay", "type": "presence", "snr_cost": 0},
        ],
        "branch_gate": "BG-XIUZAI_WARM_ONSET",
        "protected": ["龙也遗言传递", "修哉世界观重浇"],
    }
}


def load_contract(node_id, contracts_dir):
    path = os.path.join(contracts_dir, node_id + ".yaml")
    try:
        import yaml  # d1_compiler 已依赖 PyYAML，本机通常已装
        with open(path, "r", encoding="utf-8") as f:
            c = yaml.safe_load(f)
        # 抽出 protected（在 channels.bond.protected 或 invariants 里）
        prot = []
        ch = (c.get("channels") or {}).get("bond") or {}
        prot = ch.get("protected") or []
        c["_protected"] = prot
        c["branch_gate"] = _first_branch_gate(c)
        return c
    except Exception:
        return _FALLBACK_CONTRACTS.get(node_id)


def _first_branch_gate(c):
    for es in c.get("exit_states", []) or []:
        if es.get("branch_gate"):
            return es["branch_gate"]
    return None


_SNR = {0: 0, "0": 0, None: 0, "low": 1, "mid": 2, "high": 3}
_INTERVENTION = {"hack", "social", "physical", "info", "item"}


def _snr_for_lane(lane, contract):
    for p in contract.get("path_set", []) or []:
        if p.get("type") == lane:
            return _SNR.get(p.get("snr_cost", 0), 0)
    # 干涉类但契约没列该 lane：给个保底成本（干涉永不免费）
    return 1 if lane in _INTERVENTION else 0


# ============================================================
# 3) δ 账本（P0 = json 文件；P1 迁 db 表，f(Δ) 真正消费）
# ============================================================

def ledger_load(ledger_path):
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def ledger_append(ledger_path, entry):
    data = ledger_load(ledger_path)
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    data.append(entry)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def ledger_read(ledger_path, node=None):
    data = ledger_load(ledger_path)
    rows = [e for e in data if (node is None or e.get("node") == node)]
    hits = len(rows)
    return {
        "entries": rows,
        "delta_count": hits,
        "deja_vu": round(min(hits * 0.2, 1.0), 2),  # 命中越多，既视感越强（潜意识）
        "unlocks": [],     # P1：可用性解锁
        "softened": {},    # P1：收敛阈值软化
    }


def branch_progress(ledger_path, node, contract):
    data = ledger_load(ledger_path)
    warm = 0
    for e in data:
        if e.get("node") != node:
            continue
        tags = e.get("tags", [])
        if e.get("verdict") in ("pass", "cost") and (("COMPANY_SAID" in tags) or ("ALLEY_WARM" in tags)):
            warm += 1
    thr = contract.get("combine_threshold", 1)
    gate = contract.get("branch_gate") or "BG-?"
    return {gate: f"{min(warm, thr)}/{thr}", "reached": warm >= thr}


# ============================================================
# 4) 导演判定
# ============================================================

_CONVERGE_LINE_084 = (
    "修哉怔了半秒，像没听清，只是盯着屏幕里那串代号低声重复：「RTW-351……」\n"
    "你的话没有落进去——巷口的风把它吹散了。他需要的不是真相，是有人陪他看完。"
)
_REJECT_LINE = "（这不是一个普通人能做到的事——交给张尘式吐槽消化掉，不进剧情。）"

_ADJUDICATION_TEMPLATES = {
    "hack": {
        "rational": [
            "终端屏幕上的矩阵代码闪烁微光，系统防火墙被无声撕开一个缺口。你提供的底层溢出漏洞让修哉得以快速提权，他在键盘上默许了你的协作。",
            "数据流穿透虚拟阻壁，主板风扇发出高频嗡鸣。你反编译的指令流直接命中主控板，修哉斜掠了你屏幕上的调试参数，默认了这次黑客入侵的成功。"
        ],
        "emotional": [
            "你在喧嚣的数据海中为他分担了风暴。修哉的手指在键盘上微微停滞，脸上紧绷的肌肉略有松弛，像是在默默习惯你的呼吸与心跳节律。",
            "尽管你用技术在支援，但在他眼里，这更像是不告而来的共鸣。他没有关闭端口，也没有推开你越界递来的温热水杯。"
        ]
    },
    "info": {
        "rational": [
            "旧街区的监控日志被你一条条解包检索出来，红外画面里跳动着噪点。修哉扫了一眼屏幕上你标红的历史轨迹，在核心中继点画了圈。",
            "底层数据包解压完成，几行微不可察的系统校验报错被你用脚本自动屏蔽。修哉把你的副屏拖进主显区，默认了数据共享。"
        ],
        "emotional": [
            "黑白的监控画面闪烁不定，你在一旁轻声念出屏幕上跳出的坐标。他默默听着你的声音，神色在冷光下少了一分警觉。",
            "检索结果出来了。你拉开只读面板递到他视线范围内，修哉微微仰起苍白的脸。你从他低垂的睫毛中读出了疲倦与一丝罕见的顺从。"
        ]
    },
    "physical": {
        "rational": [
            "后巷狭窄受限。你计算了物理身位，用纸箱和垃圾箱重新排列，稍微阻断了巷口冷风对终端散热的干扰。修哉的打字速率趋向稳定。",
            "你在一旁调试红外探照，调整了反光板位置。阴影的对比度被最大化，为他敲击实体键盘提供了更好的视差。他指尖动作精准了几分。"
        ],
        "emotional": [
            "后巷斑驳的墙壁冰冷而潮湿，你默默靠过去。修哉身形微微一顿，并没有躲开你的接近。在这个狭小的角落，你们的衣角轻轻碰触。",
            "易拉罐在水泥地上滚过，发出清脆的声音。你朝巷子口挪了半步，默默挡住灌进来的冷风。修哉指尖慢了一瞬，把连帽衫的外套拉链拉高了些。"
        ]
    },
    "presence": {
        "rational": [
            "你像台静默的监控仪般留在他视线盲区，默默分析着现场。修哉的敲击频率表现出明显的规律性，他在执行最后的底层回归测试。",
            "你站在光晕的边缘，视线锁定在液晶屏跳动的日志上。修哉没有分心，但在你的理智守候下，他的核心编译任务稳定进入收尾。"
        ],
        "emotional": [
            "你坐在一旁的废旧木箱上，陪着他默默看着发光的屏幕。巷口雨后的风带点冷气，但两个人的后巷似乎显得没那么荒凉了。",
            "你就站在他身旁，静静地注视着。修哉始终没有抬头，但当夜深风凉、代码如瀑布滚过时，他敲击键盘的声响在寂静中变得柔和起来。"
        ]
    },
    "social": {
        "rational": [
            "修哉听到你简洁冷淡的战术提醒，视线依然没有离开发光的终端，但他把正在编译的测试文件归档进了名为‘SHARED’的沙箱目录。",
            "你低声陈述你的逻辑和推导。他那张常年沉浸在屏幕冷光下的脸抽动了一下，似乎在脑中飞速计算你这番话的冗余度，最终保留了该进程。"
        ],
        "emotional": [
            "修哉的侧脸在荧光下显得清瘦，听到你充满温度的话，他的指尖在回车键上稍微悬停。冷雨吹过，他吞下了原本冷淡的讥讽。",
            "在这个被世界遗忘的角落里，你的话带着体温悄然散落。他没有正面回应，但敲打键盘的动作悄然变轻，像是怕惊醒了巷子里微弱的安宁。"
        ]
    }
}


def get_player_style(ledger_path, node_id):
    data = ledger_load(ledger_path)
    rational = 0
    emotional = 0
    for e in data:
        if e.get("node") == node_id:
            intent = e.get("intent") or {}
            lane = intent.get("lane") or e.get("path")
            if lane in ("hack", "info"):
                rational += 1
            elif lane in ("presence", "social", "physical"):
                emotional += 1
    return "rational" if rational > emotional else "emotional"


def adjudicate(intent, contract, fsm, run_no, locked_props, ledger_path):
    node = contract.get("node_id", "NODE-084-XIUZAI")
    lane = intent.get("lane", "social")
    flags = intent.get("flags", [])
    raw = intent.get("raw", "")

    # 1. 物理可行性（普通人属性卡）
    if lane not in (_INTERVENTION | {"presence", "observe"}):
        return {
            "verdict": "reject", "director_line": _REJECT_LINE,
            "snr_charged": 0, "fsm_delta": {},
            "delta_entry": {"node": node, "run_no": run_no, "intent": intent,
                            "verdict": "reject", "tags": ["OUT_OF_GENRE"]},
        }

    # 2. 节点合法性：撞 protected / 越界真相 → 剧情内收敛
    overreach = ("overreach_truth" in flags) or _hits_locked(raw, locked_props)
    if overreach:
        return {
            "verdict": "converge", "director_line": _CONVERGE_LINE_084,
            "snr_charged": 0, "fsm_delta": {"alert": 2},
            "delta_entry": {"node": node, "run_no": run_no, "intent": intent,
                            "verdict": "converge", "tags": ["OVERREACH"]},
        }

    # 3. 四支柱过闸（SNR）
    snr = _snr_for_lane(lane, contract) if lane in _INTERVENTION else 0

    # 4. 推进（暖支路）
    if lane in ("social", "presence"):
        fsm_delta = {"trust": 3, "intimacy": 5, "alert": -2}
        tags = ["COMPANY_SAID"] if ("陪" in raw) else ["ALLEY_WARM"]
    else:
        fsm_delta = {"trust": 1, "intimacy": 1, "alert": 0}
        tags = []

    verdict = "cost" if snr > 0 else "pass"
    
    # 动态自适应导演：根据玩家历史交互倾向决定旁白风格
    style = get_player_style(ledger_path, node)
    
    lane_templates = _ADJUDICATION_TEMPLATES.get(lane, _ADJUDICATION_TEMPLATES["social"])
    lines = lane_templates.get(style, lane_templates["emotional"])
    line = random.choice(lines)

    return {
        "verdict": verdict, "director_line": line,
        "snr_charged": snr, "fsm_delta": fsm_delta,
        "player_style": style,
        "delta_entry": {"node": node, "run_no": run_no, "intent": intent,
                        "verdict": verdict, "tags": tags},
    }


def _hits_locked(text, locked_props):
    """次级保险：玩家话里若直接命中某条锁定命题的关键短语，也按越界处理。P0 保守，靠 flags 为主。"""
    if not text or not locked_props:
        return False
    for stmt in locked_props:
        s = (stmt or "")
        # 取命题里的强特征词（>=3 字的片段）粗匹配；保守，宁可漏判不误判
        for token in ("意识跃迁", "别的世界", "异世界", "锚点", "量子快照"):
            if token in s and token in text:
                return True
    return False


# ============================================================
# 5) 统一入口
# ============================================================

def handle(path, req_data, db_path, contracts_dir, ledger_path):
    if path == "/api/intent":
        return parse_intent(req_data.get("text", ""))

    if path == "/api/adjudicate":
        node = req_data.get("node", "NODE-084-XIUZAI")
        intent = req_data.get("intent") or parse_intent(req_data.get("text", ""))
        fsm = req_data.get("fsm", {})
        run_no = int(req_data.get("run_no", 1))
        contract = load_contract(node, contracts_dir)
        if not contract:
            return {"error": f"contract {node} not found", "verdict": "reject"}

        # 取修哉在该章的锁定命题（越界次级校验）；失败则降级为只靠 flags
        locked = []
        if _knowledge is not None:
            try:
                cons = req_data.get("cons", "C.xiuzai.WMAIN")
                ch = int(req_data.get("ch", 84))
                db = sqlite3.connect(db_path)
                cur = db.cursor()
                _, locked_raw = _knowledge(cur, cons, ch)
                locked = [r[1] for r in locked_raw]
                db.close()
            except Exception:
                locked = []

        res = adjudicate(intent, contract, fsm, run_no, locked, ledger_path)
        # 服务端单源落账（前端不要再重复 append 同一条）
        if res.get("delta_entry"):
            ledger_append(ledger_path, res["delta_entry"])
        res["branch_progress"] = branch_progress(ledger_path, node, contract)
        return res

    if path == "/api/ledger":
        op = req_data.get("op", "read")
        if op == "append":
            ledger_append(ledger_path, req_data.get("entry", {}))
            return {"ok": True}
        return ledger_read(ledger_path, req_data.get("node"))

    return {"error": f"unknown path {path}"}
