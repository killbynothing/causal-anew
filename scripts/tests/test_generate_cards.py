# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from scripts import generate_cards


def test_draft_card_schema_and_rejection(tmp_path: Path) -> None:
    draft = generate_cards.generate_draft(
        scene_id="OPENING_CAFE_001",
        ch_anchor=9,
        characters=["kakashi", "akito", "xiuzai"],
        events=["E002-01", "E002-02"],
        db_path=str(ROOT / "data" / "world_truth.db"),
    )
    output_file = tmp_path / "test_cafe_draft.json"
    output_file.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    assert draft["status"] == "draft_needs_human"
    assert draft["scene_id"] == "OPENING_CAFE_001"
    assert draft["ch_anchor"] == 9
    assert isinstance(draft["must_happen"], list)
    assert len(draft["must_happen"]) == 2
    assert len(draft["locks"]) > 0
    assert any("无戏外概念" in x for x in draft["locks"])

    try:
        proto.load_card(output_file)
        raise AssertionError("Engine loaded a draft card without raising ValueError!")
    except ValueError as exc:
        assert "Cannot load draft card" in str(exc)


def test_knowledge_gate_no_future_knowledge() -> None:
    draft = generate_cards.generate_draft(
        scene_id="OPENING_CAFE_001",
        ch_anchor=9,
        characters=["kakashi", "akito", "xiuzai"],
        events=["E002-01"],
        db_path=str(ROOT / "data" / "world_truth.db"),
    )
    gate = draft["memory_layers"]["knowledge_gate"]
    gate_str = json.dumps(gate, ensure_ascii=False)
    assert any("【此刻知道" in line for line in gate)
    for future_term in ["世界政府", "RTW", "LT", "时空机器", "狙击手"]:
        assert future_term not in gate_str
    assert "spoiler_gate" in gate_str


def test_opening_overlay_preserves_authored_mh() -> None:
    for scene_id, path in generate_cards.OPENING_AUTHORED.items():
        authored = json.loads(path.read_text(encoding="utf-8"))
        overlaid = generate_cards.compile_opening_overlay(scene_id)
        assert overlaid["compiler"]["mode"] == "authored_overlay"
        assert overlaid["scene_id"] == scene_id
        authored_ids = [
            str(item.get("id"))
            for item in (authored.get("must_happen") or [])
            if isinstance(item, dict)
        ]
        overlay_ids = [
            str(item.get("id"))
            for item in (overlaid.get("must_happen") or [])
            if isinstance(item, dict)
        ]
        assert overlay_ids == authored_ids
        assert overlaid.get("status") != "draft_needs_human"
        # Playable after overlay stamp.
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "card.json"
            # Strip compiler-only projected helper before write? Keep full overlay.
            playable = dict(overlaid)
            playable.pop("memory_layers", None)
            playable["memory_layers"] = {
                k: v
                for k, v in (overlaid.get("memory_layers") or {}).items()
                if k != "knowledge_gate_projected"
            }
            out.write_text(json.dumps(playable, ensure_ascii=False), encoding="utf-8")
            loaded = proto.load_card(out)
            assert loaded["scene_id"] == scene_id


def test_session_stamps_opening_compiler_and_fronting() -> None:
    session = proto.FreeStageSession(
        card_path=ROOT / "runtime" / "free_stage_card_ryuya_prologue.json",
        config={"api_key": "", "api_url": "", "model": "mock"},
        caller=proto.fixed_selftest_actor,
        autosave=False,
    )
    assert session.card.get("_fronting_runtime") is True
    assert (session.card.get("compiler") or {}).get("mode") == "authored_overlay"
    assert "C.ryuya.W1" in (session.card.get("present") or [])
    receipts = session.card.get("_fronting_select") or []
    assert receipts
    assert receipts[0].get("selected") == "C.ryuya.W1"
    asm = session._assembly_projection_status()
    assert asm["top_tier"] is True
    assert asm["deferred_not_top_tier"] == []
    wired = " ".join(asm.get("wired_now") or [])
    assert "fronting_canon runtime select" in wired
    assert "Storylet generate_cards overlay" in wired
    assert "β soft→director threshold" in wired


def _run_directly() -> None:
    with tempfile.TemporaryDirectory() as td:
        test_draft_card_schema_and_rejection(Path(td))
    test_knowledge_gate_no_future_knowledge()
    test_opening_overlay_preserves_authored_mh()
    test_session_stamps_opening_compiler_and_fronting()
    print("ALL Compiler Tests Passed Successfully!")


if __name__ == "__main__":
    _run_directly()
