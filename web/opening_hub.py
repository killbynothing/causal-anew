#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opening_hub.py —— 第一部开场 地点枢纽与主持人调度模块 (v0.5)
======================================================
管理 Ch.8-12 阶段的单线开场探索、原著匿名对话流、自报姓名记账，
以及离场过天推进（调 world_sim 推进离场 tick）。
"""

import os
import json
import time
import random

_HERE = os.path.dirname(__file__)
_MAP_PATH = os.path.join(_HERE, "opening_map.json")

_NAMES = {
    "C.kakashi.WMAIN": "晴明",  # 化名为晴明
    "C.xiuzai.WMAIN": "折原修哉",
    "C.akito.WMAIN": "川口秋人",
}

_ANON_NAMES = {
    "C.kakashi.WMAIN": "银发青年",
    "C.akito.WMAIN": "圆脸青年",
    "C.xiuzai.WMAIN": "黑发青年",
}

_COVER_IDENTITY = {
    "C.kakashi.WMAIN": {"name": "坂本晴明", "backstory": "来北京散心旅游的日本游客"},
    "C.xiuzai.WMAIN": {"name": "折原修哉", "backstory": "和同伴一起来北京短暂停留的年轻游客"},
    "C.akito.WMAIN": {"name": "川口秋人", "backstory": "和朋友同行、对陌生人保持谨慎的普通青年"},
}

_TABOO_LIST = {
    "C.kakashi.WMAIN": ["人造人", "写轮眼", "神威", "雷切", "RTW-131", "世界政府", "命案", "日本逃亡"],
    "C.xiuzai.WMAIN": ["龙也真相", "折原家灭门", "世界政府", "RTW", "晴明君机体", "异世界修哉", "终局死亡"],
    "C.akito.WMAIN": ["世界线", "记忆芯片", "多维记忆", "世界政府", "终局真相", "既视感机制"],
}

def _load_map():
    if not os.path.exists(_MAP_PATH):
        raise FileNotFoundError(f"opening_map.json 缺失在: {_MAP_PATH}")
    with open(_MAP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _handle_look(req_data, db_path, ledger_path, config):
    ch = int(req_data.get("ch", 8))
    map_data = _load_map()
    places = []
    ch_str = str(ch)

    for place_name, place_info in map_data.items():
        if place_name.startswith("_"):
            continue
        # 仅返回该章节唯一的剧情发生地点
        if "chapters" in place_info and ch_str in place_info["chapters"]:
            places.append({
                "id": place_name,
                "blurb": place_info.get("blurb", "")
            })
            break # 单流程，一章只有一处

    # 主持人旁白，体现普通学生与龙也信物的背景，隐去NPC人名
    if ch == 8:
        host_text = (
            "北京的清晨。你刚刚抵达这座城市，龙也留给你的嘱托依旧压在心头。信物还在怀中，你对这块全然陌生的地方和那几个隐约的目标线索还毫无头绪。\n"
            "天安门广场的方向人声渐起，听说有一批从外地来的年轻游客天天去那看升国旗……\n"
            "**你想去看看吗？**"
        )
    else:
        default_blurbs = [
            f"北京的清晨凉风习习。你打算在城区走走。现在是第 {ch} 章认识期，你想去哪里看看？",
            f"日光透过树叶洒在京城的胡同里。你想起龙也对这群年轻人的挂念，打算继续探寻。现在是第 {ch} 章，前往何处？",
            f"微风吹过北京的街道，龙也交代的事情让你无法懈怠。第 {ch} 章，今天你打算去哪里？"
        ]
        host_text = random.choice(default_blurbs)

    return {
        "host_text": host_text,
        "places": places
    }


def _handle_go(req_data, db_path, ledger_path, config):
    ch = int(req_data.get("ch", 8))
    place = req_data.get("place", "").strip()
    map_data = _load_map()
    ch_str = str(ch)

    if place not in map_data:
        return {"error": f"未知的地点: {place}"}

    place_info = map_data[place]
    if "chapters" not in place_info or ch_str not in place_info["chapters"]:
        return {"error": f"地点 {place} 在第 {ch} 章无遭遇数据"}

    chapter_info = place_info["chapters"][ch_str]
    encounters = chapter_info.get("encounters", [])
    if not encounters:
        encounter_beat = "你在四周看了看，没有发现什么特别的。"
    else:
        encounter = random.choice(encounters)
        encounter_beat = encounter.get("beat", "")

    present_ids = chapter_info.get("present", [])
    # 接触列表渲染：初遇匿名阶段对玩家显示形容词
    present = [{"cons": cid, "name": _ANON_NAMES.get(cid, "陌生青年")} for cid in present_ids]
    dialogue_flow = chapter_info.get("dialogue_flow", [])

    host_text = f"你来到了【{place}】。{place_info.get('blurb', '')}"

    return {
        "host_text": host_text,
        "present": present,
        "encounter_beat": encounter_beat,
        "dialogue_flow": dialogue_flow
    }


def _handle_meet(req_data, db_path, ledger_path, config):
    cons = req_data.get("cons", "").strip()
    ch = int(req_data.get("ch", 8))
    place = req_data.get("place", "").strip()
    run_no = int(req_data.get("run_no", 1))

    if not cons:
        return {"error": "Missing parameter 'cons'"}

    from world_sim import ledger_load, ledger_append

    ledger_entries = ledger_load(ledger_path)
    already_met = False
    for entry in ledger_entries:
        if entry.get("type") == "acquaint" and entry.get("cons") == cons and int(entry.get("run_no", 1)) == run_no:
            already_met = True
            break

    first_met = not already_met
    if first_met:
        new_entry = {
            "type": "acquaint",
            "cons": cons,
            "ch": ch,
            "place": place,
            "run_no": run_no,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        ledger_append(ledger_path, new_entry)

    anon_name = _ANON_NAMES.get(cons, "陌生人")

    chat_params = {
        "cons": cons,
        "ch": ch,
        "trust": 50,
        "intimacy": 20,
        "alert": 20,
        "state": "open",
        "anon_name": anon_name
    }

    map_data = _load_map()
    place_info = map_data.get(place, {})
    chapter_info = place_info.get("chapters", {}).get(str(ch), {})
    present_ids = chapter_info.get("present", [])
    present_characters = [
        {"cons": cid, "name": _ANON_NAMES.get(cid, "陌生青年")}
        for cid in present_ids
    ]
    scene_config = {
        "location": place or "未知地点",
        "current_beat": req_data.get("situation") or place_info.get("blurb", "清晨的人群正在散去，彼此仍只是萍水相逢。"),
        "present_characters": present_characters,
        "player_stage": "stranger",
        "cover_identity": _COVER_IDENTITY.get(cons, {"name": anon_name, "backstory": "不主动披露私人背景。"}),
        "taboo_list": _TABOO_LIST.get(cons, []),
        "dialogue_flow": chapter_info.get("dialogue_flow", []),
        "chapter": ch,
        "target_cons": cons,
    }

    return {
        "chat_params": chat_params,
        "first_met": first_met,
        "scene_config": scene_config
    }


def _handle_advance(req_data, db_path, ledger_path, config):
    from world_sim import handle as ws_handle

    contracts_dir = os.path.abspath(os.path.join(_HERE, "..", "contracts"))

    ws_req = {
        "run_no": int(req_data.get("run_no", 1)),
        "from_ch": int(req_data.get("from_ch")),
        "to_ch": int(req_data.get("to_ch")),
        "active_delta": req_data.get("active_delta") or []
    }

    res = ws_handle(ws_req, db_path, contracts_dir, ledger_path, config)
    return res


def handle(req_data, db_path=None, ledger_path=None, config=None):
    op = req_data.get("op", "look")

    if op == "look":
        return _handle_look(req_data, db_path, ledger_path, config)
    elif op == "go":
        return _handle_go(req_data, db_path, ledger_path, config)
    elif op == "meet":
        return _handle_meet(req_data, db_path, ledger_path, config)
    elif op == "advance":
        return _handle_advance(req_data, db_path, ledger_path, config)
    else:
        return {"error": f"未知的操作: {op}"}


if __name__ == "__main__":
    print("=== opening_hub v0.5 快速自检 ===")
    test_ledger = os.path.join(_HERE, "delta_ledger.json")

    # 模拟 look
    res_look = handle({"op": "look", "ch": 8, "run_no": 1}, None, test_ledger, {})
    print("Look result Ch8:", json.dumps(res_look, ensure_ascii=False, indent=2))

    # 模拟 go
    res_go = handle({"op": "go", "ch": 8, "place": "天安门升旗广场", "run_no": 1}, None, test_ledger, {})
    print("Go result Ch8:", json.dumps(res_go, ensure_ascii=False, indent=2))

    # 模拟 meet
    res_meet = handle({"op": "meet", "cons": "C.kakashi.WMAIN", "ch": 8, "place": "天安门升旗广场", "run_no": 1}, None, test_ledger, {})
    print("Meet result Ch8 (First met?):", res_meet.get("first_met"), "params:", res_meet.get("chat_params"))

    print("=== 自检完成 ===")
