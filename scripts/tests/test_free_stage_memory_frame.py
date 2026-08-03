# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto


def test_tiananmen_prompt_assembles_scene_frame_and_three_memory_layers():
    card = proto.load_json(ROOT / "runtime" / "free_stage_card_tiananmen_v2.json")
    prompt = json.loads(proto.build_prompt(card, [], "你们是谁？", [], 0))

    assert prompt["scene_frame"]["where"] == "北京天安门广场升旗区旁"
    assert "为什么在这里" not in prompt["scene_frame"]
    assert set(prompt["memory_layers"]) >= {"context_memory", "relationship_memory", "knowledge_gate"}
    assert "升旗" in json.dumps(prompt["memory_layers"]["context_memory"], ensure_ascii=False)


def test_cafe_memory_acceptance_requires_two_natural_flag_raising_references():
    history = [
        {"role": "npc", "speaker": "秋人", "text": "今早在广场升旗时我们见过你，还跟你借了视频。", "stage": "", "turn": 1},
        {"role": "npc", "speaker": "修哉", "text": "你那段升旗视频稳得多，秋人早上的手抖没救。", "stage": "", "turn": 2},
    ]

    assert proto.memory_frame_issues(history) == []


def test_cafe_memory_acceptance_flags_single_reference():
    history = [
        {"role": "npc", "speaker": "秋人", "text": "今早在广场升旗时我们见过你，还跟你借了视频。", "stage": "", "turn": 1},
        {"role": "npc", "speaker": "修哉", "text": "咖啡快凉了。", "stage": "", "turn": 2},
    ]

    issues = proto.memory_frame_issues(history)
    assert any("flag-raising memory references" in item for item in issues)


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
