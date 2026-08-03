#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S0: scan free_stage cards → seed migration registry CSV.

Output: data/seed_migration_registry_2026-08-01.csv
Columns: field_path, card_source, classification, target_table, batch, status, note
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARD_GLOB = "runtime/free_stage_card_*.json"
OUT = ROOT / "data" / "seed_migration_registry_2026-08-01.csv"

# Plan §2 classification constitution (field name → class/batch/target)
RULES: list[tuple[str, str, str, str]] = [
    # suffix-match on leaf or path segment
    ("identity_relations", "Seed", "propositions+knowledge_schedule", "A"),
    ("body_props", "Seed", "items/body_profile", "A"),
    ("name", "Seed", "archetypes/consciousnesses", "A"),
    ("voice_samples", "Seed", "persona_core", "C"),
    ("boundaries", "Seed", "persona_core", "C"),
    ("constraints", "Mixed", "persona_core|storylet.invariants", "C/D"),
    ("memory_context", "Seed", "slow_memory", "C"),
    ("inner_state", "Storylet", "storylet.entry_affect", "D"),
    ("scene_working_memory", "Run/Session", "run_ledger+cache", "—"),
    ("must_happen", "Storylet", "node_contracts", "D"),
    ("exits", "Storylet", "node_contracts", "D"),
    ("locks", "Storylet", "node_contracts", "D"),
    ("canon_performance", "Storylet", "node_contracts", "D"),
    ("branch_rules", "Storylet", "node_contracts", "D"),
    ("branch_points", "Storylet", "node_contracts", "D"),
    ("force_exit", "Storylet", "node_contracts", "D"),
    ("director_beats", "Storylet", "node_contracts", "D"),
    ("director_only_characters", "Storylet", "node_contracts", "D"),
    ("intent_affordances", "Storylet", "node_contracts", "D"),
    ("social_inference_rules", "Storylet", "node_contracts", "D"),
    ("autonomous_decisions", "Storylet", "node_contracts", "D"),
    ("scene_frame", "Storylet", "node_contracts", "D"),
    ("blurb", "Storylet", "node_contracts", "D"),
    ("entry_hook", "Storylet", "node_contracts", "D"),
    ("ambient_stage", "Storylet", "node_contracts", "D"),
    ("ambient_actor_profiles", "Storylet", "node_contracts", "D"),
    ("current_event_terms", "Storylet", "node_contracts", "D"),
    ("scene_source_excerpt", "Storylet", "node_contracts", "D"),
    ("knowledge_gate", "Seed", "knowledge_schedule", "A"),
    ("context_memory", "Mixed", "slow_memory|run", "C/D"),
    ("relationship_memory", "Mixed", "REL|run", "C/D"),
    ("creative_status", "Discard", "—", "—"),
    ("creative_note", "Discard", "—", "—"),
    ("situation_facets", "Seed", "facet_store", "C"),
]


def classify(path: str) -> tuple[str, str, str]:
    leaf = path.split(".")[-1]
    # strip array indices
    leaf = leaf.split("[")[0]
    for key, cls, target, batch in RULES:
        if leaf == key or f".{key}." in f".{path}." or path.endswith(f".{key}"):
            return cls, target, batch
    # persona_cards container
    if path.startswith("persona_cards."):
        return "Mixed", "see_leaf", "?"
    if path in {"scene", "scene_id", "ch_anchor", "clock", "present", "prologue_active", "exit_menu"}:
        return "Storylet", "node_contracts/meta", "D"
    if path.startswith("intro_") or path.startswith("names_known") or path.startswith("player_"):
        return "Storylet", "node_contracts", "D"
    return "Unclassified", "TBD", "?"


def walk(obj: Any, prefix: str, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            out.add(path)
            walk(v, path, out)
    elif isinstance(obj, list) and obj:
        # record list container; sample first element shape
        out.add(f"{prefix}[]")
        if isinstance(obj[0], (dict, list)):
            walk(obj[0], f"{prefix}[]", out)


def main() -> int:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for card_path in sorted((ROOT / "runtime").glob("free_stage_card_*.json")):
        card = json.loads(card_path.read_text(encoding="utf-8"))
        paths: set[str] = set()
        walk(card, "", paths)
        for path in sorted(paths):
            key = (path, card_path.name)
            if key in seen:
                continue
            seen.add(key)
            cls, target, batch = classify(path)
            rows.append(
                {
                    "field_path": path,
                    "card_source": card_path.name,
                    "classification": cls,
                    "target_table": target,
                    "batch": batch,
                    "status": "registered",
                    "note": "",
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "field_path",
                "card_source",
                "classification",
                "target_table",
                "batch",
                "status",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT} rows={len(rows)} cards={len(list((ROOT/'runtime').glob('free_stage_card_*.json')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
