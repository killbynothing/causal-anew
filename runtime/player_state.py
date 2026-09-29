"""P2c-6 single owner for mutable player runtime state.

This module consolidates write authority only. It deliberately preserves the
existing runtime semantics, including the current +2 elapsed-minutes-per-turn
rule, until a separate pacing/time design decision changes it.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence


DEFAULT_PLAYER_STATE: dict[str, Any] = {
    "injury": "正常/良好",
    "status": "行动中",
    "convergence_rate": 100,
    "energy": 0.78,
    "physical": "good",
    "elapsed_minutes": 0,
}


def _normalized(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_PLAYER_STATE)
    if isinstance(raw, Mapping):
        state.update(copy.deepcopy(dict(raw)))
    state.setdefault("convergence_rate", 100)
    state.setdefault("energy", 0.78)
    state.setdefault("physical", "good")
    state.setdefault("elapsed_minutes", 0)
    return state


class PlayerStateOwner:
    """Own the current player-state dict and expose copy-only projections."""

    def __init__(self, state: Mapping[str, Any] | None = None) -> None:
        self._state = _normalized(state)

    @classmethod
    def from_legacy(cls, raw: Mapping[str, Any] | None) -> "PlayerStateOwner":
        return cls(raw)

    def view(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def reset(self) -> dict[str, Any]:
        self._state = _normalized(None)
        return self.view()

    def replace(self, state: Mapping[str, Any]) -> dict[str, Any]:
        self._state = _normalized(state)
        return self.view()

    def patch(
        self,
        updates: Mapping[str, Any],
        *,
        preserve_keys: Sequence[str] = (),
    ) -> dict[str, Any]:
        preserved = {
            str(key): copy.deepcopy(self._state.get(str(key)))
            for key in preserve_keys
        }
        self._state.update(copy.deepcopy(dict(updates)))
        for key, value in preserved.items():
            self._state[key] = value
        return self.view()

    def advance_elapsed(self, minutes: int = 2) -> int:
        current = int(self._state.get("elapsed_minutes", 0) or 0)
        self._state["elapsed_minutes"] = current + int(minutes)
        return int(self._state["elapsed_minutes"])

    def reset_elapsed(self) -> None:
        self._state["elapsed_minutes"] = 0

    def reduce_convergence(self, amount: int = 10) -> int:
        current = int(self._state.get("convergence_rate", 100) or 0)
        value = max(0, current - int(amount))
        self._state["convergence_rate"] = value
        return value

    def apply_offscreen(
        self,
        updates: Mapping[str, Any],
        *,
        preserve_elapsed: bool = True,
    ) -> dict[str, Any]:
        preserve = ("elapsed_minutes",) if preserve_elapsed else ()
        return self.patch(updates, preserve_keys=preserve)

    def project_branch_status(
        self,
        branch_progress: Sequence[str],
        *,
        ended: bool,
    ) -> dict[str, Any]:
        facts = {str(item) for item in branch_progress if str(item).strip()}
        if "choiceA_brace" in facts:
            self._state["injury"] = "肋骨骨折 (重伤残血)"
        elif "B1_dog" in facts:
            self._state["injury"] = "无明显外伤"
        self._state["status"] = "已完成" if bool(ended) else "行动中"
        return self.view()
