# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import opening_top_tier as ott


def test_prologue_selects_w1():
    cons = ott.select_fronting_cons(
        "B.ryuya.WMAIN",
        scene_id="OPENING_RYUYA_PROLOGUE_001",
        prefer_cons="C.ryuya.W1",
    )
    assert cons == "C.ryuya.W1"


def test_org_hint_selects_wmain():
    cons = ott.select_fronting_cons(
        "B.ryuya.WMAIN",
        hint="组织行动 冷酷",
        prefer_cons="C.ryuya.WMAIN",
    )
    assert cons == "C.ryuya.WMAIN"


def test_apply_fronting_stamps_prologue_card():
    import json

    card = json.loads(
        (ROOT / "runtime" / "free_stage_card_ryuya_prologue.json").read_text(encoding="utf-8")
    )
    out = ott.apply_fronting_to_card(card)
    assert out["_fronting_runtime"] is True
    assert out["present"] == ["C.ryuya.W1"]
    assert out["_fronting_select"][0]["selected"] == "C.ryuya.W1"
    assert out["_fronting_select"][0]["matched_pin"] is True


if __name__ == "__main__":
    test_prologue_selects_w1()
    test_org_hint_selects_wmain()
    test_apply_fronting_stamps_prologue_card()
    print("PASS fronting")
