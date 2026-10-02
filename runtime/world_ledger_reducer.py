"""P2c ledger reducer for committed/derived world records.

WorldCommit still decides and validates world transactions. This reducer owns
only the in-session storage projections for world transactions, resolver
causal receipts, and the director observation ledger.
"""
from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from runtime.causal_protocol import ReceiptConflict, RuntimeScope, canonical_payload_hash
from runtime.run_observation_ledger import append_observation
from runtime import world_commit


class WorldLedgerReducer:
    def __init__(
        self,
        *,
        world_transactions: Mapping[str, Mapping[str, Any]] | None = None,
        causal_receipts: Iterable[Mapping[str, Any]] = (),
        run_observation_ledger: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self._write_world_transactions(world_transactions or {})
        self._write_causal_receipts(causal_receipts)
        self._write_run_observation_ledger(run_observation_ledger)

    def _write_world_transactions(
        self,
        values: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.world_transactions = {
            str(key): copy.deepcopy(dict(value))
            for key, value in dict(values or {}).items()
            if str(key).strip() and isinstance(value, Mapping)
        }

    def _write_causal_receipts(
        self,
        values: Iterable[Mapping[str, Any]],
    ) -> None:
        self.causal_receipts = [
            copy.deepcopy(dict(value))
            for value in values
            if isinstance(value, Mapping)
        ]

    def _write_run_observation_ledger(
        self,
        values: Iterable[Mapping[str, Any]],
    ) -> None:
        self.run_observation_ledger = [
            copy.deepcopy(dict(value))
            for value in values
            if isinstance(value, Mapping)
        ]

    def transaction_snapshot(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self.world_transactions)

    def causal_snapshot(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.causal_receipts)

    def observation_snapshot(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.run_observation_ledger)

    def replace_transactions(
        self, values: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        self._write_world_transactions(values)
        return self.transaction_snapshot()

    def replace_causal(
        self, values: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        self._write_causal_receipts(values)
        return self.causal_snapshot()

    def replace_observations(
        self, values: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        self._write_run_observation_ledger(values)
        return self.observation_snapshot()

    def clear(self) -> None:
        self._write_world_transactions({})
        self._write_causal_receipts(())
        self._write_run_observation_ledger(())

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        row = self.world_transactions.get(str(transaction_id or "").strip())
        return copy.deepcopy(row) if isinstance(row, dict) else None

    def commit_world_fact(
        self,
        *,
        scope: RuntimeScope,
        request_id: str,
        turn_id: str,
        transaction_id: str,
        kind: str,
        outcome: str,
        owner: str,
        scene_id: str,
        turn: int,
        public_effect: str = "",
        source_refs: Sequence[str] = (),
        base_revision: int = 0,
    ) -> world_commit.WorldCommitResult:
        working = self.transaction_snapshot()
        result = world_commit.commit_world_fact(
            working,
            scope=scope,
            request_id=request_id,
            turn_id=turn_id,
            transaction_id=transaction_id,
            kind=kind,
            outcome=outcome,
            owner=owner,
            scene_id=scene_id,
            turn=turn,
            public_effect=public_effect,
            source_refs=source_refs,
            base_revision=base_revision,
        )
        if result.committed:
            self._write_world_transactions(working)
        return result

    def append_causal_receipt(self, receipt: Mapping[str, Any]) -> bool:
        row = copy.deepcopy(dict(receipt))
        receipt_id = str(row.get("receipt_id") or "").strip()
        if not receipt_id:
            raise ValueError("causal receipt requires receipt_id")
        for existing in self.causal_receipts:
            if str(existing.get("receipt_id") or "") != receipt_id:
                continue
            if canonical_payload_hash(existing) != canonical_payload_hash(row):
                raise ReceiptConflict(
                    f"causal receipt id reused with different payload: {receipt_id}"
                )
            return False
        self._write_causal_receipts([*self.causal_receipts, row])
        return True

    def append_observation(
        self,
        *,
        kind: str,
        fact_text: str,
        turn: int = 0,
        scene_id: str = "",
        session_id: str = "",
        run_id: int | str = 1,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        before = self.observation_snapshot()
        after = append_observation(
            before,
            kind=kind,
            fact_text=fact_text,
            turn=turn,
            scene_id=scene_id,
            session_id=session_id,
            run_id=run_id,
            extra=extra,
        )
        if after == before:
            return False
        self._write_run_observation_ledger(after)
        return True
