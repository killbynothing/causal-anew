#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assert seed migration registry covers the free_stage card field union."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "data" / "seed_migration_registry_2026-08-01.csv"


def walk(obj, prefix: str, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            out.add(path)
            walk(v, path, out)
    elif isinstance(obj, list) and obj:
        out.add(f"{prefix}[]")
        if isinstance(obj[0], (dict, list)):
            walk(obj[0], f"{prefix}[]", out)


def main() -> int:
    if not REG.exists():
        print(f"[FAIL] missing registry: {REG}")
        return 1
    registered: set[str] = set()
    with REG.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            registered.add(row["field_path"])

    card_fields: set[str] = set()
    for card_path in sorted((ROOT / "runtime").glob("free_stage_card_*.json")):
        card = json.loads(card_path.read_text(encoding="utf-8"))
        walk(card, "", card_fields)

    missing = sorted(card_fields - registered)
    if missing:
        print(f"[FAIL] registry missing {len(missing)} field paths (show ≤20):")
        for p in missing[:20]:
            print(f"  - {p}")
        return 1
    print(f"[PASS] registry covers card field union ({len(card_fields)} paths, {len(registered)} registry rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
