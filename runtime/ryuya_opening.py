# -*- coding: utf-8 -*-
"""龙也开场梗概 × 延后托付闪回（文案口径：悬念节奏改造·中薄梗概）。

开场：中薄梗概（挂坠 + 龙也天津朋友 + 两个名字没记牢）→ 直进所选入口。
正戏：修哉或张尘名字落地且在场 → 切入两年前可演段（主职：让玩家认识龙也；托付自然落在临别）→ 演完回原场。

梗概不讲泼袖/两年/谁是谁；闪回现场才演清。
"""
from __future__ import annotations

from typing import Any

RYUYA_FLASHBACK_TRIGGERS = frozenset({"C.xiuzai.WMAIN", "C.zhangchen.WMAIN"})

RYUYA_OPENING_SYNOPSIS_PARAS = (
    "你有一枚旧挂坠。古铜色，不重。",
    (
        "给你的人叫龙也——天津那边一个偶尔碰上的朋友。"
        "认识得挺荒唐，但你暂时不想细想。"
    ),
    "他还提过两个名字。你没记牢。",
)

OPENING_LAST_PARA_BY_OPENING_ID = {
    "aline_tiananmen": (
        "日子照旧。三月里的一个周末，你忽然想去一趟北京。"
        "刚好临时看到有票，便坐高铁过来；路上才后知后觉地想，升旗是不是还得提前约。"
        "不过既然来了，就先去看看。实在进不去，在地铁口附近站着看一眼也行。"
    ),
}

# 识别句只勾住记忆入口，不剧透托付全文（托付在闪回里由龙也当面说清）。
RYUYA_FLASHBACK_BRIDGE = (
    "修哉。这个名字落下来的瞬间，你心里像被什么极轻地碰了一下。"
    "雨声、咖啡机、靠窗那张磨白边漆的桌子——忽然全都清晰起来。"
)

RYUYA_FLASHBACK_BRIDGE_ZHANGCHEN = (
    "张尘。这个名字落下来的瞬间，你心里像被什么极轻地碰了一下。"
    "雨声、咖啡机、靠窗那张磨白边漆的桌子——忽然全都清晰起来。"
)


def build_opening_synopsis_turns(
    last_para: str | None = None, *, opening_id: str = ""
) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    paras = list(RYUYA_OPENING_SYNOPSIS_PARAS)
    # 天安门等入口：在中薄三句之后追加专属尾巴，不替换中薄正文。
    extra_tail = ""
    if last_para is not None:
        extra_tail = last_para
    elif opening_id in OPENING_LAST_PARA_BY_OPENING_ID:
        extra_tail = OPENING_LAST_PARA_BY_OPENING_ID[opening_id]
    for para in paras:
        turns.append(
            {
                "role": "narrate",
                "speaker": "旁白",
                "text": para,
                "stage": "",
                "turn": 0,
                "audience": "player",
                "player_visible": True,
                "provenance": {"authored": "ryuya_opening_synopsis"},
            }
        )
    if extra_tail:
        turns.append(
            {
                "role": "narrate",
                "speaker": "旁白",
                "text": extra_tail,
                "stage": "",
                "turn": 0,
                "audience": "player",
                "player_visible": True,
                "provenance": {"authored": "ryuya_opening_synopsis", "opening_tail": opening_id or "custom"},
            }
        )
    return turns


def flashback_bridge_text(hits: set[str]) -> str:
    if "C.zhangchen.WMAIN" in hits and "C.xiuzai.WMAIN" not in hits:
        return RYUYA_FLASHBACK_BRIDGE_ZHANGCHEN
    return RYUYA_FLASHBACK_BRIDGE


def flashback_trigger_hits(
    *,
    introduced_cons: set[str],
    present_cons: set[str],
    flashback_done: bool,
    prologue_active: bool,
) -> set[str]:
    """在场且名字已绑定到人时触发（自报或第三人介绍均可）；梗概里听见名字不够。"""
    if flashback_done or prologue_active:
        return set()
    return (introduced_cons & RYUYA_FLASHBACK_TRIGGERS) & present_cons


# 层 C：挂坠第一次被玩家用到时的短闪回（感官锚，不重演整场序幕）。
PENDANT_LAYER_C_PARAS = (
    "指尖碰到那枚挂坠的瞬间，雨声先回来了——天津街角，靠窗那张边漆磨白的旧桌。",
    "有人把咖啡溅到袖口，又笑着让你坐下赔一杯。临别时，那枚古铜色挂坠被放进你手里。",
)


def build_pendant_layer_c_turns(*, turn_no: int = 0) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for para in PENDANT_LAYER_C_PARAS:
        turns.append(
            {
                "role": "narrate",
                "speaker": "旁白",
                "text": para,
                "stage": "",
                "turn": int(turn_no),
                "audience": "player",
                "player_visible": True,
                "provenance": {"authored": "pendant_layer_c"},
            }
        )
    return turns
