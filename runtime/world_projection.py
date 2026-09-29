"""P2b-1 receipt-driven projections for committed world facts.

Projection reducers may update compatibility views, but they do not decide
whether a fact happened. Their only authority is an already-committed
WorldCommit record.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from runtime.run_observation_ledger import append_observation

PENDANT_PROP = "古铜色金属挂坠项链"
RYUYA_BODY_ID = "B.ryuya.WMAIN"


@dataclass(frozen=True)
class WorldProjectionResult:
    player_state: dict[str, Any]
    body_frames: dict[str, Any]
    observation_ledger: list[dict[str, Any]]


class WorldProjectionState:
    """P2c owner for mutable world projections.

    Session and observers receive deep-copy views. Legacy reducer callbacks may
    mutate only the internal body-frame value handed to them by this owner.
    """

    def __init__(
        self,
        *,
        body_frames: Mapping[str, Any] | None = None,
        observation_ledger: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._body_frames = copy.deepcopy(dict(body_frames or {}))
        self._observation_ledger = [
            copy.deepcopy(dict(item))
            for item in observation_ledger
            if isinstance(item, Mapping)
        ]

    @classmethod
    def from_legacy(cls, raw: Mapping[str, Any]) -> "WorldProjectionState":
        frames = raw.get("body_frames")
        ledger = raw.get("run_observation_ledger")
        return cls(
            body_frames=frames if isinstance(frames, Mapping) else {},
            observation_ledger=ledger if isinstance(ledger, (list, tuple)) else (),
        )

    def reset(self) -> None:
        self._body_frames.clear()
        self._observation_ledger.clear()

    def body_frames_view(self) -> dict[str, Any]:
        return copy.deepcopy(self._body_frames)

    def observation_ledger_view(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._observation_ledger)

    def replace_observation_ledger(
        self,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self._observation_ledger = [
            copy.deepcopy(dict(item))
            for item in rows
            if isinstance(item, Mapping)
        ]

    def append_observation(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._observation_ledger = append_observation(
            self._observation_ledger,
            **kwargs,
        )
        return self.observation_ledger_view()

    def ensure_body_frames(
        self,
        card: dict[str, Any],
        ensure_fn: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]],
    ) -> dict[str, Any]:
        self._body_frames = ensure_fn(card, self._body_frames)
        return self.body_frames_view()

    def settle_body_frames(
        self,
        card: dict[str, Any],
        turns: list[dict[str, Any]],
        *,
        settle_fn: Callable[[dict[str, Any], dict[str, Any], list[dict[str, Any]]], list[str]],
        ensure_fn: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]],
    ) -> list[str]:
        issues = settle_fn(self._body_frames, card, turns)
        self._body_frames = ensure_fn(card, self._body_frames)
        return list(issues or [])

    def apply_world_transaction(
        self,
        record: Mapping[str, Any],
        *,
        player_state: Mapping[str, Any] | None,
        session_id: str = "",
    ) -> dict[str, Any]:
        projected = project_world_transaction(
            record,
            player_state=player_state,
            body_frames=self._body_frames,
            observation_ledger=self._observation_ledger,
            session_id=session_id,
        )
        self._body_frames = copy.deepcopy(projected.body_frames)
        self._observation_ledger = copy.deepcopy(projected.observation_ledger)
        return copy.deepcopy(projected.player_state)


def _world_receipt_id(record: Mapping[str, Any]) -> str:
    receipt = record.get("receipt") if isinstance(record.get("receipt"), Mapping) else {}
    if str(receipt.get("producer") or "") != "WorldCommit":
        raise ValueError("world projection requires a committed WorldCommit receipt")
    receipt_id = str(receipt.get("receipt_id") or "").strip()
    if not receipt_id:
        raise ValueError("world projection requires world receipt id")
    return receipt_id


def project_world_transaction(
    record: Mapping[str, Any],
    *,
    player_state: Mapping[str, Any] | None,
    body_frames: Mapping[str, Any] | None,
    observation_ledger: list[dict[str, Any]] | None,
    session_id: str = "",
) -> WorldProjectionResult:
    """Project one committed fact into compatibility views without new decisions."""
    receipt_id = _world_receipt_id(record)
    state = copy.deepcopy(dict(player_state or {}))
    frames = copy.deepcopy(dict(body_frames or {}))
    observations = [copy.deepcopy(row) for row in (observation_ledger or [])]

    tx_id = str(record.get("transaction_id") or "").strip()
    outcome = str(record.get("outcome") or "").strip()
    scene_id = str(record.get("scene_id") or "").strip()
    turn = int(record.get("turn", 0) or 0)
    run_id = int(record.get("run", 1) or 1)

    if tx_id != "ryuya_pendant_disposition":
        return WorldProjectionResult(state, frames, observations)
    if outcome not in {"accepted", "declined", "deferred"}:
        raise ValueError(f"unsupported pendant disposition projection: {outcome}")

    if outcome == "accepted":
        props = [str(item) for item in (state.get("body_props") or []) if str(item).strip()]
        if PENDANT_PROP not in props:
            props.append(PENDANT_PROP)
        state["body_props"] = props

        frame = frames.get(RYUYA_BODY_ID)
        if isinstance(frame, dict):
            frame["holding"] = None
            frame["hands"] = "free"
            frame["note"] = "挂坠已交到对方手里"
            frame["last_action_type"] = "object_handle"

    observations = append_observation(
        observations,
        turn=turn,
        scene_id=scene_id,
        session_id=str(session_id or ""),
        run_id=run_id,
        fact_text=f"挂坠{outcome}",
        kind="pendant",
        extra={
            "world_receipt_id": receipt_id,
            "world_transaction_id": tx_id,
        },
    )
    return WorldProjectionResult(state, frames, observations)
