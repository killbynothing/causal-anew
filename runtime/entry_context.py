"""Explicit, serialisable context for arriving at a scene from another route.

Scene cards own the physical frame and the NPCs currently present.  They do not
own the player's social identity or the reason the player arrived.  This small
value object is the hand-off boundary between those two concerns.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EntryContext:
    entry_id: str
    source_opening_id: str
    source_line: str
    arrival_reason: str
    public_context: list[str] = field(default_factory=list)
    relationship_context: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for field_name in ("entry_id", "source_opening_id", "source_line", "arrival_reason"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"EntryContext.{field_name} must not be blank")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "EntryContext | None":
        if not isinstance(raw, dict):
            return None
        return cls(
            entry_id=str(raw.get("entry_id", "")).strip(),
            source_opening_id=str(raw.get("source_opening_id", "")).strip(),
            source_line=str(raw.get("source_line", "")).strip(),
            arrival_reason=str(raw.get("arrival_reason", "")).strip(),
            public_context=[str(item).strip() for item in raw.get("public_context", []) if str(item).strip()],
            relationship_context=[str(item).strip() for item in raw.get("relationship_context", []) if str(item).strip()],
        )
