"""P2a player-action receipts.

A player-action receipt proves only what the player publicly said or did. It
never asserts custody, world truth, NPC belief, relationship outcome, or beat
success.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.causal_protocol import RuntimeScope, canonical_payload_hash, ReceiptConflict


@dataclass(frozen=True)
class PlayerActionReceipt:
    receipt_id: str
    request_id: str
    scope: RuntimeScope
    turn: int
    speech: str
    action: str
    claimed_fact_id: str
    payload_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "free_stage.player_action_receipt.v1",
            "receipt_id": self.receipt_id,
            "request_id": self.request_id,
            "scope": self.scope.to_dict(),
            "turn": self.turn,
            "speech": self.speech,
            "action": self.action,
            "claimed_fact_id": self.claimed_fact_id,
            "payload_hash": self.payload_hash,
        }


def player_action_for_fact(
    *,
    scope: RuntimeScope,
    request_id: str,
    turn: int,
    player_input: str | Mapping[str, Any],
    fact_id: str,
) -> PlayerActionReceipt:
    if scope.run < 1:
        raise ValueError("player action receipt requires run>=1")
    request = str(request_id or "").strip()
    fact = str(fact_id or "").strip()
    if not request or not fact:
        raise ValueError("player action receipt requires request_id/fact_id")
    if isinstance(player_input, Mapping):
        speech = str(player_input.get("speech") or "").strip()
        action = str(player_input.get("action") or "").strip()
    else:
        speech = str(player_input or "").strip()
        action = ""
    payload = {
        "scope": scope.to_dict(),
        "turn": int(turn),
        "speech": speech,
        "action": action,
        "claimed_fact_id": fact,
    }
    return PlayerActionReceipt(
        receipt_id=f"playeract:{request}:{fact}",
        request_id=request,
        scope=scope,
        turn=int(turn),
        speech=speech,
        action=action,
        claimed_fact_id=fact,
        payload_hash=canonical_payload_hash(payload),
    )


def assert_same_player_action(
    existing: PlayerActionReceipt,
    candidate: PlayerActionReceipt,
) -> PlayerActionReceipt:
    if existing.receipt_id != candidate.receipt_id or existing != candidate:
        raise ReceiptConflict(f"player action receipt conflict: {candidate.receipt_id}")
    return existing
