"""P2c BeatReducer: the single owner of must-happen completion state.

FreeStageSession exposes completed/completed_by_card as read-only compatibility
projections. Business code submits already-validated beat completion events to
this reducer; legacy snapshots migrate once with an explicit legacy source.
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from runtime.causal_protocol import ReceiptEnvelope, RuntimeScope, canonical_payload_hash

BEAT_STATE_SCHEMA = "free_stage.beat_state.v1"
BEAT_RECEIPT_SCHEMA = "free_stage.beat_receipt.v1"


@dataclass(frozen=True)
class BeatCommitResult:
    newly_completed: tuple[str, ...]
    receipt_ids: tuple[str, ...]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _instance_id(scene_id: str, visit: int) -> str:
    return f"{scene_id}:visit:{int(visit)}"


class BeatReducer:
    def __init__(self, state: Mapping[str, Any]) -> None:
        self._state = copy.deepcopy(dict(state))
        self._validate()

    @classmethod
    def new(cls, scene_id: str) -> "BeatReducer":
        sid = _text(scene_id)
        if not sid:
            raise ValueError("BeatReducer requires scene_id")
        instance = _instance_id(sid, 1)
        return cls({
            "schema_version": BEAT_STATE_SCHEMA,
            "active_scene_id": sid,
            "active_scene_instance_id": instance,
            "visit_counts": {sid: 1},
            "scene_instances": {instance: sid},
            "receipts": [],
            "migration": None,
        })

    @classmethod
    def from_session_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        current_scene_id: str,
        card_history: Sequence[str],
        worldline: str,
        run: int,
        ch_anchor: int,
        session_id: str,
    ) -> "BeatReducer":
        raw = payload.get("beat_state")
        if isinstance(raw, Mapping):
            return cls(raw)

        # v1 legacy migration: preserve what old completed fields claimed, but
        # mark it as migration evidence. Never fabricate a player action.
        sid = _text(current_scene_id)
        history = [_text(item) for item in card_history if _text(item)]
        if sid not in history:
            history.append(sid)
        counts = Counter(history)
        visit_counts = {scene: max(1, int(count)) for scene, count in counts.items()}
        scene_instances: dict[str, str] = {}
        for scene, count in visit_counts.items():
            for visit in range(1, count + 1):
                scene_instances[_instance_id(scene, visit)] = scene
        active_instance = _instance_id(sid, visit_counts.get(sid, 1))
        state = {
            "schema_version": BEAT_STATE_SCHEMA,
            "active_scene_id": sid,
            "active_scene_instance_id": active_instance,
            "visit_counts": visit_counts,
            "scene_instances": scene_instances,
            "receipts": [],
            "migration": {
                "source_schema": str(payload.get("schema_version") or "unknown"),
                "source_fields": ["completed", "completed_by_card"],
                "mode": "legacy_snapshot_no_player_receipt",
            },
        }
        reducer = cls(state)

        legacy_by_card = payload.get("completed_by_card")
        if isinstance(legacy_by_card, Mapping):
            for scene, beats in legacy_by_card.items():
                scene_text = _text(scene)
                if not scene_text or not isinstance(beats, list):
                    continue
                instance = reducer.latest_instance_for_scene(scene_text)
                if instance is None:
                    reducer.enter_scene(scene_text)
                    instance = reducer.active_scene_instance_id
                reducer._complete_legacy(
                    scene_id=scene_text,
                    scene_instance_id=instance,
                    beat_ids=[_text(item) for item in beats if _text(item)],
                    worldline=worldline,
                    run=run,
                    ch_anchor=ch_anchor,
                    session_id=session_id,
                    source_field="completed_by_card",
                )

        current = payload.get("completed")
        if isinstance(current, list):
            reducer._complete_legacy(
                scene_id=sid,
                scene_instance_id=active_instance,
                beat_ids=[_text(item) for item in current if _text(item)],
                worldline=worldline,
                run=run,
                ch_anchor=ch_anchor,
                session_id=session_id,
                source_field="completed",
            )
        reducer.resume_scene(sid, active_instance)
        return reducer

    def _validate(self) -> None:
        if self._state.get("schema_version") != BEAT_STATE_SCHEMA:
            raise ValueError("unsupported beat state schema")
        sid = _text(self._state.get("active_scene_id"))
        instance = _text(self._state.get("active_scene_instance_id"))
        if not sid or not instance:
            raise ValueError("beat state requires active scene/instance")
        instances = self._state.get("scene_instances")
        if not isinstance(instances, dict) or _text(instances.get(instance)) != sid:
            raise ValueError("beat active instance does not belong to active scene")
        visits = self._state.get("visit_counts")
        if not isinstance(visits, dict):
            raise ValueError("beat state visit_counts must be object")
        receipts = self._state.get("receipts")
        if not isinstance(receipts, list):
            raise ValueError("beat state receipts must be list")

    @property
    def active_scene_id(self) -> str:
        return _text(self._state["active_scene_id"])

    @property
    def active_scene_instance_id(self) -> str:
        return _text(self._state["active_scene_instance_id"])

    @property
    def completed(self) -> list[str]:
        return self.completed_for_instance(self.active_scene_instance_id)

    @property
    def completed_by_card(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        scenes = {
            _text(scene)
            for scene in dict(self._state.get("scene_instances") or {}).values()
            if _text(scene)
        }
        for scene in sorted(scenes):
            instance = self.latest_instance_for_scene(scene)
            if instance:
                out[scene] = self.completed_for_instance(instance)
        return out

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def latest_instance_for_scene(self, scene_id: str) -> str | None:
        sid = _text(scene_id)
        instances = [
            instance
            for instance, scene in dict(self._state.get("scene_instances") or {}).items()
            if _text(scene) == sid
        ]
        if not instances:
            return None
        def visit_no(instance: str) -> int:
            marker = ":visit:"
            if marker not in instance:
                return 0
            try:
                return int(instance.rsplit(marker, 1)[1])
            except (TypeError, ValueError):
                return 0
        return max(instances, key=visit_no)

    def completed_for_instance(self, scene_instance_id: str) -> list[str]:
        iid = _text(scene_instance_id)
        result: list[str] = []
        seen: set[str] = set()
        for row in self._state.get("receipts") or []:
            if not isinstance(row, Mapping) or _text(row.get("scene_instance_id")) != iid:
                continue
            beat = _text(row.get("beat_id"))
            if beat and beat not in seen:
                seen.add(beat)
                result.append(beat)
        return result

    def enter_scene(self, scene_id: str) -> str:
        sid = _text(scene_id)
        if not sid:
            raise ValueError("enter_scene requires scene_id")
        visits = dict(self._state.get("visit_counts") or {})
        visit = int(visits.get(sid, 0) or 0) + 1
        visits[sid] = visit
        instance = _instance_id(sid, visit)
        instances = dict(self._state.get("scene_instances") or {})
        instances[instance] = sid
        self._state["visit_counts"] = visits
        self._state["scene_instances"] = instances
        self._state["active_scene_id"] = sid
        self._state["active_scene_instance_id"] = instance
        return instance

    def resume_scene(self, scene_id: str, scene_instance_id: str | None = None) -> str:
        sid = _text(scene_id)
        instance = _text(scene_instance_id)
        if not instance:
            instance = self.latest_instance_for_scene(sid) or ""
        instances = dict(self._state.get("scene_instances") or {})
        if not instance or _text(instances.get(instance)) != sid:
            raise ValueError(f"unknown beat scene instance for resume: {sid} / {instance}")
        self._state["active_scene_id"] = sid
        self._state["active_scene_instance_id"] = instance
        return instance

    def reset(self, scene_id: str) -> None:
        fresh = BeatReducer.new(scene_id)
        self._state = fresh.to_dict()

    def complete(
        self,
        *,
        scope: RuntimeScope,
        beat_ids: Sequence[str],
        turn: int,
        source_kind: str,
        request_id: str,
        source_refs: Sequence[str] = (),
    ) -> BeatCommitResult:
        if scope.scene_instance_id != self.active_scene_instance_id:
            raise ValueError("beat scope does not match active scene instance")
        if int(scope.run) < 1:
            raise ValueError("beat completion requires run>=1")
        kind = _text(source_kind)
        req = _text(request_id)
        if not kind or not req:
            raise ValueError("beat completion requires source_kind/request_id")

        existing = set(self.completed)
        receipts = list(self._state.get("receipts") or [])
        newly: list[str] = []
        receipt_ids: list[str] = []
        for sequence, raw in enumerate(beat_ids):
            beat = _text(raw)
            if not beat or beat in existing:
                continue
            payload = {
                "scene_id": self.active_scene_id,
                "scene_instance_id": self.active_scene_instance_id,
                "beat_id": beat,
                "turn": int(turn),
                "source_kind": kind,
            }
            receipt = ReceiptEnvelope.for_payload(
                receipt_id=f"beat:{canonical_payload_hash({'scope': scope.to_dict(), 'beat_id': beat})}",
                request_id=req,
                turn_id=f"turn:{int(turn)}",
                sequence=sequence,
                scope=scope,
                producer="BeatReducer",
                source_refs=tuple(_text(item) for item in source_refs if _text(item)),
                visibility="system",
                base_revision=0,
                payload=payload,
            )
            receipts.append({
                "schema_version": BEAT_RECEIPT_SCHEMA,
                **payload,
                "receipt": receipt.to_dict(),
            })
            existing.add(beat)
            newly.append(beat)
            receipt_ids.append(receipt.receipt_id)
        self._state["receipts"] = receipts
        return BeatCommitResult(tuple(newly), tuple(receipt_ids))

    def _complete_legacy(
        self,
        *,
        scene_id: str,
        scene_instance_id: str,
        beat_ids: Sequence[str],
        worldline: str,
        run: int,
        ch_anchor: int,
        session_id: str,
        source_field: str,
    ) -> None:
        current_active = (self.active_scene_id, self.active_scene_instance_id)
        self.resume_scene(scene_id, scene_instance_id)
        scope = RuntimeScope(
            worldline=_text(worldline) or "WMAIN",
            run=max(1, int(run)),
            ch_anchor=max(0, int(ch_anchor)),
            session_id=_text(session_id) or "legacy-session",
            scene_instance_id=scene_instance_id,
        )
        self.complete(
            scope=scope,
            beat_ids=beat_ids,
            turn=0,
            source_kind="legacy_snapshot",
            request_id=f"beat-migration:{_text(session_id) or 'legacy-session'}:{source_field}:{scene_instance_id}",
            source_refs=(f"legacy:{source_field}",),
        )
        self.resume_scene(*current_active)
