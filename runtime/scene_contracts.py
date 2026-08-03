#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 scene-to-contract binding hooks for group scenes."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - verify skips compiler when yaml missing.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACTS = ROOT / "contracts"

REVIVE_TARGETS = ["苏颖", "姐姐", "龙也"]
REVIVE_VERBS = ["复活", "救活", "让她活", "让他活", "活过来", "不让她死", "不让他死", "时间倒流", "回到"]
OUT_OF_GENRE = ["超能力", "神力", "瞬移", "穿墙", "魔法", "念力"]


def load_contract(node_id: str, contracts_dir: str | Path | None = None) -> dict[str, Any] | None:
    if yaml is None:
        return None
    root = Path(contracts_dir) if contracts_dir else DEFAULT_CONTRACTS
    for suffix in (".yaml", ".yml"):
        path = root / f"{node_id}{suffix}"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    return None


def load_all_contracts(contracts_dir: str | Path | None = None) -> list[dict[str, Any]]:
    if yaml is None:
        return []
    root = Path(contracts_dir) if contracts_dir else DEFAULT_CONTRACTS
    contracts = []
    for path in sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml"))):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            contracts.append(data)
    return contracts


def _event_tokens(text: str | None) -> set[str]:
    return set(re.findall(r"E\d{3}-\d{2}", str(text or "")))


def bind_scene_contract(
    scene_state: dict[str, Any],
    contracts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Bind by explicit node_id first, then by encounter event overlap."""
    anchor = scene_state.get("node_id") or scene_state.get("contract_node") or scene_state.get("canon_anchor") or ""
    if anchor:
        node_id = str(anchor)
        if not node_id.startswith("NODE-"):
            match = re.search(r"NODE-\d+[A-Z0-9_-]*", node_id)
            node_id = match.group(0) if match else ""
        if node_id:
            contract = load_contract(node_id, contracts_dir)
            if contract:
                return {"covered": True, "reason": "BOUND", "node_id": node_id, "contract": contract}

    scene_tokens = set()
    for key in ("canon_anchor", "canon_src", "current_beat", "scene_id"):
        scene_tokens.update(_event_tokens(scene_state.get(key)))
    if not scene_tokens:
        return {"covered": False, "reason": "NO_CANON_ANCHOR", "node_id": None, "contract": None}

    for contract in load_all_contracts(contracts_dir):
        if set(contract.get("entry_conditions", []) or []) & scene_tokens:
            return {
                "covered": True,
                "reason": "BOUND_BY_ENTRY_EVENT",
                "node_id": contract.get("node_id"),
                "contract": contract,
            }
    return {"covered": False, "reason": "CONTRACT_NOT_FOUND", "node_id": None, "contract": None}


def register_branch_progress(state: Any, binding: dict[str, Any], path_ids: list[str] | None) -> list[str]:
    if not binding.get("covered") or not path_ids:
        return []
    node_id = binding.get("node_id")
    valid_paths = {
        str(item.get("id"))
        for item in ((binding.get("contract") or {}).get("path_set") or [])
        if item.get("id")
    }
    if not node_id or not valid_paths:
        return []
    ledger = getattr(state, "branch_progress", None)
    if not isinstance(ledger, dict):
        ledger = {}
        state.branch_progress = ledger
    current = set(ledger.get(node_id, []) or [])
    added = []
    for path_id in path_ids:
        if path_id in valid_paths and path_id not in current:
            current.add(path_id)
            added.append(path_id)
    if added:
        ledger[node_id] = sorted(current)
        state.save()
    return added


def resolve_active_exit_state(state: Any, binding: dict[str, Any]) -> dict[str, Any] | None:
    if not binding.get("covered"):
        return None
    contract = binding.get("contract") or {}
    node_id = binding.get("node_id")
    threshold = int(contract.get("combine_threshold", 0) or 0)
    if not node_id or threshold <= 0:
        return None
    ledger = getattr(state, "branch_progress", {}) or {}
    activated = sorted(set(ledger.get(node_id, []) or []))
    if len(activated) < threshold:
        return None
    for exit_state in contract.get("exit_states", []) or []:
        if str(exit_state.get("id", "")).startswith("branched"):
            return {
                "id": exit_state.get("id"),
                "branch_gate": exit_state.get("branch_gate"),
                "activated_paths": activated,
                "threshold": threshold,
            }
    return None


def adjudicate_scene_contract(
    scene_state: dict[str, Any],
    player_text: str,
    contracts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Small deterministic hook: redlines converge in-story; otherwise leave scene free."""
    binding = bind_scene_contract(scene_state, contracts_dir)
    text = player_text or ""
    if any(v in text for v in REVIVE_VERBS) and any(t in text for t in REVIVE_TARGETS):
        return {
            "mode": "converge",
            "covered": binding["covered"],
            "node_id": binding["node_id"],
            "kind": "SELF_REF",
            "director_line": "话音刚落，现场没有被改写；人的脚步、风声和沉默仍沿着原来的物理方向推进。",
            "tags": ["REDLINE:SELF_REF"],
        }
    if any(k in text for k in OUT_OF_GENRE):
        return {
            "mode": "converge",
            "covered": binding["covered"],
            "node_id": binding["node_id"],
            "kind": "OUT_OF_GENRE",
            "director_line": "这个动作超出了普通人的物理边界，现场只把它当成一句失真的玩笑消化掉。",
            "tags": ["REDLINE:OUT_OF_GENRE"],
        }
    if not binding["covered"]:
        return {
            "mode": "free_scene",
            "covered": False,
            "reason": binding["reason"],
            "node_id": binding["node_id"],
            "contract": binding.get("contract"),
            "tags": ["UNCOVERED_CONTRACT"],
        }

    contract = binding["contract"] or {}
    never = ((contract.get("softening") or {}).get("never_soften")) or []
    for item in never:
        key = str(item).replace("被", "").replace("城", "")
        if item in text or (key and key in text and any(v in text for v in ("取消", "阻止", "不让", "改掉"))):
            return {
                "mode": "converge",
                "covered": True,
                "node_id": binding["node_id"],
                "contract": contract,
                "kind": "FIXED_FLOOR",
                "director_line": f"你试图撬动「{item}」，但这不是能被松开的地方；局势只在细部震动，没有离开既定地基。",
                "tags": ["REDLINE:FIXED_FLOOR"],
            }
    return {
        "mode": "contract_bound",
        "covered": True,
        "node_id": binding["node_id"],
        "contract": contract,
        "tier": contract.get("tier"),
        "canon_locked": list(((contract.get("invariants") or {}).get("canon_locked")) or []),
        "tags": ["CONTRACT_BOUND"],
    }
