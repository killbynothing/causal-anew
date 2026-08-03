"""Run-local ambient people: bodies first, persistent identity after reciprocity."""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Mapping

from runtime.intent_runtime import IntentResolution, retarget_resolution


AMBIENT_TARGET_PREFIX = "$ambient:"


def is_ambient_target(value: str) -> bool:
    return str(value or "").startswith(AMBIENT_TARGET_PREFIX)


def profile_for_target(card: Mapping[str, Any], target: str) -> dict[str, Any] | None:
    if not is_ambient_target(target):
        return None
    profile_id = str(target)[len(AMBIENT_TARGET_PREFIX):].strip()
    for raw in card.get("ambient_actor_profiles", ()):
        if isinstance(raw, Mapping) and str(raw.get("profile_id", "")).strip() == profile_id:
            return dict(raw)
    return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_") or "person"


def materialize(
    profile: Mapping[str, Any], *, session_id: str, turn: int, registry: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Create a provisional body. It is not a persistent identity yet."""
    profile_id = _slug(str(profile.get("profile_id", "ambient")))
    seed = hashlib.sha256(f"{session_id}|{profile_id}".encode("utf-8")).hexdigest()[:12]
    actor_id = f"ambient:{profile_id}:{seed}"
    existing = registry.get(actor_id)
    if isinstance(existing, Mapping):
        return actor_id, copy.deepcopy(existing["persona"]), dict(existing)
    cons = f"C.ambient.{profile_id}.{seed}"
    role = str(profile.get("public_role", "路人")).strip() or "路人"
    persona = {
        "name": role,
        "constraints": list(profile.get("constraints", ()) or ["只处理自己此刻能看见和听见的事。"]),
        "inner_state": {
            "want_now": str(profile.get("want_now", "完成眼前的工作或行程。")),
            "knot": str(profile.get("knot", "不把陌生人的事自动当成自己的事。")),
            "unsaid": "",
            "stance_to_player": "陌生、可回应，也可以拒绝或离开。",
        },
        "boundaries": copy.deepcopy(profile.get("boundaries") or {
            "hard": [], "soft": ["私人行程"], "style": "按手头事务和安全感直接回答。",
        }),
        "voice_samples": list(profile.get("voice_samples", ()) or []),
        "run_local": True,
        "ambient_profile_id": profile_id,
    }
    record = {
        "actor_id": actor_id,
        "actor_cons": cons,
        "profile_id": profile_id,
        "public_role": role,
        "status": "provisional",
        "created_turn": int(turn),
        "persona": copy.deepcopy(persona),
        "episodes": [],
    }
    return actor_id, persona, record


def establish_after_reciprocity(
    registry: Mapping[str, Any], *, actor_cons: str, decision: Mapping[str, Any], turn: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Only an observed reply turns a body into a stable run-local person."""
    result = {str(key): copy.deepcopy(value) for key, value in registry.items()}
    for actor_id, raw in result.items():
        if not isinstance(raw, dict) or raw.get("actor_cons") != actor_cons:
            continue
        if raw.get("status") == "established":
            return result, None
        raw["status"] = "established"
        event = {
            "event": "reciprocity_established", "actor_id": actor_id,
            "actor_cons": actor_cons, "turn": int(turn),
            "outcome": str(decision.get("outcome", "")),
            "visible_response": str(decision.get("visible_response", "")),
        }
        raw.setdefault("episodes", []).append(event)
        return result, event
    return result, None


def hydrate_resolution(
    card: dict[str, Any], resolution: IntentResolution, *, session_id: str, turn: int,
    registry: Mapping[str, Any],
) -> tuple[IntentResolution, dict[str, Any], dict[str, Any] | None]:
    """Place one environmental role into the live card only after selection."""
    profile = profile_for_target(card, resolution.feasibility.intent.target)
    if profile is None:
        return resolution, dict(registry), None
    actor_id, persona, record = materialize(profile, session_id=session_id, turn=turn, registry=registry)
    updated = {str(key): copy.deepcopy(value) for key, value in registry.items()}
    updated.setdefault(actor_id, record)
    cons = str(updated[actor_id]["actor_cons"])
    if cons not in card.setdefault("present", []):
        card["present"].append(cons)
    card.setdefault("persona_cards", {})[cons] = copy.deepcopy(persona)
    card.setdefault("ambient_stage", {}).setdefault("可接触的人", str(profile.get("public_role", "路人")))
    return retarget_resolution(resolution, cons), updated, record
