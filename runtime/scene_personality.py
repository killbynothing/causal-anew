"""C0 scene-personality package shape; content remains human-reviewed.

`environment_palette` is a director material library (weather, light, sound,
objects that may exist). It is not a forced opening beat script. Prefer it over
legacy `entry_hooks` when both are present.
"""
from __future__ import annotations
from typing import Mapping

REQUIRED = (
    "scene_id",
    "source_refs",
    "sensory_tone",
    "environment_events",
    "interactive_objects",
    "invariants",
    "natural_wait_point",
    "human_arbitration",
)

# At least one of these must be present and non-empty.
PALETTE_KEYS = ("environment_palette", "entry_hooks")


def validate_scene_personality(package: Mapping[str, object]) -> None:
    for key in REQUIRED:
        value = package.get(key)
        if value in (None, "", [], {}):
            raise ValueError(f"scene personality missing {key}")
    if not isinstance(package.get("source_refs"), list):
        raise ValueError("source_refs must be a list")
    if not isinstance(package.get("human_arbitration"), list):
        raise ValueError("human_arbitration must be a list")
    if not any(package.get(key) not in (None, "", [], {}) for key in PALETTE_KEYS):
        raise ValueError("scene personality needs environment_palette or entry_hooks")
