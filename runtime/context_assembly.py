"""N6 explicit, auditable actor-context assembly."""
from __future__ import annotations

import copy
import json
from typing import Any, Mapping


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def assemble_actor_context(prompt_packet: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep actor-visible data unchanged while exposing its four context layers."""
    packet = copy.deepcopy(dict(prompt_packet))
    memory = packet.get("self_memory") if isinstance(packet.get("self_memory"), Mapping) else {}
    layers = {
        "stable_identity": {"actor_cons": packet.get("actor_cons"), "self_core": packet.get("self_core", {}), "disclosure_policy": packet.get("disclosure_policy", {})},
        "authoritative_present": {"scene": packet.get("scene"), "world_cursor": packet.get("world_cursor", {}), "physical_scene": packet.get("physical_scene", {}), "world_signals": packet.get("world_signals", [])},
        "scene_window": {"observable_player": packet.get("observable_player", {}), "observable_dialogue": packet.get("observable_dialogue", []), "private_perceptions": packet.get("private_perceptions", [])},
        "goal_conditioned_memory": {"scene_working_memory": memory.get("scene_working_memory", {}), "episodic_recent": memory.get("episodic_recent", []), "slow_memory_top_k": memory.get("slow_memory_top_k", []), "relevant_knowledge_top_k": packet.get("relevant_knowledge_top_k", []), "identity_relations": packet.get("identity_relations", [])},
    }
    goal_memory = layers["goal_conditioned_memory"]
    return packet, {
        "schema_version": "free_stage.context_assembly.v1",
        "enforcement": "observe_only",
        "layers": {name: {"chars": _size(value)} for name, value in layers.items()},
        "memory": {"slow_memory_activated": len(goal_memory["slow_memory_top_k"] or []), "knowledge_activated": len(goal_memory["relevant_knowledge_top_k"] or []), "episodes_activated": len(goal_memory["episodic_recent"] or [])},
    }
