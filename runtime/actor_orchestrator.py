"""One-way orchestration for a director call plus isolated actor calls.

Actors always run in bidding order and hear earlier same-turn speech before
they speak.  By default the director runs first, then the actor chain
(environment → reaction).  Set ``parallel_llm=True`` only when wall-clock
overlap is explicitly desired; actors never chorus in parallel.
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


DirectorCall = Callable[[str, dict[str, Any], Callable[..., str] | None], dict[str, Any]]
ActorCall = Callable[[dict[str, Any], dict[str, Any], Callable[..., str] | None], dict[str, Any]]
Degradation = Callable[..., dict[str, str]]


def enrich_packet_with_same_turn_prior(
    packet: dict[str, Any],
    prior_turns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Inject already-spoken same-turn lines so the next actor can hear them."""
    out = copy.deepcopy(packet)
    visible = [
        {
            "speaker": str(item.get("speaker") or ""),
            "text": str(item.get("text") or ""),
            "stage": str(item.get("stage") or ""),
            "same_turn": True,
        }
        for item in prior_turns
        if str(item.get("text") or "").strip() or str(item.get("stage") or "").strip()
    ]
    if not visible:
        out.setdefault("same_turn_prior_speech", [])
        return out

    dialogue = list(out.get("observable_dialogue") or [])
    dialogue.extend(visible)
    out["observable_dialogue"] = dialogue
    out["same_turn_prior_speech"] = visible

    contract = dict(out.get("conversation_contract") or {})
    slot = str(contract.get("response_slot") or "")
    covered = "；".join(
        f"{row['speaker']}：{row['text']}"
        for row in visible
        if str(row.get("text") or "").strip()
    )[:280]
    contract["same_turn_hear"] = covered
    if slot == "secondary":
        extra = (
            "本拍前一位同伴已经开口，你听见了。"
            "像真人聊天那样接：短附和、补一句新细节、或自然拐到你自己眼前的事都可以；"
            "不要换皮复述别人刚说完的同一句。"
            "若你这拍没什么要补的，可以只做一个可见反应。"
        )
        prev = str(contract.get("social_instruction") or "").strip()
        contract["social_instruction"] = f"{prev} {extra}".strip() if prev else extra
        contract["max_new_questions"] = 0
    out["conversation_contract"] = contract
    return out


def _run_actors_sequential(
    packets_in_order: list[tuple[str, dict[str, Any]]],
    config: dict[str, Any],
    *,
    actor_call: ActorCall,
    degradation: Degradation,
    caller: Callable[..., str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    turns: list[dict[str, Any]] = []
    actor_decisions: list[dict[str, Any]] = []
    context_receipts: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    errors: list[str] = []
    prior_turns: list[dict[str, Any]] = []

    for cons, packet in packets_in_order:
        try:
            enriched = enrich_packet_with_same_turn_prior(packet, prior_turns)
            # Persist hear-back onto the caller's packet so observer receipts
            # show the true delivery, not the pre-hear skeleton.
            if isinstance(packet, dict):
                packet["same_turn_prior_speech"] = list(enriched.get("same_turn_prior_speech") or [])
                if enriched.get("conversation_contract"):
                    packet["conversation_contract"] = copy.deepcopy(enriched["conversation_contract"])
                if enriched.get("observable_dialogue") is not None:
                    packet["observable_dialogue"] = copy.deepcopy(enriched["observable_dialogue"])
            actor_payload = actor_call(enriched, config, caller)
            actor_turns = [dict(item) for item in (actor_payload.get("turns") or []) if isinstance(item, dict)]
            turns.extend(actor_turns)
            prior_turns.extend(actor_turns)
            if isinstance(packet, dict) and isinstance(actor_payload.get("pre_speech"), dict):
                packet["pre_speech"] = copy.deepcopy(actor_payload["pre_speech"])
            actor_decisions.extend(actor_payload.get("actor_decisions", []) or [])
            degradations.extend(actor_payload.get("degradations", []) or [])
            actor_receipt = actor_payload.get("context_receipt")
            if isinstance(actor_receipt, dict):
                receipt = dict(actor_receipt)
                receipt["same_turn_prior_count"] = len(enriched.get("same_turn_prior_speech") or [])
                receipt["response_slot"] = str(
                    (enriched.get("conversation_contract") or {}).get("response_slot") or ""
                ) or None
                if isinstance(actor_payload.get("pre_speech"), dict):
                    receipt["pre_speech"] = copy.deepcopy(actor_payload["pre_speech"])
                context_receipts.append(receipt)
        except Exception as exc:
            errors.append(f"{cons}:{exc}")
            degradations.append(degradation(
                "actor_packet",
                "sequential_actor_failed",
                "串行演员路失败，该路本拍静默；后续演员仍按已听见内容继续。",
                detail=str(exc)[:180],
            ))
    return turns, actor_decisions, context_receipts, degradations, errors


def dispatch_turn(
    prompt: str,
    packets_in_order: list[tuple[str, dict[str, Any]]],
    config: dict[str, Any],
    *,
    director_call: DirectorCall,
    actor_call: ActorCall,
    degradation: Degradation,
    caller: Callable[..., str] | None = None,
    worker_count: Callable[[int], int] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run director then sequential actors; preserve bidding order and partial successes.

    Default is causal order (director first). ``parallel_llm=True`` only overlaps
    director wall-clock with the actor chain; actors themselves stay sequential.
    """
    degradations: list[dict[str, Any]] = []
    # Default False: environment/accounting before reactions (定稿串行结算).
    overlap_director = bool(config.get("parallel_llm", False)) and caller is None and bool(packets_in_order)

    if not overlap_director:
        director_payload = director_call(prompt, config, caller)
        turns, actor_decisions, context_receipts, actor_degs, errors = _run_actors_sequential(
            packets_in_order, config, actor_call=actor_call, degradation=degradation, caller=caller,
        )
        degradations.extend(actor_degs)
        director_receipt = director_payload.get("context_receipt")
        receipts = ([dict(director_receipt)] if isinstance(director_receipt, dict) else []) + context_receipts
        if errors and not turns and packets_in_order:
            raise RuntimeError("all sequential actor calls failed: " + "; ".join(errors[:3]))
        degradations.append(degradation(
            "actor_llm",
            "sequential_dispatch",
            f"本拍串行：导演先 → 演员{len(packets_in_order)}路（后者听见前者）。",
            detail="overlap_director=false",
        ))
        return {
            "turns": turns,
            "mh_progress": director_payload.get("mh_progress", []),
            "director_note": director_payload.get("director_note", ""),
            "ambient": director_payload.get("ambient", ""),
            "actor_decisions": actor_decisions,
            "context_receipts": receipts,
            "degradations": list(director_payload.get("degradations", []) or []) + degradations,
        }, degradations

    # Director wall-clock overlaps the sequential actor chain; actors never parallelize.
    _ = worker_count  # kept for call-site compatibility; actor fan-out is intentionally 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        director_future = pool.submit(director_call, prompt, config, None)
        actor_future = pool.submit(
            _run_actors_sequential,
            packets_in_order,
            config,
            actor_call=actor_call,
            degradation=degradation,
            caller=None,
        )
        director_payload = director_future.result()
        turns, actor_decisions, context_receipts, actor_degs, errors = actor_future.result()

    degradations.extend(actor_degs)
    director_receipt = director_payload.get("context_receipt")
    receipts = ([dict(director_receipt)] if isinstance(director_receipt, dict) else []) + context_receipts
    if errors and not turns and packets_in_order:
        raise RuntimeError("all sequential actor calls failed: " + "; ".join(errors[:3]))
    degradations.append(degradation(
        "actor_llm",
        "sequential_dispatch",
        f"本拍串行演员（导演并行重叠）：导演1路 + 演员{len(packets_in_order)}路。",
        detail="overlap_director=true",
    ))
    return {
        "turns": turns,
        "mh_progress": director_payload.get("mh_progress", []),
        "director_note": director_payload.get("director_note", ""),
        "ambient": director_payload.get("ambient", ""),
        "actor_decisions": actor_decisions,
        "context_receipts": receipts,
        "degradations": list(director_payload.get("degradations", []) or []) + degradations,
    }, degradations
