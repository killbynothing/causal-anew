#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto


def _dummy_caller(**kwargs):
    return json.dumps(
        {
            "turns": [],
            "mh_progress": [],
            "director_note": "",
        },
        ensure_ascii=False,
    )


def test_maybe_transition_uses_one_exit_policy_decider():
    source = inspect.getsource(proto.FreeStageSession._maybe_transition)
    assert "exit_policy.decide_exit" in source
    assert "should_trigger_exit(" not in source
    assert "choose_exit_spec(" not in source

    decision_pos = source.index("exit_policy.decide_exit")
    receipt_pos = source.index("self._record_scene_receipt")
    assert receipt_pos > decision_pos
    assert "if exit_decision.authorized:" in source


def test_step_and_one_shot_no_longer_invent_endrun_from_mh_completion():
    step_source = inspect.getsource(proto.FreeStageSession.step)
    run_source = inspect.getsource(proto.run_session)
    class_source = inspect.getsource(proto.FreeStageSession)

    old_generic = (
        'if resolved_card.get("must_happen") '
        'and all_must_happen_complete(resolved_card, self.completed)'
    )
    assert old_generic not in step_source
    assert "session.ended = True" not in run_source
    assert "ExitPolicy is the sole decider" in step_source
    # P1b upgrades the compatibility boolean to a lifecycle projection.
    # ExitPolicy still authorizes; only _set_lifecycle_state may project ended.
    assert "self.ended =" not in inspect.getsource(proto.FreeStageSession._mark_ended)
    lifecycle_source = inspect.getsource(proto.FreeStageSession._set_lifecycle_state)
    assert "self.ended = state == run_lifecycle.CLOSED" in lifecycle_source


def test_forced_exit_target_survives_save_reload():
    left = "runtime/free_stage_card_ryuya_prologue.json"
    right = "runtime/free_stage_card_tiananmen_v2.json"
    source_card = {
        "scene_id": "P1A_CONFIRM_FIXTURE",
        "scene": "确认目标夹具",
        "ch_anchor": 1,
        "must_happen": [{"id": "M1", "desc": "未完成"}],
        "exits": [
            {
                "target_card": left,
                "intent_tokens": ["走左边"],
                "allow_forced_exit_before_must": True,
            },
            {
                "target_card": right,
                "intent_tokens": ["走右边"],
                "allow_forced_exit_before_must": True,
            },
        ],
        "persona_cards": {},
    }

    with tempfile.TemporaryDirectory() as tmp:
        card_path = Path(tmp) / "source.json"
        card_path.write_text(json.dumps(source_card, ensure_ascii=False), encoding="utf-8")
        state_dir = Path(tmp) / "states"
        runtime_state_path = Path(tmp) / "runtime_state.json"
        session = proto.FreeStageSession(
            session_id="p1a-confirm",
            card_path=card_path,
            state_dir=state_dir,
            runtime_state_path=runtime_state_path,
            load_existing=False,
            autosave=False,
            caller=_dummy_caller,
        )
        emitted = []
        transition = session._maybe_transition(
            {"speech": "我走左边", "action": "", "thought": ""},
            turn_no=1,
            emitted=emitted,
        )
        assert transition is None
        assert session.ended is False
        assert session._last_exit_intent_turn == 1
        assert session._last_exit_intent_exit_spec
        assert session._last_exit_intent_exit_spec["target_card"] == left
        session.save()

        resumed = proto.FreeStageSession(
            session_id="p1a-confirm",
            card_path=card_path,
            state_dir=state_dir,
            runtime_state_path=runtime_state_path,
            load_existing=True,
            autosave=False,
            caller=_dummy_caller,
        )
        assert resumed._last_exit_intent_turn == 1
        assert resumed._last_exit_intent_exit_spec
        assert resumed._last_exit_intent_exit_spec["target_card"] == left


def test_brief_multi_exit_skip_refuses_default_first_route():
    with tempfile.TemporaryDirectory() as tmp:
        card_path = Path(tmp) / "brief.json"
        card_path.write_text(
            json.dumps(
                {
                    "scene_id": "P1A_BRIEF_MULTI",
                    "scene": "多出口速览夹具",
                    "ch_anchor": 1,
                    "pacing": "brief",
                    "must_happen": [{"id": "M1"}],
                    "exits": [
                        {"target_card": "runtime/free_stage_card_ryuya_prologue.json"},
                        {"target_card": "runtime/free_stage_card_tiananmen_v2.json"},
                    ],
                    "persona_cards": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        session = proto.FreeStageSession(
            session_id="p1a-brief",
            card_path=card_path,
            state_dir=Path(tmp) / "states",
            load_existing=False,
            autosave=False,
            caller=_dummy_caller,
        )
        try:
            session.skip_scene(caller=_dummy_caller)
        except ValueError as exc:
            assert "unambiguous exit" in str(exc)
        else:
            raise AssertionError("multi-exit skip must not silently choose exits[0]")


def test_no_exit_completed_scene_stays_open_without_explicit_auto_end():
    with tempfile.TemporaryDirectory() as tmp:
        card_path = Path(tmp) / "social.json"
        card_path.write_text(
            json.dumps(
                {
                    "scene_id": "P1A_SOCIAL_NO_EXIT",
                    "scene": "自由社交夹具",
                    "ch_anchor": 1,
                    "must_happen": [{"id": "M1"}],
                    "exits": [],
                    "persona_cards": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        session = proto.FreeStageSession(
            session_id="p1a-social",
            card_path=card_path,
            state_dir=Path(tmp) / "states",
            load_existing=False,
            autosave=False,
            caller=_dummy_caller,
        )
        session._commit_beats(
            ["M1"],
            source_kind="test_fixture",
            turn_no=0,
            event_id="fixture:exit-policy:m1",
        )
        emitted = []
        assert session._maybe_transition(
            {"speech": "再聊一会儿", "action": "", "thought": ""},
            turn_no=1,
            emitted=emitted,
        ) is None
        assert session.ended is False


if __name__ == "__main__":
    test_maybe_transition_uses_one_exit_policy_decider()
    test_step_and_one_shot_no_longer_invent_endrun_from_mh_completion()
    test_forced_exit_target_survives_save_reload()
    test_brief_multi_exit_skip_refuses_default_first_route()
    test_no_exit_completed_scene_stays_open_without_explicit_auto_end()
    print("PASS test_exit_policy_production_wire")
