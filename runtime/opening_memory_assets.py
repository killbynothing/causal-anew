"""Opening-memory asset selection, independent from the session orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPENING_MEMORY_BY_OPENING: dict[str, Path] = {
    "aline_tiananmen": ROOT / "runtime" / "opening_memory.json",
    "cline_16zhong": ROOT / "runtime" / "opening_memory_c16.json",
    "wline_weichu": ROOT / "runtime" / "opening_memory_weichu.json",
}
ALINE_INTRO_NPCS = frozenset({"C.akito.WMAIN", "C.xiuzai.WMAIN", "C.kakashi.WMAIN"})
C16_INTRO_NPCS = frozenset({"C.zhangchen.WMAIN", "C.banbo.WMAIN", "C.yuxuan.WMAIN"})
WEICHU_INTRO_NPCS = frozenset({"C.weichu.WMAIN", "C.zhangchen.WMAIN"})


def load_opening_memory_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def resolve_opening_memory_source(
    opening_id: str, card: dict[str, Any], *, is_c16_family: bool = False,
    is_weichu_family: bool = False,
) -> dict[str, Any]:
    """Select only an approved opening asset; unknown cards receive no asset."""
    if opening_id in OPENING_MEMORY_BY_OPENING:
        return load_opening_memory_file(OPENING_MEMORY_BY_OPENING[opening_id])
    present = set(card.get("present") or [])
    if present.intersection(ALINE_INTRO_NPCS):
        return load_opening_memory_file(OPENING_MEMORY_BY_OPENING["aline_tiananmen"])
    if present.intersection(C16_INTRO_NPCS) or is_c16_family:
        return load_opening_memory_file(OPENING_MEMORY_BY_OPENING["cline_16zhong"])
    if present.intersection(WEICHU_INTRO_NPCS) or is_weichu_family:
        return load_opening_memory_file(OPENING_MEMORY_BY_OPENING["wline_weichu"])
    return {}
