#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.exit_policy import ExitRequest, decide_exit


def card(*, exits=None, must=None, auto_end=False):
    raw = {
        "scene_id": "S1",
        "must_happen": must if must is not None else [{"id": "M1"}],
        "exits": exits or [],
    }
    if auto_end:
        raw["auto_end_on_complete"] = True
    return raw


def req(c, **kw):
    base = dict(
        card=c,
        completed=tuple(kw.pop("completed", ())),
        player_input=kw.pop("player_input", {"speech": "", "action": "", "thought": ""}),
        stall=kw.pop("stall", 0),
        active_exit_state=kw.pop("active_exit_state", "converged"),
        branch_progress=frozenset(kw.pop("branch_progress", ())),
        actor_decisions=tuple(kw.pop("actor_decisions", ())),
    )
    base.update(kw)
    return ExitRequest(**base)


def test_future_reunion_phrase_is_not_current_exit_intent():
    social = card(exits=[{"target_pending_entry": True}])
    completed = ("M1",)

    for line in (
        "想再见见你总要有个借口吧",
        "我希望以后还能再见到你",
        "下次再见到你再说",
    ):
        assert not __import__("runtime.transition_service", fromlist=["x"]).has_global_exit_intent(line)
        decision = decide_exit(
            req(
                social,
                completed=completed,
                player_input={"speech": line, "action": "", "thought": ""},
                pending_entry_target_ref="runtime/approved.json",
            )
        )
        assert decision.action == "continue", (line, decision.to_dict())

    for line in ("再见，我先走了", "那我先走了，回头见", "告辞"):
        assert __import__("runtime.transition_service", fromlist=["x"]).has_global_exit_intent(line)


def test_mh_complete_without_exit_contract_does_not_end():
    decision = decide_exit(req(card(exits=[]), completed=("M1",)))
    assert decision.action == "continue"
    assert decision.reason == "no_exit_signal"


def test_explicit_auto_end_is_opt_in_only():
    c = card(exits=[], auto_end=True)
    no_flag = decide_exit(req(c, completed=("M1",)))
    assert no_flag.action == "continue"

    flagged = decide_exit(req(c, completed=("M1",), explicit_auto_end=True))
    assert flagged.action == "end_run"
    assert flagged.reason == "explicit_auto_end"


def test_semantic_receipt_is_prospective_until_authorized():
    spec = {
        "target_card": "runtime/target.json",
        "semantic_receipt": "route.accepted",
        "requires_branch_progress": ["route.accepted"],
    }
    decision = decide_exit(
        req(
            card(exits=[spec]),
            completed=("M1",),
            semantic_exit_spec=spec,
            branch_progress=(),
        )
    )
    assert decision.action == "transition"
    assert decision.target_ref == "runtime/target.json"
    assert decision.prospective_branch_facts == ("route.accepted",)


def test_unmet_requirement_blocks_transition():
    spec = {
        "target_card": "runtime/target.json",
        "requires_branch_progress": ["missing.fact"],
    }
    decision = decide_exit(
        req(
            card(exits=[spec]),
            completed=("M1",),
            selected_exit_spec=spec,
        )
    )
    assert decision.action == "continue"
    assert decision.reason == "exit_requirements_unmet"


def test_forced_exit_freezes_original_target_across_confirmation():
    left = {
        "target_card": "runtime/left.json",
        "intent_tokens": ["走左边"],
        "allow_forced_exit_before_must": True,
    }
    right = {
        "target_card": "runtime/right.json",
        "intent_tokens": ["走右边"],
        "allow_forced_exit_before_must": True,
    }
    first = decide_exit(
        req(
            card(exits=[left, right], must=[{"id": "M1"}]),
            completed=(),
            player_input={"speech": "我走左边", "action": "", "thought": ""},
        )
    )
    assert first.action == "await_confirmation"
    assert first.exit_spec["target_card"] == "runtime/left.json"

    confirmed = decide_exit(
        req(
            card(exits=[left, right], must=[{"id": "M1"}]),
            completed=(),
            player_input={"speech": "随便", "action": "", "thought": ""},
            pending_confirmation=True,
            confirmed_exit_spec=first.exit_spec,
        )
    )
    assert confirmed.action == "transition"
    assert confirmed.mode == "forced"
    assert confirmed.target_ref == "runtime/left.json"


def test_confirmation_cannot_bypass_target_requirements():
    spec = {
        "target_card": "runtime/locked.json",
        "requires_branch_progress": ["gate.open"],
    }
    decision = decide_exit(
        req(
            card(exits=[spec]),
            pending_confirmation=True,
            confirmed_exit_spec=spec,
        )
    )
    assert decision.action == "continue"
    assert decision.reason == "exit_requirements_unmet"


def test_confirmation_cancel_clears_pending_exit():
    spec = {"target_card": "runtime/target.json"}
    decision = decide_exit(
        req(
            card(exits=[spec]),
            pending_confirmation=True,
            confirmed_exit_spec=spec,
            confirmation_cancelled=True,
        )
    )
    assert decision.action == "continue"
    assert decision.reason == "confirmation_cancelled"
    assert decision.confirmation_action == "clear"


def test_menu_never_silently_chooses_first_exit():
    exits = [
        {"target_card": "runtime/a.json"},
        {"target_card": "runtime/b.json"},
    ]
    decision = decide_exit(
        req(
            card(exits=exits),
            completed=("M1",),
            player_input={"speech": "我走了", "action": "", "thought": ""},
            exit_menu=True,
        )
    )
    assert decision.action == "show_menu"
    assert decision.target_ref is None

    # Same rule while MH is incomplete: the generic intent is not allowed to
    # freeze exits[0] as the confirmation target.
    forced = decide_exit(
        req(
            card(
                exits=[
                    {**exits[0], "allow_forced_exit_before_must": True},
                    {**exits[1], "allow_forced_exit_before_must": True},
                ]
            ),
            completed=(),
            player_input={"speech": "我走了", "action": "", "thought": ""},
            exit_menu=True,
        )
    )
    assert forced.action == "show_menu"
    assert forced.mode == "forced"
    assert forced.exit_spec is None


def test_flashback_return_carries_concrete_target():
    spec = {"target_card": "runtime/wrong.json"}
    decision = decide_exit(
        req(
            card(exits=[spec]),
            completed=("M1",),
            flashback_target_ref="runtime/original_scene.json",
        )
    )
    assert decision.action == "transition"
    assert decision.target_kind == "flashback_return"
    assert decision.target_ref == "runtime/original_scene.json"


def test_standalone_social_exit_ends_only_after_real_exit_signal():
    c = card(exits=[{"target_pending_entry": True}])
    stay = decide_exit(
        req(
            c,
            completed=("M1",),
            player_input={"speech": "再聊会儿", "action": "", "thought": ""},
            standalone_end=True,
        )
    )
    assert stay.action == "continue"

    leave = decide_exit(
        req(
            c,
            completed=("M1",),
            player_input={"speech": "我先走了，回头见", "action": "", "thought": ""},
            standalone_end=True,
        )
    )
    assert leave.action == "end_run"


def test_pending_entry_target_must_exist_before_transition():
    spec = {"target_pending_entry": True}
    missing = decide_exit(
        req(
            card(exits=[spec]),
            completed=("M1",),
            selected_exit_spec=spec,
            pending_entry_target_ref=None,
        )
    )
    assert missing.action == "continue"
    assert missing.reason == "authorized_exit_missing_target"

    present = decide_exit(
        req(
            card(exits=[spec]),
            completed=("M1",),
            selected_exit_spec=spec,
            pending_entry_target_ref="runtime/approved.json",
        )
    )
    assert present.action == "transition"
    assert present.target_kind == "pending_entry"
    assert present.target_ref == "runtime/approved.json"


if __name__ == "__main__":
    test_future_reunion_phrase_is_not_current_exit_intent()
    test_mh_complete_without_exit_contract_does_not_end()
    test_explicit_auto_end_is_opt_in_only()
    test_semantic_receipt_is_prospective_until_authorized()
    test_unmet_requirement_blocks_transition()
    test_forced_exit_freezes_original_target_across_confirmation()
    test_confirmation_cannot_bypass_target_requirements()
    test_confirmation_cancel_clears_pending_exit()
    test_menu_never_silently_chooses_first_exit()
    test_flashback_return_carries_concrete_target()
    test_standalone_social_exit_ends_only_after_real_exit_signal()
    test_pending_entry_target_must_exist_before_transition()
    print("PASS test_exit_policy")
