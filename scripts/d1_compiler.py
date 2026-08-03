#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D1 节点契约编译器 v0.1
=====================
把 YAML 节点契约 → 四个编译错误码校验 + event_uid 外键校验 → 合规者入库 node_contracts。
依据《节点契约_草案_第一部.md》§三校验清单 + 《高维机制四支柱设计书》编译不变式。

四个永不允许白名单绕过的编译错误码：
  E_SELF_REF          exit_states 试图回滚 causal_constants 锁链上的任一环
  E_XLINE_CHANNEL     声明了跨线通讯(crossline_comm)却未声明合法 channel
  E_FREE_INTERVENTION 干涉类路径未声明 snr_cost（干涉永不免费）
  E_COHERENCE_PHASE   横向跳者与玩家同框却未声明 coherence.phase

用法：
  python scripts/d1_compiler.py --db world_truth.db --contracts contracts/        # 编译入库
  python scripts/d1_compiler.py --db world_truth.db --contracts contracts/ --check-only   # 只校验不入库
  （从项目根目录运行）
"""
import argparse, json, os, re, sqlite3, sys, glob
try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml --break-system-packages")

VALID_CHANNELS = {"LT_ANCHOR", "PHONE", "DATAPACK"}
# 干涉类型（需 snr_cost）；observe/presence/structural 为非干涉，免 snr
INTERVENTION_TYPES = {"hack", "social", "physical", "info", "item"}
# 横向跳者（与玩家同框需声明 coherence.phase）；可随同位体建档扩充
LATERAL_JUMPERS = {"C.dust.W1"}   # 异世界张尘 ID 定名后加入
VALID_PHASES = {"aligned", "neutral", "opposed"}
OPENING_MAP_PATH = os.path.join("c1_web_console", "opening_map.json")


class CompileError(Exception):
    def __init__(self, code, node_id, detail):
        self.code, self.node_id, self.detail = code, node_id, detail
        super().__init__(f"[{code}] {node_id}: {detail}")


def load_locked_consts(conn):
    """从 causal_constants 取锁链全集：const_id + dependency_chain 上的所有环。"""
    locked = set()
    try:
        for r in conn.execute("SELECT const_id, dependency_chain FROM causal_constants"):
            locked.add(r[0])
            try:
                locked.update(json.loads(r[1] or "[]"))
            except json.JSONDecodeError:
                pass
    except sqlite3.OperationalError:
        print("  ⚠ causal_constants 表不存在——请先跑 A2_mechanics_migration.sql")
    return locked


def event_exists(conn, uid):
    """event_uid 在 events(run=0).payload 内存在性校验。"""
    row = conn.execute(
        "SELECT 1 FROM events WHERE run=0 AND json_extract(payload,'$.event_uid')=? LIMIT 1", (uid,)
    ).fetchone()
    return row is not None


def load_event_uids(conn):
    """Preload run=0 event_uid values once; avoids json_extract scans per contract entry."""
    event_uids = set()
    try:
        rows = conn.execute("SELECT payload FROM events WHERE run=0")
    except sqlite3.OperationalError:
        return event_uids
    for (payload,) in rows:
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            continue
        uid = data.get("event_uid") if isinstance(data, dict) else None
        if uid:
            event_uids.add(str(uid))
    return event_uids


def load_opening_map():
    if not os.path.exists(OPENING_MAP_PATH):
        return {}
    with open(OPENING_MAP_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _event_tokens(text):
    return set(re.findall(r"E\d{3}-\d{2}", str(text or "")))


def _contract_scene_candidates(contract, opening_map):
    entries = set(contract.get("entry_conditions", []) or [])
    if not entries:
        return []
    matches = []
    for place, place_info in (opening_map or {}).items():
        chapters = (place_info or {}).get("chapters", {}) or {}
        for ch_key, chapter in chapters.items():
            encounter_tokens = set()
            for encounter in chapter.get("encounters", []) or []:
                encounter_tokens.update(_event_tokens(encounter.get("canon_src")))
                encounter_tokens.update(_event_tokens(encounter.get("canon_anchor")))
            if entries & encounter_tokens:
                matches.append((place, ch_key, chapter))
    return matches


def validate(contract, conn, locked_consts, opening_map=None, event_uids=None):
    """对单个契约跑全部校验；通过返回规范化 dict，否则抛 CompileError。"""
    nid = contract.get("node_id", "<no-id>")

    # 0. event_uid 外键（容器节点可无 entry_conditions）
    for uid in contract.get("entry_conditions", []) or []:
        if isinstance(uid, str) and uid.startswith("E") and not uid.startswith("E_"):
            exists = uid in event_uids if event_uids is not None else event_exists(conn, uid)
            if not exists:
                raise CompileError("E_FK_EVENT", nid, f"entry event_uid '{uid}' 不在 events(run=0)")

    # 1. E_SELF_REF：exit_states 的 negates 命中锁链
    for ex in contract.get("exit_states", []) or []:
        for neg in ex.get("negates", []) or []:
            if neg in locked_consts:
                raise CompileError("E_SELF_REF", nid,
                                   f"exit '{ex.get('id')}' 试图回滚锁链环 '{neg}'（复活/翻案被焊死）")

    # 2. E_XLINE_CHANNEL：声明跨线却无合法 channel
    if contract.get("crossline_comm"):
        ch = contract.get("channel")
        if ch not in VALID_CHANNELS:
            raise CompileError("E_XLINE_CHANNEL", nid,
                               f"crossline_comm=true 但 channel='{ch}' 非法（须 {VALID_CHANNELS}）")

    # 3. E_FREE_INTERVENTION：干涉类路径缺 snr_cost
    for p in contract.get("path_set", []) or []:
        if p.get("type") in INTERVENTION_TYPES and "snr_cost" not in p:
            raise CompileError("E_FREE_INTERVENTION", nid,
                               f"干涉路径 '{p.get('id')}'(type={p.get('type')}) 未声明 snr_cost")

    # 4. E_COHERENCE_PHASE：横向跳者×玩家同框却无 phase
    coh = contract.get("coherence", {}) or {}
    witnesses = set(contract.get("witnesses", []) or [])
    lateral_present = coh.get("lateral_jumper_present") or bool(witnesses & LATERAL_JUMPERS)
    if lateral_present and coh.get("player_present"):
        if coh.get("phase") not in VALID_PHASES:
            raise CompileError("E_COHERENCE_PHASE", nid,
                               f"横向跳者与玩家同框，coherence.phase='{coh.get('phase')}' 须 ∈ {VALID_PHASES}")

    # 5. E_PATH_UNWIRED：path_set 声明了，场景里必须至少有一个 player_choice 拍
    if contract.get("path_set"):
        candidates = _contract_scene_candidates(contract, opening_map or {})
        if not candidates:
            return contract
        wired = any(
            any(beat.get("beat_type") == "player_choice" for beat in (chapter.get("dialogue_flow", []) or []))
            for _place, _ch, chapter in candidates
        )
        if not wired:
            labels = [f"{place}@ch{ch_key}" for place, ch_key, _chapter in candidates]
            raise CompileError("E_PATH_UNWIRED", nid,
                               f"path_set 已声明，但对应场景 {labels} 没有 player_choice 拍")

    return contract


def compile_contracts(db_path, contracts_dir, check_only=False):
    conn = sqlite3.connect(db_path)
    locked = load_locked_consts(conn)
    event_uids = load_event_uids(conn)
    opening_map = load_opening_map()
    files = sorted(glob.glob(os.path.join(contracts_dir, "*.yaml")) +
                   glob.glob(os.path.join(contracts_dir, "*.yml")))
    if not files:
        print(f"  (无契约文件于 {contracts_dir})"); conn.close(); return 0, 0
    ok, fail = 0, 0
    for fp in files:
        docs = [d for d in yaml.safe_load_all(open(fp, encoding="utf-8")) if d]
        for c in docs:
            nid = c.get("node_id", "<no-id>")
            try:
                validate(c, conn, locked, opening_map=opening_map, event_uids=event_uids)
            except CompileError as e:
                print(f"  [FAIL] {e}"); fail += 1; continue
            if not check_only:
                conn.execute("INSERT OR REPLACE INTO node_contracts(node_id, part, contract) VALUES (?,?,?)",
                             (nid, c.get("part"), json.dumps(c, ensure_ascii=False)))
            print(f"  [OK]   {nid}{'（已入库）' if not check_only else ''}")
            ok += 1
    if not check_only:
        conn.commit()
    conn.close()
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join("data", "world_truth.db"))
    ap.add_argument("--contracts", default="contracts")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        sys.exit(f"[FAIL] 找不到数据库：{args.db}")
    print(f"D1 编译器 v0.1 ｜ db={args.db} ｜ contracts={args.contracts} ｜ {'仅校验' if args.check_only else '编译入库'}")
    ok, fail = compile_contracts(args.db, args.contracts, args.check_only)
    print(f"\n结果：{ok} 通过，{fail} 失败")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
