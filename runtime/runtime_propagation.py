#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 helpers: feed scene-created runtime propositions into runtime_gate."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
C1_CONSOLE = ROOT / "c1_web_console"
if str(C1_CONSOLE) not in sys.path:
    sys.path.insert(0, str(C1_CONSOLE))

from runtime_gate import learned, propagate, record_event  # type: ignore


def _prop_id(prop: dict[str, Any], index: int) -> str:
    return str(prop.get("prop_id") or prop.get("id") or f"RT.SCENE.{index:03d}")


def ingest_created_runtime_props(
    scene_log: list[dict[str, Any]],
    *,
    store: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Record created_runtime_props with the row's visible_to as immediate witnesses."""
    recorded: list[dict[str, Any]] = []
    for row_index, row in enumerate(scene_log):
        run_no = int(row.get("run_no", 1))
        if run_no == 0:
            raise ValueError("run=0 is read-only; runtime props may only append to run>=1")
        witnesses = list(row.get("visible_to") or [])
        for prop_index, prop in enumerate(row.get("created_runtime_props") or []):
            if isinstance(prop, str):
                prop_obj = {"prop_id": prop, "statement": prop}
            elif isinstance(prop, dict):
                prop_obj = prop
            else:
                continue
            pid = _prop_id(prop_obj, row_index * 100 + prop_index)
            statement = str(prop_obj.get("statement") or prop_obj.get("text") or pid)
            info = record_event(run_no, pid, statement, witnesses, store=store)
            recorded.append({"run_no": run_no, "prop_id": pid, "statement": statement, "learned_by": info["learned_by"]})
    return recorded


def propagate_runtime_prop(
    run_no: int,
    prop_id: str,
    *,
    to: list[str],
    store: str | Path | None = None,
) -> dict[str, Any] | None:
    """Explicitly propagate one runtime proposition. Empty targets do nothing."""
    if int(run_no) == 0:
        raise ValueError("run=0 is read-only; runtime props may only append to run>=1")
    if not to:
        return None
    return propagate(run_no, prop_id, to, store=store)


def runtime_props_for_cons(
    run_no: int,
    cons: str,
    *,
    store: str | Path | None = None,
) -> dict[str, str]:
    return learned(run_no, cons, store=store)
