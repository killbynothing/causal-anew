#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
name_book.py -- NPC 名册单一来源（审计重构 R6）。

此前同一套「真名/化名/短名/介绍前指代」映射在 4+ 处各自维护并已漂移：
  - runtime/free_stage_prototype.py  CONS_ALIASES / redact_pre_intro / hard_check /
    sanitize_visible_names / find_npc_canon_events(short_names ×2) / 桥接 npc_names
  - runtime/scene_runtime.py         bid_turn_taking 内联 aliases / anonymize_text
  - c1_web_console/scene_api.py      _REAL_NAMES / _CONS_ALIASES
改一处漏三处 = 直接的真名泄露风险面。自本文件起：**改名只改这里**。

字段说明：
  slug            记忆/桥接层使用的英文短键（structured_memories 的 key）
  full / short    场上公开全名（化名）与短名
  pre_intro       自我介绍前的指代（free_stage redact 出口所用）
  anon_pre_intro  scene_runtime.anonymize_text 出口所用指代。
  romaji          正典事件文本匹配用罗马字姓氏
  offstage_names  戏外真名（原著/原作名），任何玩家可见面禁止出现
  offstage_surface 出口硬替换表：戏外真名 → 场上安全写法
  extra_aliases   其它可指认该角色的称呼（参与识别，不参与输出）
"""
from __future__ import annotations

NAME_BOOK: dict[str, dict] = {
    "C.kakashi.WMAIN": {
        "slug": "kakashi",
        "full": "坂本晴明",
        "short": "晴明",
        "pre_intro": "银发青年",
        "anon_pre_intro": "银发青年",
        "romaji": "Sakamoto",
        "offstage_names": ["卡卡西", "旗木"],
        "offstage_surface": {"卡卡西": "坂本晴明", "旗木": "坂本"},
        "extra_aliases": [],
    },
    "C.xiuzai.WMAIN": {
        "slug": "xiuzai",
        "full": "折原修哉",
        "short": "修哉",
        "pre_intro": "黑发青年",
        "anon_pre_intro": "黑发青年",
        "romaji": "Orihara",
        "offstage_names": [],
        "offstage_surface": {},
        "extra_aliases": ["懒散青年"],
    },
    "C.akito.WMAIN": {
        "slug": "akito",
        "full": "川口秋人",
        "short": "秋人",
        "pre_intro": "圆脸青年",
        "anon_pre_intro": "圆脸青年",
        "romaji": "Kawaguchi",
        "offstage_names": [],
        "offstage_surface": {},
        "extra_aliases": [],
    },
    "C.maki.WMAIN": {
        "slug": "maki",
        "full": "折原真纪",
        "short": "真纪",
        "pre_intro": None,
        "anon_pre_intro": None,
        "romaji": None,
        "offstage_names": [],
        "offstage_surface": {},
        "extra_aliases": [],
    },
    "C.ryuya.WMAIN": {
        "slug": "ryuya", "full": "折原龙也", "short": "龙也",
        "pre_intro": "浅发青年", "anon_pre_intro": "浅发青年", "romaji": "Orihara",
        "offstage_names": [], "offstage_surface": {}, "extra_aliases": [],
    },
    "C.ryuya.W1": {
        "slug": "ryuya_w1", "full": "折原龙也", "short": "龙也",
        "pre_intro": "浅发青年", "anon_pre_intro": "浅发青年", "romaji": "Orihara",
        "offstage_names": [], "offstage_surface": {}, "extra_aliases": [],
    },
    "C.banbo.WMAIN": {
        "slug": "banbo", "full": "敖斑驳", "short": "斑驳",
        "pre_intro": "染异色头发的女生", "anon_pre_intro": "染异色头发的女生", "romaji": None,
        "offstage_names": [], "offstage_surface": {}, "extra_aliases": ["斑爷"],
    },
    "C.yuxuan.WMAIN": {
        "slug": "yuxuan", "full": "潘雨璇", "short": "雨璇",
        "pre_intro": "扎着马尾的女生", "anon_pre_intro": "扎着马尾的女生", "romaji": None,
        "offstage_names": [], "offstage_surface": {}, "extra_aliases": ["璇儿", "璇璇"],
    },
    "C.pan_father.WMAIN": {
        "slug": "pan_father", "full": "潘父", "short": None,
        "pre_intro": "中年男人", "anon_pre_intro": "中年男人", "romaji": None,
        "offstage_names": [], "offstage_surface": {}, "extra_aliases": [],
    },
    "C.pan_mother.WMAIN": {
        "slug": "pan_mother", "full": "潘母", "short": None,
        "pre_intro": "中年女人", "anon_pre_intro": "中年女人", "romaji": None,
        "offstage_names": [], "offstage_surface": {}, "extra_aliases": [],
    },
    "C.liuxu.WMAIN": {
        "slug": "liuxu",
        "full": "柳絮",
        "short": None,
        "pre_intro": "年轻女子",
        "anon_pre_intro": "年轻女子",
        "romaji": None,
        "offstage_names": [],
        "offstage_surface": {},
        "extra_aliases": [],
    },
    "C.weichu.WMAIN": {
        "slug": "weichu",
        "full": "魏初",
        "short": None,
        "pre_intro": "穿西装的女性",
        "anon_pre_intro": "穿西装的女性",
        "romaji": None,
        "offstage_names": [],
        "offstage_surface": {},
        "extra_aliases": [],
    },
    "C.zhangchen.WMAIN": {
        "slug": "zhangchen",
        "full": "张尘",
        "short": None,
        "pre_intro": "年轻男人",
        "anon_pre_intro": "年轻男人",
        "romaji": None,
        "offstage_names": [],
        "offstage_surface": {},
        "extra_aliases": [],
    },
}

# 开场三人组（当前 A 线主引擎的在场 NPC）
MAIN_TRIO: tuple[str, ...] = ("C.kakashi.WMAIN", "C.xiuzai.WMAIN", "C.akito.WMAIN")
# 正典事件匹配所覆盖的角色（三人组 + 真纪）
CANON_CAST: tuple[str, ...] = MAIN_TRIO + ("C.maki.WMAIN",)
# 控制台 API 层建档角色（三人组 + 柳絮）
API_CAST: tuple[str, ...] = MAIN_TRIO + ("C.liuxu.WMAIN",)

# 玩家可使用的公共地点别称。与角色名册同属“可见称谓→场内真值”的
# 归一化层；只用于理解玩家意图，不改写正典库中的地点文本。
PUBLIC_LOCATION_ALIASES: dict[str, str] = {
    "耀华中学": "十六中",
}


def entry(cons_id: str) -> dict:
    return NAME_BOOK.get(cons_id, {})


def normalize_public_location_aliases(text: str) -> str:
    """Normalize player-facing place aliases before route intent matching."""
    normalized = str(text or "")
    for alias, canonical in PUBLIC_LOCATION_ALIASES.items():
        normalized = normalized.replace(alias, canonical)
    return normalized


def full_name(cons_id: str) -> str | None:
    return entry(cons_id).get("full")


def short_name(cons_id: str) -> str | None:
    return entry(cons_id).get("short")


def pre_intro_name(cons_id: str) -> str | None:
    return entry(cons_id).get("pre_intro")


def real_names(cons_id: str) -> list[str]:
    """场上公开全名 + 短名（存在者），用于介绍前泄露检查与遮蔽。"""
    e = entry(cons_id)
    return [n for n in (e.get("full"), e.get("short")) if n]


def offstage_names(cons_id: str) -> list[str]:
    return list(entry(cons_id).get("offstage_names", []))


def all_aliases(cons_id: str) -> list[str]:
    """可指认该角色的全部称呼（含介绍前指代与戏外真名），用于点名识别。"""
    e = entry(cons_id)
    names = real_names(cons_id)
    if e.get("pre_intro"):
        names.append(e["pre_intro"])
    names.extend(e.get("extra_aliases", []))
    names.extend(e.get("offstage_names", []))
    return names


def canon_match_keys(cons_id: str) -> list[str]:
    """正典事件文本匹配键：slug / 短名 / 全名 / 罗马字（存在者）。"""
    e = entry(cons_id)
    return [n for n in (e.get("slug"), e.get("short"), e.get("full"), e.get("romaji")) if n]


def offstage_surface_map() -> dict[str, str]:
    """全体角色戏外真名 → 场上安全写法的出口替换总表。"""
    merged: dict[str, str] = {}
    for e in NAME_BOOK.values():
        merged.update(e.get("offstage_surface", {}))
    return merged


def slug_to_full(cast: tuple[str, ...] = MAIN_TRIO) -> dict[str, str]:
    return {NAME_BOOK[c]["slug"]: NAME_BOOK[c]["full"] for c in cast}


def slug_to_short(cast: tuple[str, ...] = MAIN_TRIO) -> dict[str, str]:
    return {NAME_BOOK[c]["slug"]: NAME_BOOK[c]["short"] for c in cast}


def anon_replacements(introduced: dict[str, bool]) -> list[tuple[str, str]]:
    """anonymize_text 的替换对：未介绍角色的 全名/短名/戏外真名 → anon_pre_intro。"""
    reps: list[tuple[str, str]] = []
    for cons in MAIN_TRIO:
        if introduced.get(cons, False):
            continue
        dst = NAME_BOOK[cons].get("anon_pre_intro")
        if not dst:
            continue
        for src in real_names(cons) + offstage_names(cons):
            reps.append((src, dst))
    return reps
