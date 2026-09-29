"""P2a player-action authority.

A player action receipt records only what the player did or said they chose.
It never asserts custody, location, success, or any other world outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping, Sequence

from runtime.causal_protocol import (
    ReceiptConflict,
    ReceiptEnvelope,
    RuntimeScope,
    canonical_payload_hash,
)

PLAYER_ACTION_SCHEMA = "free_stage.player_action.v1"


@dataclass(frozen=True)
class PlayerActionCommitResult:
    record: dict[str, Any]
    committed: bool


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_player_action(
    *,
    scope: RuntimeScope,
    request_id: str,
    turn_id: str,
    action_id: str,
    action_kind: str,
    target: str,
    value: str,
    turn: int,
    source_refs: Sequence[str] = (),
    base_revision: int = 0,
) -> dict[str, Any]:
    aid = _text(action_id)
    req = _text(request_id)
    kind = _text(action_kind)
    if not aid or not req or not kind:
        raise ValueError("player action requires action/request/kind")
    if int(turn) < 0:
        raise ValueError("player action turn must be >= 0")
    payload = {
        "action_id": aid,
        "actor": "player",
        "action_kind": kind,
        "target": _text(target),
        "value": _text(value),
        "turn": int(turn),
    }
    receipt = ReceiptEnvelope.for_payload(
        receipt_id=f"player:{canonical_payload_hash({'scope': scope.to_dict(), 'action_id': aid})}",
        request_id=req,
        turn_id=_text(turn_id) or f"turn:{int(turn)}",
        sequence=0,
        scope=scope,
        producer="PlayerAction",
        source_refs=tuple(_text(item) for item in source_refs if _text(item)),
        visibility="public",
        base_revision=int(base_revision),
        payload=payload,
    )
    return {
        "schema_version": PLAYER_ACTION_SCHEMA,
        "action": payload,
        "receipt": receipt.to_dict(),
    }


def commit_player_action(
    ledger: MutableMapping[str, dict[str, Any]],
    record: dict[str, Any],
) -> PlayerActionCommitResult:
    action = record.get("action") if isinstance(record.get("action"), dict) else {}
    action_id = _text(action.get("action_id"))
    if record.get("schema_version") != PLAYER_ACTION_SCHEMA or not action_id:
        raise ValueError("invalid player action record")
    existing = ledger.get(action_id)
    if existing is not None:
        if canonical_payload_hash(existing) != canonical_payload_hash(record):
            raise ReceiptConflict(f"player action id reused with different payload: {action_id}")
        return PlayerActionCommitResult(record=dict(existing), committed=False)
    ledger[action_id] = dict(record)
    return PlayerActionCommitResult(record=dict(record), committed=True)
