"""Player-facing entry facts owned by a scene card.

The physical scene card may contribute public arrival context for its own native
entry.  Cross-line identity is deliberately outside this module and travels in
``EntryContext`` instead.
"""
from __future__ import annotations

from typing import Any


def apply_card_entry_projection(
    block: dict[str, dict[str, Any]], card: dict[str, Any], *, enabled: bool
) -> dict[str, dict[str, Any]]:
    """Append a card's native, player-visible entry facts when explicitly allowed."""
    if not enabled:
        return block
    projection = card.get("entry_projection") if isinstance(card.get("entry_projection"), dict) else {}
    opening = block.get("__opening__")
    if not projection or not isinstance(opening, dict):
        return block
    opening["context_memory"] = list(opening.get("context_memory", [])) + [
        str(item).strip() for item in projection.get("context_memory", []) if str(item).strip()
    ]
    opening["relationship_memory"] = list(opening.get("relationship_memory", [])) + [
        str(item).strip() for item in projection.get("relationship_memory", []) if str(item).strip()
    ]
    return block
