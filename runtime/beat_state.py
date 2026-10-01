"""P2c authoritative BeatState and immutable BeatReceipts.

Beat completion is scene-instance scoped. completed and completed_by_card are
compatibility projections derived from this state, not writable ledgers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from runtime.causal_protocol import canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"
BEAT_RECEIPT_SCHEMA = "free_stage.beat_receipt.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def scene_instance_id(scene_id: str, visit_no: int) -> str:
    scene = _text(scene_id)
    if not scene or int(visit_no) < 1:
        raise ValueError("scene instance requires scene_id and visit_no>=1")
    return f"{scene}:visit:{int(visit_no)}"


@dataclass(frozen=True)
class BeatReceipt:
    receipt_id: str
    scene_id: str
    scene_instance_id: str
    beat_id: str
    source_kind: str
    source_ref: str
    turn: int
    schema_version: str = BEAT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != BEAT_RECEIPT_SCHEMA:
            raise ValueError(f"unsupported beat receipt schema: {self.schema_version}")
        for name in ("receipt_id", "scene_id", "scene_instance_id", "beat_id", "source_kind", "source_ref"):
            if not _text(getattr(self, name)):
                raise ValueError(f"beat receipt requires {name}")
        if int(self.turn) < 0:
            raise ValueError("beat receipt turn must be >=0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "scene_id": self.scene_id,
            "scene_instance_id": self.scene_instance_id,
            "beat_id": self.beat_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "turn": int(self.turn),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BeatReceipt":
        return cls(
            schema_version=_text(raw.get("schema_version")) or BEAT_RECEIPT_SCHEMA,
            receipt_id=_text(raw.get("receipt_id")),
            scene_id=_text(raw.get("scene_id")),
            scene_instance_id=_text(raw.get("scene_instance_id")),
            beat_id=_text(raw.get("beat_id")),
            source_kind=_text(raw.get("source_kind")),
            source_ref=_text(raw.get("source_ref")),
            turn=int(raw.get("turn", 0) or 0),
        )


class BeatState:
    def __init__(
        self,
        *,
        current_scene_id: str,
        current_scene_instance_id: str,
        scene_order: list[str] | None = None,
        visits: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.current_scene_id = _text(current_scene_id)
        self.current_scene_instance_id = _text(current_scene_instance_id)
        if not self.current_scene_id or not self.current_scene_instance_id:
            raise ValueError("BeatState requires current scene and scene instance")
        self._scene_order = [str(x) for x in (scene_order or []) if _text(x)]
        self._visits: dict[str, dict[str, Any]] = {}
        for instance, raw in dict(visits or {}).items():
            if not isinstance(raw, Mapping):
                continue
            scene = _text(raw.get("scene_id"))
            receipts_raw = raw.get("receipts") or {}
            if not scene or not isinstance(receipts_raw, Mapping):
                raise ValueError(f"invalid beat visit: {instance}")
            receipts: dict[str, BeatReceipt] = {}
            for beat_id, receipt_raw in receipts_raw.items():
                if not isinstance(receipt_raw, Mapping):
                    raise ValueError(f"invalid beat receipt: {instance}/{beat_id}")
                receipt = BeatReceipt.from_dict(receipt_raw)
                if receipt.scene_instance_id != str(instance) or receipt.scene_id != scene:
                    raise ValueError("beat receipt scope mismatch")
                receipts[_text(beat_id)] = receipt
            self._visits[str(instance)] = {"scene_id": scene, "receipts": receipts}
        if self.current_scene_instance_id not in self._visits:
            self._visits[self.current_scene_instance_id] = {
                "scene_id": self.current_scene_id,
                "receipts": {},
            }
        if self.current_scene_instance_id not in self._scene_order:
            self._scene_order.append(self.current_scene_instance_id)
        current = self._visits[self.current_scene_instance_id]
        if current["scene_id"] != self.current_scene_id:
            raise ValueError("current beat scene/instance mismatch")

    @classmethod
    def new(cls, scene_id: str, *, visit_no: int = 1) -> "BeatState":
        instance = scene_instance_id(scene_id, visit_no)
        return cls(
            current_scene_id=scene_id,
            current_scene_instance_id=instance,
            scene_order=[instance],
            visits={instance: {"scene_id": scene_id, "receipts": {}}},
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BeatState":
        if raw.get("schema_version") != BEAT_STATE_SCHEMA:
            raise ValueError("unsupported beat state schema")
        return cls(
            current_scene_id=_text(raw.get("current_scene_id")),
            current_scene_instance_id=_text(raw.get("current_scene_instance_id")),
            scene_order=[str(x) for x in (raw.get("scene_order") or [])],
            visits=raw.get("visits") if isinstance(raw.get("visits"), Mapping) else {},
        )

    @classmethod
    def from_legacy(
        cls,
        *,
        current_scene_id: str,
        current_completed: Iterable[str],
        completed_by_card: Mapping[str, Iterable[str]],
        card_history: Iterable[str],
    ) -> "BeatState":
        history = [_text(x) for x in card_history if _text(x)]
        if not history:
            history = [_text(current_scene_id)]
        counters: dict[str, int] = {}
        order: list[str] = []
        visits: dict[str, dict[str, Any]] = {}
        latest_for_scene: dict[str, str] = {}
        for scene in history:
            counters[scene] = counters.get(scene, 0) + 1
            instance = scene_instance_id(scene, counters[scene])
            order.append(instance)
            visits[instance] = {"scene_id": scene, "receipts": {}}
            latest_for_scene[scene] = instance

        current_scene = _text(current_scene_id) or history[-1]
        current_instance = latest_for_scene.get(current_scene)
        if current_instance is None:
            counters[current_scene] = counters.get(current_scene, 0) + 1
            current_instance = scene_instance_id(current_scene, counters[current_scene])
            order.append(current_instance)
            visits[current_instance] = {"scene_id": current_scene, "receipts": {}}
            latest_for_scene[current_scene] = current_instance

        state = cls(
            current_scene_id=current_scene,
            current_scene_instance_id=current_instance,
            scene_order=order,
            visits=visits,
        )
        for scene, beats in dict(completed_by_card or {}).items():
            scene_key = _text(scene)
            instance = latest_for_scene.get(scene_key)
            if not instance:
                continue
            old_scene = state.current_scene_id
            old_instance = state.current_scene_instance_id
            state.current_scene_id = scene_key
            state.current_scene_instance_id = instance
            for beat in beats or ():
                bid = _text(beat)
                if bid:
                    state.complete(
                        bid,
                        source_kind="legacy_snapshot",
                        source_ref=f"legacy:completed_by_card:{scene_key}",
                        turn=0,
                    )
            state.current_scene_id = old_scene
            state.current_scene_instance_id = old_instance
        for beat in current_completed or ():
            bid = _text(beat)
            if bid:
                state.complete(
                    bid,
                    source_kind="legacy_snapshot",
                    source_ref=f"legacy:current:{current_scene}",
                    turn=0,
                )
        return state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BEAT_STATE_SCHEMA,
            "current_scene_id": self.current_scene_id,
            "current_scene_instance_id": self.current_scene_instance_id,
            "scene_order": list(self._scene_order),
            "visits": {
                instance: {
                    "scene_id": visit["scene_id"],
                    "receipts": {
                        beat: receipt.to_dict()
                        for beat, receipt in visit["receipts"].items()
                    },
                }
                for instance, visit in self._visits.items()
            },
        }

    def enter_scene(
        self,
        *,
        scene_id: str,
        scene_instance_id: str,
        restored_beats: Iterable[str] = (),
        source_kind: str,
        source_ref: str,
        turn: int,
    ) -> None:
        scene = _text(scene_id)
        instance = _text(scene_instance_id)
        if not scene or not instance:
            raise ValueError("enter_scene requires scene and instance")
        existing = self._visits.get(instance)
        if existing is not None and existing["scene_id"] != scene:
            raise ValueError("scene instance reused for different scene")
        if existing is None:
            self._visits[instance] = {"scene_id": scene, "receipts": {}}
            self._scene_order.append(instance)
        self.current_scene_id = scene
        self.current_scene_instance_id = instance
        for beat in restored_beats:
            bid = _text(beat)
            if bid:
                self.complete(
                    bid,
                    source_kind=source_kind,
                    source_ref=source_ref,
                    turn=turn,
                )

    def complete(
        self,
        beat_id: str,
        *,
        source_kind: str,
        source_ref: str,
        turn: int,
    ) -> bool:
        beat = _text(beat_id)
        kind = _text(source_kind)
        ref = _text(source_ref)
        if not beat or not kind or not ref:
            raise ValueError("beat completion requires beat/source_kind/source_ref")
        if int(turn) < 0:
            raise ValueError("beat completion turn must be >=0")
        visit = self._visits[self.current_scene_instance_id]
        receipts: dict[str, BeatReceipt] = visit["receipts"]
        if beat in receipts:
            return False
        payload = {
            "scene_id": self.current_scene_id,
            "scene_instance_id": self.current_scene_instance_id,
            "beat_id": beat,
            "source_kind": kind,
            "source_ref": ref,
            "turn": int(turn),
        }
        receipt = BeatReceipt(
            receipt_id=f"beat:{canonical_payload_hash(payload)}",
            scene_id=self.current_scene_id,
            scene_instance_id=self.current_scene_instance_id,
            beat_id=beat,
            source_kind=kind,
            source_ref=ref,
            turn=int(turn),
        )
        receipts[beat] = receipt
        return True

    def completed(self) -> list[str]:
        visit = self._visits[self.current_scene_instance_id]
        return list(visit["receipts"].keys())

    def receipts(self) -> list[dict[str, Any]]:
        visit = self._visits[self.current_scene_instance_id]
        return [receipt.to_dict() for receipt in visit["receipts"].values()]

    def completed_by_card(self) -> dict[str, list[str]]:
        latest: dict[str, list[str]] = {}
        for instance in self._scene_order:
            visit = self._visits.get(instance)
            if not visit:
                continue
            latest[str(visit["scene_id"])] = list(visit["receipts"].keys())
        return latest
