"""P2c BeatReducer event ledger and projections."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

BEAT_EVENT_SCHEMA = "free_stage.beat_event.v1"


class BeatConflict(ValueError):
    pass


@dataclass(frozen=True)
class BeatCommitResult:
    record: dict[str, Any]
    committed: bool


def _text(value: Any) -> str:
    return str(value or "").strip()


def scene_instance_id(scene_id: str, visit: int) -> str:
    sid = _text(scene_id)
    visit_no = int(visit)
    if not sid or visit_no < 1:
        raise ValueError("scene instance requires scene_id and visit>=1")
    return f"{sid}:visit:{visit_no}"


def visit_from_instance(scene_id: str, instance_id: str) -> int:
    sid = _text(scene_id)
    raw = _text(instance_id)
    prefix = f"{sid}:visit:"
    if not sid or not raw.startswith(prefix):
        raise ValueError(f"scene instance mismatch: {raw}")
    visit = int(raw[len(prefix):])
    if visit < 1:
        raise ValueError("scene visit must be >=1")
    return visit


def commit_completion(
    ledger: MutableMapping[str, dict[str, Any]],
    *,
    scene_id: str,
    scene_instance_id: str,
    beat_id: str,
    turn: int,
    source_kind: str,
    source_ref: str = "",
    legacy: bool = False,
) -> BeatCommitResult:
    sid = _text(scene_id)
    instance = _text(scene_instance_id)
    beat = _text(beat_id)
    if not sid or not instance or not beat:
        raise ValueError("beat completion requires scene/instance/beat")
    visit_from_instance(sid, instance)
    event_id = f"beat-complete:{instance}:{beat}"
    existing = ledger.get(event_id)
    if existing is not None:
        if (
            _text(existing.get("scene_id")) != sid
            or _text(existing.get("scene_instance_id")) != instance
            or _text(existing.get("beat_id")) != beat
        ):
            raise BeatConflict(f"beat event id reused with different fact: {event_id}")
        return BeatCommitResult(dict(existing), False)
    record = {
        "schema_version": BEAT_EVENT_SCHEMA,
        "event_id": event_id,
        "kind": "complete",
        "scene_id": sid,
        "scene_instance_id": instance,
        "beat_id": beat,
        "turn": int(turn),
        "source_kind": _text(source_kind) or "unknown",
        "source_ref": _text(source_ref),
        "legacy": bool(legacy),
    }
    ledger[event_id] = record
    return BeatCommitResult(dict(record), True)


def project_completed(
    ledger: Mapping[str, Mapping[str, Any]],
    scene_instance_id_value: str,
) -> list[str]:
    instance = _text(scene_instance_id_value)
    out: list[str] = []
    seen: set[str] = set()
    for row in ledger.values():
        if _text(row.get("scene_instance_id")) != instance:
            continue
        if _text(row.get("kind")) != "complete":
            continue
        beat = _text(row.get("beat_id"))
        if beat and beat not in seen:
            seen.add(beat)
            out.append(beat)
    return out


def project_completed_by_card(
    ledger: Mapping[str, Mapping[str, Any]],
    scene_visits: Mapping[str, int],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for scene_id, visit in scene_visits.items():
        sid = _text(scene_id)
        if not sid or int(visit or 0) < 1:
            continue
        beats = project_completed(ledger, scene_instance_id(sid, int(visit)))
        if beats:
            out[sid] = beats
    return out


def migrate_legacy(
    *,
    current_scene_id: str,
    card_history: Sequence[str],
    completed: Sequence[str],
    completed_by_card: Mapping[str, Sequence[str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int], str]:
    """Migrate old projections without inventing player evidence."""
    visits: dict[str, int] = {}
    for raw in card_history:
        sid = _text(raw)
        if sid:
            visits[sid] = visits.get(sid, 0) + 1
    current = _text(current_scene_id)
    if not current:
        raise ValueError("legacy beat migration requires current scene")
    if current not in visits:
        visits[current] = 1

    ledger: dict[str, dict[str, Any]] = {}
    current_visit = max(1, visits[current])

    for raw_scene, raw_beats in completed_by_card.items():
        sid = _text(raw_scene)
        if not sid:
            continue
        visit = max(1, visits.get(sid, 1))
        if sid == current and visit > 1:
            visit -= 1
        instance = scene_instance_id(sid, visit)
        for beat in raw_beats or ():
            beat_text = _text(beat)
            if beat_text:
                commit_completion(
                    ledger,
                    scene_id=sid,
                    scene_instance_id=instance,
                    beat_id=beat_text,
                    turn=0,
                    source_kind="legacy_snapshot",
                    source_ref="completed_by_card",
                    legacy=True,
                )

    current_instance = scene_instance_id(current, current_visit)
    for beat in completed or ():
        beat_text = _text(beat)
        if beat_text:
            commit_completion(
                ledger,
                scene_id=current,
                scene_instance_id=current_instance,
                beat_id=beat_text,
                turn=0,
                source_kind="legacy_snapshot",
                source_ref="completed",
                legacy=True,
            )
    return ledger, visits, current_instance
