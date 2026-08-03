"""Player-facing projections derived from card data and public introduction state."""
from __future__ import annotations

from typing import Any

from runtime.name_book import pre_intro_name


def present_characters_from_card(card: dict[str, Any]) -> list[dict[str, str]]:
    persona_cards = card.get("persona_cards") or {}
    present: list[dict[str, str]] = []
    for raw_cons in card.get("present") or []:
        cons = str(raw_cons)
        persona = persona_cards.get(cons)
        if not isinstance(persona, dict):
            continue
        present.append({"cons": cons, "name": str(persona.get("name") or cons).strip()})
    return present


def build_stage_projection(card: dict[str, Any]) -> dict[str, Any]:
    """Build one spatial truth before rendering player and actor projections.

    Absent an authored exception, every card-listed consciousness shares the
    player's local scene.  This prevents a narrator from silently turning a
    companion into an offscreen watcher.
    """
    authored = card.get("spatial_truth") if isinstance(card.get("spatial_truth"), dict) else {}
    player_position = str(authored.get("player_position") or "shared_scene").strip()
    authored_positions = authored.get("positions") if isinstance(authored.get("positions"), dict) else {}
    characters = []
    for row in present_characters_from_card(card):
        cons = str(row["cons"])
        position = authored_positions.get(cons)
        if not isinstance(position, dict):
            position = {"relation_to_player": "beside_player", "zone": player_position}
        relation = str(position.get("relation_to_player") or "beside_player")
        characters.append({
            **row,
            "relation_to_player": relation,
            "zone": str(position.get("zone") or player_position),
            "player_visible": bool(position.get("player_visible", relation != "offscreen")),
        })
    return {"camera": "player_pov", "player_position": player_position, "characters": characters}


def visible_speaker_label(
    card: dict[str, Any] | None, cons: str, intro_done: bool, introduced_cons: set[str] | None = None,
) -> str:
    persona = ((card or {}).get("persona_cards") or {}).get(cons)
    if not isinstance(persona, dict):
        slug = cons.split(".")[1] if "." in cons else cons
        return slug or cons
    if not intro_done and (introduced_cons is None or cons not in introduced_cons):
        alias = str(persona.get("_alias_visible") or "").strip()
        if alias:
            return alias.split("/")[0].strip()
        pre = pre_intro_name(cons)
        if pre:
            return pre
    return str(persona.get("name") or cons).strip()


def build_player_roster(
    card: dict[str, Any], *, intro_done: bool = False, introduced_cons: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Project the present cast without leaking names before introduction."""
    known = set(introduced_cons or [])
    roster: list[dict[str, Any]] = []
    for row in present_characters_from_card(card):
        cons = str(row["cons"])
        introduced = bool(intro_done or cons in known)
        audience = visible_speaker_label(card, cons, intro_done, known)
        roster.append({
            "cons": cons,
            "audience_label": audience,
            "display_name": audience,
            "debug_name": str(row["name"]),
            "introduced": introduced,
        })
    return roster
