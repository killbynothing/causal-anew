#!/usr/bin/env python3
from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime import scene_policies
from runtime import turn_engine


def _snapshot(*, scene_id: str = "OPENING_TIANANMEN_002"):
    history = [
        {
            "role": "npc",
            "text": "（日）いっしょに行きますか。",
            "lang": "ja",
            "player_visible": True,
        }
    ]
    return scene_policies.ScenePolicyInput.from_runtime(
        scene_id=scene_id,
        player_input={"speech": "可以，我听得懂日语。", "action": ""},
        recent_history=history,
    )


def test_policy_contract_is_frozen_and_value_only():
    snapshot = _snapshot()
    assert isinstance(snapshot.recent_history, tuple)
    assert all(isinstance(item, scene_policies.PublicTurn) for item in snapshot.recent_history)

    try:
        snapshot.scene_id = "OTHER"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("ScenePolicyInput must be frozen")

    output_fields = tuple(item.name for item in fields(scene_policies.ScenePolicyOutput))
    assert output_fields == ("evidence", "opportunities", "proposals")
    out = scene_policies.evaluate(snapshot)
    assert isinstance(out.evidence, tuple)
    assert isinstance(out.opportunities, tuple)
    assert isinstance(out.proposals, tuple)


def test_policy_snapshot_detaches_from_mutable_runtime_input():
    history = [
        {
            "role": "npc",
            "text": "（日）いっしょに行きますか。",
            "lang": "ja",
            "player_visible": True,
        }
    ]
    player_input = {"speech": "可以。", "action": ""}
    snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="OPENING_TIANANMEN_002",
        player_input=player_input,
        recent_history=history,
    )

    history[0]["text"] = "MUTATED"
    player_input["speech"] = "MUTATED"

    assert snapshot.recent_history[0].text != "MUTATED"
    assert snapshot.player_speech != "MUTATED"


def test_scene_policy_module_cannot_write_runtime_authority():
    source = inspect.getsource(scene_policies)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            assert not module.startswith("runtime"), module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("runtime"), alias.name

    for forbidden in (
        "FreeStageSession",
        "_beat_complete(",
        "_beat_complete_many(",
        "_branch_add(",
        "_branch_remove(",
        "_commit_world_transaction(",
        "_mark_ended(",
        "_maybe_transition(",
        ".save(",
        ".patch_player(",
        ".increment_elapsed(",
        "ActorMindState",
        "PhysicalState",
        "RuntimeStore",
        "FactProjection",
        "WorldCommit",
    ):
        assert forbidden not in source, forbidden


def test_tiananmen_policy_is_deterministic_and_scene_scoped():
    snapshot = _snapshot()
    first = scene_policies.evaluate(snapshot)
    second = scene_policies.evaluate(snapshot)
    assert first == second
    assert "tiananmen_japanese_understood" in first.evidence

    other = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="OTHER_SCENE",
        player_input={"speech": "可以，我听得懂日语。", "action": ""},
        recent_history=[],
    )
    assert scene_policies.evaluate(other) == scene_policies.ScenePolicyOutput()


def test_private_or_director_only_history_does_not_become_policy_evidence():
    snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="OPENING_TIANANMEN_002",
        player_input={"speech": "可以。", "action": ""},
        recent_history=[
            {
                "role": "npc",
                "text": "（日）いっしょに行きますか。",
                "lang": "ja",
                "player_visible": False,
                "audience": "director_only",
            }
        ],
    )
    assert "tiananmen_japanese_understood" not in scene_policies.evaluate(snapshot).evidence


def test_tiananmen_session_adapter_only_delegates_classification():
    source = inspect.getsource(proto.tiananmen_player_facts)
    assert "ScenePolicyInput.from_runtime(" in source
    assert "evaluate_tiananmen(snapshot).evidence" in source

    for forbidden in (
        "tiananmen_video_unavailable",
        "tiananmen_video_offered",
        "tiananmen_japanese_understood",
        "tiananmen_aquarium_accepted",
        "tiananmen_aquarium_declined",
        "tiananmen_independent_aquarium_destination",
    ):
        assert forbidden not in source, forbidden

    sample = {
        "speech": "没有视频，不过我听得懂日语，不跟你们去海洋馆了。",
        "action": "",
    }
    history = [
        {
            "role": "npc",
            "text": "（日）海洋館に行きますか。",
            "lang": "ja",
            "player_visible": True,
        }
    ]
    snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="OPENING_TIANANMEN_002",
        player_input=sample,
        recent_history=history,
    )
    assert proto.tiananmen_player_facts(sample, recent_history=history) == set(
        scene_policies.evaluate_tiananmen(snapshot).evidence
    )


def test_future_turn_engine_core_has_no_concrete_scene_policy_or_scene_ids():
    path = ROOT / "runtime" / "turn_engine.py"
    if not path.exists():
        return

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            assert module not in {"runtime.scene_policies", "scene_policies"}, module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in {"runtime.scene_policies", "scene_policies"}, alias.name

    for forbidden in (
        "OPENING_TIANANMEN_002",
        "16ZHONG",
        "C.ryuya",
        "RP3",
        "RP4",
        "TM2",
        "TM3",
    ):
        assert forbidden not in source, forbidden



def test_c16_classifiers_are_policy_owned_without_behavior_drift():
    gate_cases = [
        (
            {"speech": "可以，一起去。", "action": ""},
            "accepted",
            "undecided",
            "undecided",
        ),
        (
            {"speech": "", "action": "我带她们走另一条街。"},
            "undecided",
            "girls_redirected",
            "undecided",
        ),
        (
            {"speech": "", "action": "我跟上张尘。"},
            "undecided",
            "undecided",
            "follow_zhangchen",
        ),
        (
            {"speech": "", "action": "我进奶茶店，在取餐口旁观。"},
            "undecided",
            "undecided",
            "inside_observer",
        ),
    ]
    for raw, cafe, diversion, shop in gate_cases:
        snapshot = scene_policies.ScenePolicyInput.from_runtime(
            scene_id="CARD_16ZHONG_GATE",
            player_input=raw,
        )
        assert scene_policies.c16_milktea_disposition(snapshot) == cafe
        assert scene_policies.c16_counter_encounter_diversion(snapshot) == diversion
        assert scene_policies.c16_shop_follow_disposition(snapshot) == shop
        assert proto.c16_milktea_disposition(raw) == cafe
        assert proto.c16_counter_encounter_diversion(raw) == diversion
        assert proto.c16_shop_follow_disposition(raw) == shop
        assert proto.c16_gate_disposition(raw) == scene_policies.c16_gate_disposition(snapshot)

    table_cases = [
        ({"speech": "", "action": "我留在取餐口。"}, "stay_counter"),
        ({"speech": "", "action": "我跟上楼，在旁桌旁观。"}, "table_observer"),
        ({"speech": "", "action": "我跟上楼，加入他们一起坐。"}, "join_request"),
    ]
    for raw, expected in table_cases:
        snapshot = scene_policies.ScenePolicyInput.from_runtime(
            scene_id="CARD_MILKTEA_WATCH",
            player_input=raw,
        )
        assert scene_policies.c16_table_follow_disposition(snapshot) == expected
        assert proto.c16_table_follow_disposition(raw) == expected


def test_c16_visibility_evidence_is_policy_owned():
    quiet = {"speech": "", "action": "我站在旁边看着。"}
    overt = {"speech": "", "action": "我上前拦住他。"}
    thought_only = {"speech": "", "action": "", "thought": "我想过去看看"}

    quiet_snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="CARD_16ZHONG_GATE",
        player_input=quiet,
    )
    overt_snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="CARD_16ZHONG_GATE",
        player_input=overt,
    )
    thought_snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="CARD_16ZHONG_GATE",
        player_input=thought_only,
    )

    assert scene_policies.c16_subtle_peripheral_watch(quiet_snapshot)
    assert proto._c16_subtle_peripheral_watch(quiet)
    assert not scene_policies.c16_subtle_peripheral_watch(overt_snapshot)
    assert scene_policies.c16_overt_intervention(overt_snapshot)
    assert proto._c16_overt_intervention(overt)
    assert not scene_policies.c16_overt_intervention(thought_snapshot)


def test_c16_scene_policy_returns_proposals_without_committing_them():
    snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="CARD_16ZHONG_GATE",
        player_input={"speech": "", "action": "我跟上张尘。"},
    )
    first = scene_policies.evaluate_c16(snapshot)
    second = scene_policies.evaluate_c16(snapshot)
    assert first == second
    assert first.evidence == ()
    assert "c16_shop_follow_disposition:follow_zhangchen" in first.proposals

    other = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="UNRELATED_SCENE",
        player_input={"speech": "", "action": "我跟上张尘。"},
    )
    assert scene_policies.evaluate_c16(other) == scene_policies.ScenePolicyOutput()


def test_c16_session_classifiers_are_thin_policy_adapters():
    for name in (
        "c16_milktea_disposition",
        "c16_counter_encounter_diversion",
        "c16_shop_follow_disposition",
        "c16_gate_disposition",
        "c16_table_follow_disposition",
        "_c16_subtle_peripheral_watch",
        "_c16_overt_intervention",
    ):
        source = inspect.getsource(getattr(proto, name))
        assert "scene_policies.ScenePolicyInput.from_runtime(" in source, name
        assert "scene_policies.c16_" in source, name
        for forbidden in (
            "_branch_add(",
            "_beat_complete(",
            "_canon_update(",
            "_maybe_transition(",
            ".save(",
        ):
            assert forbidden not in source, (name, forbidden)


def test_session_step_consumes_one_policy_output_instead_of_reclassifying_c16():
    source = inspect.getsource(proto.FreeStageSession.step)
    assert "scene_policies.evaluate(scene_policy_snapshot)" in source
    assert source.count("scene_policies.evaluate(scene_policy_snapshot)") == 1
    assert "scene_policies.proposal_value(" in source
    assert '"c16_overt_intervention" in scene_policy_output.evidence' in source

    for forbidden in (
        "c16_counter_encounter_diversion(parsed_input)",
        "c16_milktea_disposition(parsed_input)",
        "c16_gate_disposition(parsed_input)",
        "c16_shop_follow_disposition(parsed_input)",
        "c16_table_follow_disposition(parsed_input)",
        "_c16_overt_intervention(parsed_input)",
        "tiananmen_player_facts(player_input",
    ):
        assert forbidden not in source, forbidden


def test_policy_output_preserves_wait_vs_undecided_for_c16_position_gates():
    gate_wait = scene_policies.evaluate(
        scene_policies.ScenePolicyInput.from_runtime(
            scene_id="CARD_16ZHONG_GATE",
            player_input={"speech": "", "action": ""},
        )
    )
    assert scene_policies.proposal_value(
        gate_wait,
        "c16_shop_follow_disposition",
    ) == "wait"

    table_wait = scene_policies.evaluate(
        scene_policies.ScenePolicyInput.from_runtime(
            scene_id="CARD_MILKTEA_WATCH",
            player_input={"speech": "", "action": ""},
        )
    )
    assert scene_policies.proposal_value(
        table_wait,
        "c16_table_follow_disposition",
    ) == "wait"


def test_canon_selector_is_pure_ordered_and_detached_from_runtime_mappings():
    raw_segments = [
        {
            "segment_id": "SEG_A",
            "trigger": "after_stop",
            "after_stop": "STOP_A",
            "requires_branch": ["watch"],
            "requires_autonomous_decisions": ["DECIDE_A"],
            "requires_autonomous_outcomes": {"DECIDE_A": "accept"},
            "auto_continue": False,
        },
        {
            "segment_id": "SEG_B",
            "trigger": "after_stop",
            "after_stop": "STOP_A",
            "requires_branch": ["watch"],
            "auto_continue": True,
        },
    ]
    decisions = [{"autonomous_decision_id": "DECIDE_A", "outcome": "accept"}]
    snapshot = scene_policies.CanonSelectionInput.from_runtime(
        pending_stop="STOP_A",
        completed_segments=(),
        branch_progress=("watch",),
        actor_decisions=decisions,
        segments=raw_segments,
    )

    raw_segments[0]["segment_id"] = "MUTATED"
    raw_segments[0]["requires_branch"].append("MUTATED")
    decisions[0]["outcome"] = "refuse"

    selected = scene_policies.select_pending_canon_segment(snapshot)
    assert selected == scene_policies.CanonSegmentSelection(
        segment_id="SEG_A",
        auto_continue=False,
    )


def test_canon_selector_preserves_first_eligible_and_auto_continue_semantics():
    segments = (
        {
            "segment_id": "BLOCKER",
            "trigger": "after_stop",
            "after_stop": "STOP_A",
            "auto_continue": False,
        },
        {
            "segment_id": "LATER_AUTO",
            "trigger": "after_stop",
            "after_stop": "STOP_A",
            "auto_continue": True,
        },
    )
    snapshot = scene_policies.CanonSelectionInput.from_runtime(
        pending_stop="STOP_A",
        completed_segments=(),
        branch_progress=(),
        actor_decisions=(),
        segments=segments,
    )
    selected = scene_policies.select_pending_canon_segment(snapshot)
    assert selected is not None
    assert selected.segment_id == "BLOCKER"
    assert selected.auto_continue is False

    after_first = scene_policies.CanonSelectionInput.from_runtime(
        pending_stop="STOP_A",
        completed_segments=("BLOCKER",),
        branch_progress=(),
        actor_decisions=(),
        segments=segments,
    )
    next_selected = scene_policies.select_pending_canon_segment(after_first)
    assert next_selected is not None
    assert next_selected.segment_id == "LATER_AUTO"
    assert next_selected.auto_continue is True


def test_canon_session_selector_delegates_without_reimplementing_policy():
    source = inspect.getsource(proto.FreeStageSession._pending_canon_selection)
    assert "scene_policies.CanonSelectionInput.from_runtime(" in source
    assert "scene_policies.select_pending_canon_segment(snapshot)" in source
    for forbidden in (
        'segment.get("trigger"',
        'segment.get("after_stop"',
        'segment.get("requires_branch"',
        'segment.get("requires_autonomous_decisions"',
        'segment.get("requires_autonomous_outcomes"',
    ):
        assert forbidden not in source, forbidden

    burst = inspect.getsource(proto.FreeStageSession._emit_canon_burst)
    assert "self._pending_canon_selection()" in burst
    assert 'next_segment.get("auto_continue")' not in burst


def test_flashback_policy_only_classifies_handoff_readiness():
    assert scene_policies.flashback_handoff_ready(
        scene_policies.FlashbackHandoffInput(
            prologue_active=True,
            has_return_frame=True,
            all_must_happen_complete=True,
        )
    )
    assert not scene_policies.flashback_handoff_ready(
        scene_policies.FlashbackHandoffInput(
            prologue_active=True,
            has_return_frame=False,
            all_must_happen_complete=True,
        )
    )

    policy_source = inspect.getsource(scene_policies.flashback_handoff_ready)
    policy_tree = ast.parse(policy_source)
    forbidden_names = {
        "WorldCommit",
        "_finalize_prologue_pendant",
        "_branch_from_world_transaction",
        "_world_transaction",
        "commit_world_fact",
        "commit_world_batch",
    }
    for node in ast.walk(policy_tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names, node.id
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names, node.attr

    transition_source = inspect.getsource(proto.FreeStageSession._maybe_transition)
    assert "scene_policies.flashback_handoff_ready(" in transition_source
    assert 'self._finalize_prologue_pendant("deferred"' in transition_source
    assert '"ryuya_pendant_disposition"' in transition_source


def _turn_ports(factory):
    return turn_engine.TurnPorts(
        input=factory("input"),
        observe=factory("observe"),
        deliberate=factory("deliberate"),
        floor=factory("floor"),
        enact=factory("enact"),
        resolve=factory("resolve"),
        commit=factory("commit"),
        exit=factory("exit"),
        project=factory("project"),
    )


def test_turn_engine_executes_exact_stage_order():
    seen = []

    def factory(stage):
        def port(frame):
            seen.append((stage, frame.stages))
            return turn_engine.TurnStageReceipt.continue_(stage)
        return port

    frame = turn_engine.TurnEngine(_turn_ports(factory)).run_turn(request_id="turn:test:1")
    assert frame.stages == turn_engine.TURN_STAGE_ORDER
    assert [stage for stage, _prior in seen] == list(turn_engine.TURN_STAGE_ORDER)
    for index, (_stage, prior) in enumerate(seen):
        assert prior == turn_engine.TURN_STAGE_ORDER[:index]


def test_turn_engine_short_circuit_can_only_jump_to_project():
    seen = []

    def factory(stage):
        def port(frame):
            seen.append(stage)
            if stage == "observe":
                return turn_engine.TurnStageReceipt.project(
                    stage,
                    note="thought_only",
                    artifact_keys=("observation_receipt",),
                )
            return turn_engine.TurnStageReceipt.continue_(stage)
        return port

    frame = turn_engine.TurnEngine(_turn_ports(factory)).run_turn(request_id="turn:test:2")
    assert frame.stages == ("input", "observe", "project")
    assert seen == ["input", "observe", "project"]
    assert frame.short_circuited
    assert frame.short_circuit_reason == "thought_only"


def test_turn_engine_rejects_stage_mismatch():
    def factory(stage):
        def port(frame):
            wrong = "observe" if stage == "input" else stage
            return turn_engine.TurnStageReceipt.continue_(wrong)
        return port

    try:
        turn_engine.TurnEngine(_turn_ports(factory)).run_turn(request_id="turn:test:3")
    except ValueError as exc:
        assert "stage mismatch" in str(exc)
    else:
        raise AssertionError("TurnEngine accepted a mismatched stage receipt")


def test_turn_engine_core_is_orchestration_only():
    source = inspect.getsource(turn_engine)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            assert module not in {
                "runtime.scene_policies",
                "runtime.free_stage_prototype",
                "runtime.world_commit",
                "runtime.player_action",
                "runtime.exit_policy",
            }, module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in {
                    "runtime.scene_policies",
                    "runtime.free_stage_prototype",
                    "runtime.world_commit",
                    "runtime.player_action",
                    "runtime.exit_policy",
                }, alias.name

    for forbidden in (
        "_branch_add(",
        "_beat_complete(",
        "_canon_update(",
        "_maybe_transition(",
        "commit_world_",
        "commit_player_action(",
        "decide_exit(",
        ".save(",
    ):
        assert forbidden not in source, forbidden


def test_ryuya_cafe_topic_interface_is_policy_owned():
    history = [
        {"role": "player", "text": "最近还好吗？"},
        {"role": "npc", "text": "还行。"},
        {"role": "player", "text": "时间不早了。"},
    ]
    raw = {"speech": "你是不是有话想说？", "action": ""}
    snapshot = scene_policies.ScenePolicyInput.from_runtime(
        scene_id="RYUYA_CAFE_POLICY",
        player_input=raw,
        recent_history=history,
    )
    assert scene_policies.ryuya_topic_interface(snapshot)
    assert proto.ryuya_deep_topic_interface(raw, history)

    adapter = inspect.getsource(proto.ryuya_deep_topic_interface)
    assert "scene_policies.ryuya_topic_interface(snapshot)" in adapter
    assert "_RYUYA_TOPIC_INTERFACE_MARKERS" not in inspect.getsource(proto)


def test_ryuya_cafe_phase_policy_preserves_original_ladder_order():
    cases = [
        (0, (), False, "opening"),
        (1, (), False, "banter"),
        (1, (), True, "deepen"),
        (2, (), False, "deepen"),
        (0, ("RP2",), False, "entrust_clear"),
        (0, ("RP2", "RP3"), False, "post_entrust_gift"),
        (0, ("RP2", "RP3", "RP4"), False, "farewell"),
    ]
    for beats, completed, topic_interface, expected in cases:
        output = scene_policies.evaluate_ryuya_cafe_state(
            scene_policies.RyuyaCafeStateInput.from_runtime(
                flash_beats=beats,
                completed=completed,
                topic_interface=topic_interface,
            )
        )
        assert scene_policies.proposal_value(
            output,
            "ryuya_cafe_phase",
        ) == expected


def test_ryuya_cafe_policy_does_not_mutate_card_or_own_authority():
    completed = ["RP2"]
    snapshot = scene_policies.RyuyaCafeStateInput.from_runtime(
        flash_beats=3,
        completed=completed,
        topic_interface=True,
    )
    completed.append("RP4")
    output = scene_policies.evaluate_ryuya_cafe_state(snapshot)
    assert scene_policies.proposal_value(
        output,
        "ryuya_cafe_phase",
    ) == "entrust_clear"

    source = inspect.getsource(scene_policies.evaluate_ryuya_cafe_state)
    tree = ast.parse(source)
    forbidden = {
        "_branch_add",
        "_beat_complete",
        "_commit_world_transaction",
        "_finalize_prologue_pendant",
        "commit_world_fact",
        "commit_world_batch",
        "save",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden, node.id
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, node.attr


def test_ryuya_cafe_session_keeps_wording_and_mutation_outside_policy():
    source = inspect.getsource(proto.advance_ryuya_prologue_want_now)
    assert "scene_policies.evaluate_ryuya_cafe_state(" in source
    assert '"ryuya_cafe_phase"' in source
    assert 'inner["want_now"] = want' in source
    assert 'working["goals"] = [goal_head, *rest][:4]' in source

    policy_source = inspect.getsource(scene_policies.evaluate_ryuya_cafe_state)
    assert "want_now" not in policy_source
    assert "goal_head" not in policy_source


def test_session_step_delegates_input_and_observe_prefix():
    source = inspect.getsource(proto.FreeStageSession.step)
    assert "self._run_turn_input_stage(player_input)" in source
    assert "self._run_turn_observe_stage(player_input, input_stage)" in source
    assert source.index("_run_turn_input_stage") < source.index("_run_turn_observe_stage")

    for forbidden in (
        "parse_player_input_modalities(",
        "ingest_player_thought(",
        "self._barge_in_stream(",
        "self.inputs.append(player_input)",
    ):
        assert forbidden not in source, forbidden


def test_input_stage_owns_normalization_not_story_decisions():
    source = inspect.getsource(proto.FreeStageSession._run_turn_input_stage)
    for required in (
        "self.physical_state.increment_elapsed(",
        "parse_player_input_modalities(",
        "self._record_player_violation(",
        "self.player_prophecies.append(",
    ):
        assert required in source, required

    for forbidden in (
        "scene_policies.",
        "build_speaker_plan(",
        "_branch_add(",
        "_beat_complete(",
        "_commit_world_transaction(",
        "_maybe_transition(",
        "call_actor",
        "arbitrate_floor",
    ):
        assert forbidden not in source, forbidden


def test_observe_stage_owns_player_observation_and_thought_only_short_circuit():
    source = inspect.getsource(proto.FreeStageSession._run_turn_observe_stage)
    for required in (
        "ingest_player_thought(",
        "self._observation_replace(",
        "self._barge_in_stream(",
        "self.inputs.append(player_input)",
        '"thought_recorded": True',
        '"thought_deltas": thought_deltas',
    ):
        assert required in source, required

    for forbidden in (
        "scene_policies.",
        "build_speaker_plan(",
        "_branch_add(",
        "_beat_complete(",
        "_commit_world_transaction(",
        "_maybe_transition(",
        "call_actor",
        "arbitrate_floor",
    ):
        assert forbidden not in source, forbidden


def test_input_observe_stage_results_are_frozen_value_boundaries():
    for cls in (proto._TurnInputStageResult, proto._TurnObserveStageResult):
        params = getattr(cls, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


def test_session_step_exposes_deliberate_then_floor_order():
    source = inspect.getsource(proto.FreeStageSession.step)
    assert "build_participation_deliberation(" in source
    assert "build_floor_plan(participation_deliberation)" in source
    assert source.index("build_participation_deliberation(") < source.index(
        "build_floor_plan(participation_deliberation)"
    )
    assert "speaker_plan = build_speaker_plan(" not in source


def test_deliberate_and_floor_adapters_keep_p4_single_arbiter_boundary():
    deliberate = inspect.getsource(proto.build_participation_deliberation)
    floor = inspect.getsource(proto.build_floor_plan)
    facade = inspect.getsource(proto.build_speaker_plan)

    assert "participation_runtime.deliberate_participation(" in deliberate
    assert "participation_runtime.arbitrate_floor(" not in deliberate

    assert floor.count("participation_runtime.arbitrate_floor(") == 1
    assert "participation_runtime.deliberate_participation(" not in floor
    for forbidden in (
        "player_input",
        "history",
        "must_happen",
        "director_instruction",
        "scene_working_memory",
    ):
        assert forbidden not in floor, forbidden

    assert "build_participation_deliberation(" in facade
    assert "build_floor_plan(" in facade


def test_participation_deliberation_snapshot_is_frozen():
    params = getattr(proto._ParticipationDeliberation, "__dataclass_params__", None)
    assert params is not None
    assert params.frozen is True


def test_session_step_delegates_actor_transport_to_enact_stage():
    source = inspect.getsource(proto.FreeStageSession.step)
    assert "self._run_turn_enact_stage(" in source
    for forbidden in (
        "run_director_and_isolated_actors(",
        "call_actor(prompt",
    ):
        assert forbidden not in source, forbidden


def test_enact_stage_calls_transport_without_authority_commits():
    source = inspect.getsource(proto.FreeStageSession._run_turn_enact_stage)
    assert "run_director_and_isolated_actors(" in source
    assert "call_actor(" in source

    for forbidden in (
        "_branch_add(",
        "_branch_remove(",
        "_beat_complete(",
        "_beat_complete_many(",
        "_commit_world_transaction(",
        "_append_actor_decisions(",
        "_record_scene_receipt(",
        "_observe(",
        "_maybe_transition(",
        "_mark_ended(",
        ".save(",
    ):
        assert forbidden not in source, forbidden

if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
