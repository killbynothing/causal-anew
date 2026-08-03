"""Pure opening-memory projections that do not own session or entry identity."""
from __future__ import annotations

from typing import Any


def filter_asset_memories(
    memories_raw: dict[str, Any], present_map: dict[str, str], *, ch_anchor: int, scene_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Keep asset entries whose owner, chapter and scene scope are all valid."""
    filtered: dict[str, list[dict[str, Any]]] = {}
    for cons, entries in memories_raw.items():
        if cons not in present_map or not isinstance(entries, list):
            continue
        valid_entries: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ch_min = int(entry.get("ch_min") if entry.get("ch_min") is not None else 0)
            ch_max = int(entry.get("ch_max") if entry.get("ch_max") is not None else 999999)
            if not (ch_min <= ch_anchor <= ch_max):
                continue
            only = entry.get("only_scenes")
            if isinstance(only, list) and scene_id not in only:
                continue
            exclude = entry.get("exclude_scenes")
            if isinstance(exclude, list) and scene_id in exclude:
                continue
            valid_entries.append(entry)
        if valid_entries:
            filtered[cons] = valid_entries
    return filtered


def project_card_native_opening(
    card: dict[str, Any], present_map: dict[str, str], *, include_player_context: bool = True,
) -> dict[str, dict[str, Any]]:
    """Project only card-owned cast constraints; optional player context is explicit."""
    layers = card.get("memory_layers", {}) if isinstance(card.get("memory_layers"), dict) else {}
    persona_cards = card.get("persona_cards", {}) if isinstance(card.get("persona_cards"), dict) else {}
    per_npc_fp = {slug: [] for slug in present_map.values()}
    per_npc_lorebooks = {slug: {"always": [], "keyed": []} for slug in present_map.values()}
    for cons, slug in present_map.items():
        persona = persona_cards.get(cons, {})
        if not isinstance(persona, dict):
            continue
        for raw in persona.get("constraints", [])[:5]:
            text = str(raw).strip()
            if text:
                per_npc_fp[slug].append(f"[上场] {text}")
        inner = persona.get("inner_state", {}) if isinstance(persona.get("inner_state"), dict) else {}
        if str(inner.get("want_now", "")).strip():
            per_npc_fp[slug].append(f"[此刻] {inner['want_now'].strip()}")
        if str(inner.get("stance_to_player", "")).strip():
            per_npc_fp[slug].append(f"[对你] {inner['stance_to_player'].strip()}")
    return {"__opening__": {
        "context_memory": list(layers.get("context_memory", [])) if include_player_context else [],
        "relationship_memory": list(layers.get("relationship_memory", [])) if include_player_context else [],
        "per_npc_first_person": per_npc_fp,
        "opening_lorebooks": per_npc_lorebooks,
        "source": "card_native_projection",
    }}
