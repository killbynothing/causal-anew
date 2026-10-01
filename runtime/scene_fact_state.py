"""P2c append-only scene fact authority.

Branch markers and observable scene receipts are projections of immutable
FactEvents. Assertions activate facts, revocations deactivate them, and
observations preserve who/what was publicly evidenced without changing truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from runtime.causal_protocol import ReceiptConflict, canonical_payload_hash

SCENE_FACT_STATE_SCHEMA = "free_stage.scene_fact_state.v1"
FACT_EVENT_SCHEMA = "free_stage.fact_event.v1"
VALID_OPS = frozenset({"assert", "revoke", "observe"})


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class FactEvent:
    event_id: str
    op: str
    scene_id: str
    scene_instance_id: str
    fact_id: str
    owner: str
    turn: int
    source_kind: str
    source_ref: str
    source_input: str = ""
    schema_version: str = FACT_EVENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != FACT_EVENT_SCHEMA:
            raise ValueError(f"unsupported fact event schema: {self.schema_version}")
        if self.op not in VALID_OPS:
            raise ValueError(f"unsupported fact op: {self.op}")
        for name in (
            "event_id", "scene_id", "scene_instance_id", "fact_id",
            "owner", "source_kind", "source_ref",
        ):
            if not _text(getattr(self, name)):
                raise ValueError(f"fact event requires {name}")
        if int(self.turn) < 0:
            raise ValueError("fact event turn must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "op": self.op,
            "scene_id": self.scene_id,
            "scene_instance_id": self.scene_instance_id,
            "fact_id": self.fact_id,
            "owner": self.owner,
            "turn": int(self.turn),
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_input": self.source_input,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "FactEvent":
        return cls(
            schema_version=_text(raw.get("schema_version")) or FACT_EVENT_SCHEMA,
            event_id=_text(raw.get("event_id")),
            op=_text(raw.get("op")),
            scene_id=_text(raw.get("scene_id")),
            scene_instance_id=_text(raw.get("scene_instance_id")),
            fact_id=_text(raw.get("fact_id")),
            owner=_text(raw.get("owner")),
            turn=int(raw.get("turn", 0) or 0),
            source_kind=_text(raw.get("source_kind")),
            source_ref=_text(raw.get("source_ref")),
            source_input=str(raw.get("source_input") or ""),
        )


class SceneFactState:
    def __init__(self, events: Iterable[FactEvent] = ()) -> None:
        self._events: list[FactEvent] = []
        self._by_id: dict[str, FactEvent] = {}
        for event in events:
            self._append_existing(event)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SceneFactState":
        if raw.get("schema_version") != SCENE_FACT_STATE_SCHEMA:
            raise ValueError("unsupported scene fact state schema")
        rows = raw.get("events")
        if not isinstance(rows, list):
            raise ValueError("scene fact state requires events list")
        return cls(
            FactEvent.from_dict(row)
            for row in rows
            if isinstance(row, Mapping)
        )

    @classmethod
    def from_legacy(
        cls,
        *,
        branch_progress: Iterable[str],
        scene_receipts: Iterable[Mapping[str, Any]],
        current_scene_id: str,
        current_scene_instance_id: str,
    ) -> "SceneFactState":
        state = cls()
        for fact in branch_progress:
            fact_id = _text(fact)
            if fact_id:
                state.assert_fact(
                    fact_id,
                    scene_id=current_scene_id,
                    scene_instance_id=current_scene_instance_id,
                    owner="legacy",
                    turn=0,
                    source_kind="legacy_snapshot",
                    source_ref="legacy:branch_progress",
                )
        for row in scene_receipts:
            if not isinstance(row, Mapping):
                continue
            fact_id = _text(row.get("fact_id"))
            if not fact_id:
                continue
            scene_id = _text(row.get("scene_id")) or current_scene_id
            scene_instance = (
                current_scene_instance_id
                if scene_id == current_scene_id
                else f"{scene_id}:legacy:1"
            )
            state.observe_fact(
                fact_id,
                scene_id=scene_id,
                scene_instance_id=scene_instance,
                owner=_text(row.get("owner")) or "legacy",
                turn=int(row.get("turn", 0) or 0),
                source_kind=_text(row.get("source_kind")) or "legacy_snapshot",
                source_ref=f"legacy:scene_receipt:{scene_id}:{fact_id}",
                source_input=str(row.get("source_input") or ""),
            )
        return state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCENE_FACT_STATE_SCHEMA,
            "events": [event.to_dict() for event in self._events],
        }

    def events(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]

    def active_facts(self) -> list[str]:
        active: dict[str, bool] = {}
        order: list[str] = []
        for event in self._events:
            if event.op == "assert":
                if event.fact_id not in active:
                    order.append(event.fact_id)
                active[event.fact_id] = True
            elif event.op == "revoke":
                active[event.fact_id] = False
        return [fact for fact in order if active.get(fact, False)]

    def observations(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in self._events:
            if event.op != "observe":
                continue
            out.append({
                "scene_id": event.scene_id,
                "scene_instance_id": event.scene_instance_id,
                "fact_id": event.fact_id,
                "owner": event.owner,
                "turn": int(event.turn),
                "source_input": event.source_input,
                "source_kind": event.source_kind,
                "source_ref": event.source_ref,
                "event_id": event.event_id,
            })
        return out

    def is_active(self, fact_id: str) -> bool:
        return _text(fact_id) in set(self.active_facts())

    def assert_fact(
        self,
        fact_id: str,
        *,
        scene_id: str,
        scene_instance_id: str,
        owner: str,
        turn: int,
        source_kind: str,
        source_ref: str,
        source_input: str = "",
    ) -> bool:
        fact = _text(fact_id)
        if not fact:
            return False
        if self.is_active(fact):
            return False
        self._append_new(
            op="assert", fact_id=fact, scene_id=scene_id,
            scene_instance_id=scene_instance_id, owner=owner, turn=turn,
            source_kind=source_kind, source_ref=source_ref,
            source_input=source_input,
        )
        return True

    def revoke_fact(
        self,
        fact_id: str,
        *,
        scene_id: str,
        scene_instance_id: str,
        owner: str,
        turn: int,
        source_kind: str,
        source_ref: str,
    ) -> bool:
        fact = _text(fact_id)
        if not fact or not self.is_active(fact):
            return False
        self._append_new(
            op="revoke", fact_id=fact, scene_id=scene_id,
            scene_instance_id=scene_instance_id, owner=owner, turn=turn,
            source_kind=source_kind, source_ref=source_ref,
        )
        return True

    def revoke_matching(
        self,
        predicate: Callable[[str], bool],
        *,
        scene_id: str,
        scene_instance_id: str,
        owner: str,
        turn: int,
        source_kind: str,
        source_ref: str,
    ) -> list[str]:
        revoked: list[str] = []
        for fact in list(self.active_facts()):
            if predicate(fact) and self.revoke_fact(
                fact,
                scene_id=scene_id,
                scene_instance_id=scene_instance_id,
                owner=owner,
                turn=turn,
                source_kind=source_kind,
                source_ref=source_ref,
            ):
                revoked.append(fact)
        return revoked

    def observe_fact(
        self,
        fact_id: str,
        *,
        scene_id: str,
        scene_instance_id: str,
        owner: str,
        turn: int,
        source_kind: str,
        source_ref: str,
        source_input: str = "",
    ) -> bool:
        fact = _text(fact_id)
        if not fact:
            return False
        # One observable receipt per fact per scene instance. Revisit = new id.
        if any(
            event.op == "observe"
            and event.fact_id == fact
            and event.scene_instance_id == scene_instance_id
            for event in self._events
        ):
            return False
        self._append_new(
            op="observe", fact_id=fact, scene_id=scene_id,
            scene_instance_id=scene_instance_id, owner=owner, turn=turn,
            source_kind=source_kind, source_ref=source_ref,
            source_input=source_input,
        )
        return True

    def _append_new(
        self,
        *,
        op: str,
        fact_id: str,
        scene_id: str,
        scene_instance_id: str,
        owner: str,
        turn: int,
        source_kind: str,
        source_ref: str,
        source_input: str = "",
    ) -> FactEvent:
        payload = {
            "op": _text(op),
            "scene_id": _text(scene_id),
            "scene_instance_id": _text(scene_instance_id),
            "fact_id": _text(fact_id),
            "owner": _text(owner),
            "turn": int(turn),
            "source_kind": _text(source_kind),
            "source_ref": _text(source_ref),
            "source_input": str(source_input or ""),
        }
        event = FactEvent(
            event_id=f"fact:{canonical_payload_hash(payload)}",
            **payload,
        )
        self._append_existing(event)
        return event

    def _append_existing(self, event: FactEvent) -> None:
        existing = self._by_id.get(event.event_id)
        if existing is not None:
            if existing != event:
                raise ReceiptConflict(
                    f"fact event id reused with different payload: {event.event_id}"
                )
            return
        self._events.append(event)
        self._by_id[event.event_id] = event
