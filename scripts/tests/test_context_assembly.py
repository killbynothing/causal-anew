#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import context_assembly
from runtime import free_stage_prototype as proto

RYUYA_CARD = ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


def _hash(value) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _card() -> dict:
    return json.loads(RYUYA_CARD.read_text(encoding="utf-8"))


def _packet(*, run_no: int = 1) -> dict:
    card = _card()
    return proto.build_actor_context_packet(
        card,
        "C.ryuya.W1",
        history=[],
        player_input={"speech": "今天雨还是很大。", "action": "", "thought": "PRIVATE_THOUGHT"},
        turn_no=1,
        world_cursor={
            "worldline": "WMAIN",
            "run": run_no,
            "ch_anchor": int(card.get("ch_anchor", 0) or 0),
        },
        runtime_inner_state={"want_now": "先接住闲聊"},
        player_profile={"name": "玩家"},
    )


def test_production_builder_is_thin_and_context_assembler_owns_retrieval():
    builder = inspect.getsource(proto.build_actor_context_packet)
    assert "context_assembly.build_actor_context_draft(" in builder
    for forbidden in (
        "fetch_relevant_knowledge(",
        "fetch_slow_memory(",
        "activate_memory_candidates(",
        "kge_slice(",
        "project_world_events(",
    ):
        assert forbidden not in builder, forbidden

    owned = inspect.getsource(context_assembly.build_actor_context_draft)
    for required in (
        "fetch_relevant_knowledge(",
        "fetch_slow_memory(",
        "activate_memory_candidates(",
        "project_world_events(",
    ):
        assert required in owned, required

    projection = inspect.getsource(proto.actor_packet_for_prompt)
    assert "context_assembly.actor_prompt_projection(" in projection
    initial_debug = inspect.getsource(proto.FreeStageSession.initial_debug_payload)
    assert "acv2.fetch_slow_memory(" not in initial_debug
    assert 'get("slow_memory_top_k")' in initial_debug
    transport = inspect.getsource(proto.call_actor_packet)
    assert "context_assembly.finalize_actor_context(packet)" in transport
    assert "assemble_actor_context(actor_packet_for_prompt(packet))" not in transport


def test_real_caller_packet_matches_authoritative_assembly_receipt():
    packet = _packet()
    packet["conversation_contract"] = {
        "response_slot": "primary",
        "participation_mode": "speak",
        "actor_may_pass": True,
    }
    packet["cog_loop"] = {"decide": {"top_concern": "接住当下话题"}}
    packet["_debug_private"] = {"secret": "ROOT_PRIVATE_DEBUG"}
    captured: list[dict] = []

    def caller(**kwargs):
        request = json.loads(kwargs["user_content"])
        captured.append(request)
        return json.dumps(
            {
                "pre_speech": {
                    "notice": "听见对方提到雨",
                    "intention": "先自然接一句",
                    "social_move": "continuer",
                },
                "turns": [],
                "mh_progress": [],
                "director_note": "",
            },
            ensure_ascii=False,
        )

    result = proto.call_actor_packet(packet, config={}, caller=caller)
    assert len(captured) == 1
    sent = captured[0]["actor_context_packet"]
    receipt = result["context_receipt"]["context_assembly"]
    assert receipt["schema_version"] == "free_stage.context_assembly.v2"
    assert receipt["enforcement"] == "authoritative"
    assert receipt["prompt_sha256"] == _hash(sent)
    assert receipt["actor_cons"] == sent["actor_cons"] == "C.ryuya.W1"

    sent_blob = json.dumps(sent, ensure_ascii=False)
    assert "PRIVATE_THOUGHT" not in sent_blob
    assert "memory_activation" not in sent
    assert "knowledge_candidates" not in sent
    assert "slow_memory_candidates" not in (sent.get("self_memory") or {})
    assert "scene_episode_withheld" not in sent_blob
    assert "ROOT_PRIVATE_DEBUG" not in sent_blob
    assert "_debug_private" not in sent
    assert receipt["layers"]["scene_overlay"]["sha256"] == _hash(
        {
            "conversation_contract": sent.get("conversation_contract", {}),
            "decision_request": sent.get("decision_request", {}),
            "cog_loop": sent.get("cog_loop", {}),
            "director_instruction": sent.get("director_instruction", {}),
        }
    )


def test_fixed_selftest_receives_playtest_only_out_of_band():
    packet = _packet()
    packet["conversation_contract"] = {
        "response_slot": "primary",
        "participation_mode": "speak",
    }
    packet["_playtest"] = {
        "completed": ["RP1"],
        "branch_progress": [],
        "must_happen_ids": ["RP1", "RP2", "RP3", "RP4"],
    }
    captured: list[dict] = []

    def wrapper(**kwargs):
        request = json.loads(kwargs["user_content"])
        captured.append(request)
        assert isinstance(kwargs.get("_playtest"), dict)
        return proto.fixed_selftest_actor(**kwargs)

    proto.call_actor_packet(packet, config={}, caller=wrapper)
    assert captured
    sent = captured[0]["actor_context_packet"]
    assert "_playtest" not in sent
    assert "RP2" not in json.dumps(sent, ensure_ascii=False)


def test_observer_candidates_and_withheld_never_change_actor_prompt():
    base = {
        "actor_cons": "C.fixture.W1",
        "scene": "S1",
        "turn": 1,
        "self_core": {"name": "fixture"},
        "self_memory": {
            "slow_memory_top_k": [{"mem_id": "safe", "text": "SAFE"}],
            "slow_memory_candidates": [{"mem_id": "debug-a", "text": "SECRET_A"}],
        },
        "relevant_knowledge_top_k": [{"prop_id": "p1", "statement": "SAFE_K"}],
        "memory_activation": {
            "scene_episode_withheld": [{"first_person_episode": "SECRET_WITHHELD_A"}],
            "knowledge_candidates": [{"statement": "SECRET_CANDIDATE_A"}],
        },
        "knowledge_candidates": [{"statement": "SECRET_TOP_A"}],
    }
    changed = copy.deepcopy(base)
    changed["self_memory"]["slow_memory_candidates"] = [
        {"mem_id": "debug-b", "text": "SECRET_B"}
    ]
    changed["memory_activation"] = {
        "scene_episode_withheld": [{"first_person_episode": "SECRET_WITHHELD_B"}],
        "knowledge_candidates": [{"statement": "SECRET_CANDIDATE_B"}],
    }
    changed["knowledge_candidates"] = [{"statement": "SECRET_TOP_B"}]

    prompt_a, receipt_a = context_assembly.finalize_actor_context(base)
    prompt_b, receipt_b = context_assembly.finalize_actor_context(changed)
    assert prompt_a == prompt_b
    assert receipt_a["prompt_sha256"] == receipt_b["prompt_sha256"]
    blob = json.dumps(prompt_a, ensure_ascii=False)
    for secret in (
        "SECRET_A",
        "SECRET_B",
        "SECRET_WITHHELD_A",
        "SECRET_WITHHELD_B",
        "SECRET_CANDIDATE_A",
        "SECRET_CANDIDATE_B",
        "SECRET_TOP_A",
        "SECRET_TOP_B",
    ):
        assert secret not in blob


def test_other_consciousness_private_seed_does_not_enter_actor_packet():
    card = _card()
    card.setdefault("persona_cards", {})["C.other.W1"] = {
        "name": "Other",
        "inner_state": {
            "want_now": "OTHER_PRIVATE_GOAL",
            "unsaid": "OTHER_ACTOR_SECRET",
        },
        "privileged_facts": ["OTHER_PRIVILEGED_SECRET"],
    }
    card.setdefault("present", []).append("C.other.W1")
    packet = proto.build_actor_context_packet(
        card,
        "C.ryuya.W1",
        history=[],
        player_input={"speech": "你好", "action": "", "thought": ""},
        turn_no=1,
        world_cursor={"worldline": "WMAIN", "run": 1, "ch_anchor": 0},
    )
    prompt, _ = context_assembly.finalize_actor_context(packet)
    blob = json.dumps(prompt, ensure_ascii=False)
    for secret in (
        "OTHER_PRIVATE_GOAL",
        "OTHER_ACTOR_SECRET",
        "OTHER_PRIVILEGED_SECRET",
    ):
        assert secret not in blob


def test_run_scope_is_forwarded_to_slow_memory_retrieval():
    original = context_assembly.acv2.fetch_slow_memory
    seen: list[int] = []

    def recording_fetch(actor_cons, ch_anchor, *, run_no=1, top_k=64, include_anchor=True):
        seen.append(int(run_no))
        return original(
            actor_cons,
            ch_anchor,
            run_no=run_no,
            top_k=top_k,
            include_anchor=include_anchor,
        )

    context_assembly.acv2.fetch_slow_memory = recording_fetch
    try:
        _packet(run_no=7)
    finally:
        context_assembly.acv2.fetch_slow_memory = original
    assert seen == [7]


def test_cross_run_memory_candidates_do_not_cross_into_prompt():
    original_slow = context_assembly.acv2.fetch_slow_memory
    original_activate = context_assembly.acv2.activate_memory_candidates

    def run_scoped_fetch(actor_cons, ch_anchor, *, run_no=1, top_k=64, include_anchor=True):
        return [
            {
                "mem_id": f"run-{int(run_no)}",
                "text": f"RUN_{int(run_no)}_ONLY",
                "owner_cons": actor_cons,
            }
        ]

    def activate_all(knowledge_candidates, slow_memory_candidates, activation_context, slow_activation_cues=None):
        return {
            "knowledge_activated": list(knowledge_candidates),
            "knowledge_withheld": [],
            "slow_memory_activated": copy.deepcopy(list(slow_memory_candidates)),
            "slow_memory_withheld": [],
        }

    context_assembly.acv2.fetch_slow_memory = run_scoped_fetch
    context_assembly.acv2.activate_memory_candidates = activate_all
    try:
        one, _ = context_assembly.finalize_actor_context(_packet(run_no=1))
        two, _ = context_assembly.finalize_actor_context(_packet(run_no=2))
    finally:
        context_assembly.acv2.fetch_slow_memory = original_slow
        context_assembly.acv2.activate_memory_candidates = original_activate

    blob_one = json.dumps(one, ensure_ascii=False)
    blob_two = json.dumps(two, ensure_ascii=False)
    assert "RUN_1_ONLY" in blob_one
    assert "RUN_2_ONLY" not in blob_one
    assert "RUN_2_ONLY" in blob_two
    assert "RUN_1_ONLY" not in blob_two


def test_debug_observer_flag_does_not_change_actor_request_or_visible_result():
    captures: dict[str, list[dict]] = {"off": [], "on": []}

    def make_caller(bucket):
        def caller(**kwargs):
            raw = kwargs.get("user_content") or ""
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                obj = {}
            if isinstance(obj, dict) and isinstance(obj.get("actor_context_packet"), dict):
                captures[bucket].append(copy.deepcopy(obj["actor_context_packet"]))
            return proto.fixed_selftest_actor(**kwargs)
        return caller

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        off = proto.FreeStageSession(
            session_id="p5-observer-parity",
            card_path=RYUYA_CARD,
            state_dir=root / "off-state",
            runtime_state_path=root / "off-runtime.db",
            load_existing=False,
            autosave=False,
            caller=make_caller("off"),
        )
        on = proto.FreeStageSession(
            session_id="p5-observer-parity",
            card_path=RYUYA_CARD,
            state_dir=root / "on-state",
            runtime_state_path=root / "on-runtime.db",
            load_existing=False,
            autosave=False,
            caller=make_caller("on"),
        )
        out_off = off.step("雨是不是又大了", debug=False)
        out_on = on.step("雨是不是又大了", debug=True)

    assert captures["off"] == captures["on"]
    assert out_off.get("turns") == out_on.get("turns")
    assert out_off.get("completed") == out_on.get("completed")
    assert "debug_payload" not in out_off
    assert isinstance(out_on.get("debug_payload"), dict)


def test_transport_variants_share_same_finalizer_and_prompt_receipt():
    base = _packet()
    variants = {
        "normal": {},
        "opening": {
            "conversation_contract": {
                "response_slot": "primary",
                "participation_mode": "speak",
                "opening_first_line": True,
            }
        },
        "repair": {
            "conversation_contract": {
                "response_slot": "secondary",
                "participation_mode": "speak",
                "social_instruction": "repair_only_visible_continuity",
            }
        },
        "fallback": {
            "physical_scene": {"degradation": "scene_projection_incomplete"},
            "conversation_contract": {
                "response_slot": "primary",
                "participation_mode": "speak",
            },
        },
        "autonomous": {
            "conversation_contract": {
                "response_slot": "primary",
                "participation_mode": "speak",
            },
            "decision_request": {
                "intent_id": "intent:p5:autonomous",
                "valid_outcomes": ["accept", "refuse", "defer"],
                "output_contract": {
                    "actor_cons": "C.ryuya.W1",
                    "intent_id": "intent:p5:autonomous",
                    "outcome": "one valid_outcomes value",
                    "visible_response": "observable speech/action",
                    "reason_sources": "actor-owned packet paths only",
                },
            },
        },
    }

    for name, overlay in variants.items():
        packet = copy.deepcopy(base)
        packet.update(copy.deepcopy(overlay))
        captured: list[dict] = []

        def caller(**kwargs):
            request = json.loads(kwargs["user_content"])
            captured.append(request)
            payload = {
                "pre_speech": {
                    "notice": "fixture",
                    "intention": "fixture",
                    "social_move": "continuer",
                },
                "turns": [],
                "mh_progress": [],
                "director_note": "",
            }
            if name == "autonomous":
                payload["actor_decision"] = {
                    "actor_cons": "C.ryuya.W1",
                    "intent_id": "intent:p5:autonomous",
                    "outcome": "accept",
                    "visible_response": "我答应。",
                    "reason_sources": ["self_state.actor_mind"],
                    "conditions": [],
                    "uncertainty": "",
                    "commitment": "",
                    "revises_decision_id": "",
                    "participation_mode": "speak",
                }
            return json.dumps(payload, ensure_ascii=False)

        result = proto.call_actor_packet(packet, config={}, caller=caller)
        assert len(captured) == 1, name
        sent = captured[0]["actor_context_packet"]
        receipt = result["context_receipt"]["context_assembly"]
        assert receipt["prompt_sha256"] == _hash(sent), name
        assert receipt["enforcement"] == "authoritative", name
        assert "memory_activation" not in sent, name
        assert "knowledge_candidates" not in sent, name


def test_finalize_paths_do_not_requery_after_draft_assembly():
    base = _packet()
    original_knowledge = context_assembly.acv2.fetch_relevant_knowledge
    original_slow = context_assembly.acv2.fetch_slow_memory

    def forbidden(*args, **kwargs):
        raise AssertionError("finalize must not re-query memory or knowledge")

    context_assembly.acv2.fetch_relevant_knowledge = forbidden
    context_assembly.acv2.fetch_slow_memory = forbidden
    try:
        variants = {
            "normal": {},
            "opening": {
                "conversation_contract": {
                    "response_slot": "primary",
                    "opening_first_line": True,
                }
            },
            "repair": {
                "conversation_contract": {
                    "response_slot": "secondary",
                    "social_instruction": "repair_only_visible_continuity",
                }
            },
            "autonomous": {
                "decision_request": {
                    "intent_id": "intent:p5:fixture",
                    "output_contract": {"outcome": "accept|refuse|defer"},
                }
            },
            "fallback": {
                "physical_scene": {"degradation": "scene_projection_incomplete"},
            },
        }
        for name, overlay in variants.items():
            packet = copy.deepcopy(base)
            packet.update(copy.deepcopy(overlay))
            prompt, receipt = context_assembly.finalize_actor_context(packet)
            assert prompt["actor_cons"] == "C.ryuya.W1", name
            assert receipt["schema_version"] == "free_stage.context_assembly.v2", name
            assert receipt["enforcement"] == "authoritative", name
    finally:
        context_assembly.acv2.fetch_relevant_knowledge = original_knowledge
        context_assembly.acv2.fetch_slow_memory = original_slow


if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
