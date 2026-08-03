"""Director-only time × place projection derived from existing runtime receipts."""
from __future__ import annotations

from typing import Any, Mapping


_BUCKET_LANE = {"past": -1, "overlapping": 0, "near": 1, "unknown": 2}


def _scene_points(world_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, fallback in (("live_scene", "overlapping"), ("near_offscreen", "near"), ("past_same_chapter", "past")):
        for item in world_state.get(source, ()) or ():
            if not isinstance(item, Mapping):
                continue
            relation = str(item.get("relation_to_current", fallback) or fallback)
            rows.append({
                "kind": "world_scene",
                "time_lane": _BUCKET_LANE.get(relation, _BUCKET_LANE["unknown"]),
                "relation": relation,
                "location": str(item.get("location") or item.get("scene_uid") or "未知地点"),
                "natural_time_window": str(item.get("natural_time_window") or "时段待定"),
                "event_uids": [str(value) for value in item.get("event_uids", ()) if str(value)],
            })
    return rows


def project_world_coordinates(
    *,
    world_state: Mapping[str, Any] | None,
    world_cursor: Mapping[str, Any] | None,
    current_location: str,
    intent_runtime: Mapping[str, Any] | None,
    ambient_actor_registry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Render a small map without becoming a second world-state authority."""
    state = dict(world_state or {})
    cursor = dict(world_cursor or {})
    runtime = dict(intent_runtime or {})
    threads = [dict(item) for item in runtime.get("threads", ()) if isinstance(item, Mapping)]
    storylets = [dict(item) for item in runtime.get("storylets", ()) if isinstance(item, Mapping)]
    decisions = [dict(item) for item in runtime.get("committed_actor_decisions", ()) if isinstance(item, Mapping)]
    intent_points = []
    for item in threads:
        event = str(item.get("event", "") or "opened")
        intent_points.append({
            "intent_id": str(item.get("intent_id", "")), "event": event,
            "target": str(item.get("target") or item.get("actor_cons") or ""),
            "outcome": str(item.get("outcome", "")),
            "turn": item.get("turn"),
        })
    for item in decisions:
        intent_points.append({
            "intent_id": str(item.get("intent_id", "")), "event": "actor_decided",
            "target": str(item.get("actor_cons", "")), "outcome": str(item.get("outcome", "")),
            "turn": None,
        })
    ambient_points = []
    for raw in (ambient_actor_registry or {}).values():
        if not isinstance(raw, Mapping) or raw.get("status") != "established":
            continue
        ambient_points.append({
            "actor_id": str(raw.get("actor_id", "")),
            "public_role": str(raw.get("public_role", "环境角色")),
            "status": "established",
        })
    return {
        "axes": {"x": "world_time", "y": "physical_location"},
        "cursor": {
            "worldline": str(cursor.get("worldline", "WMAIN")),
            "run": cursor.get("run"),
            "world_clock": str(cursor.get("world_clock") or cursor.get("clock") or "未知时刻"),
            "current_location": str(current_location or "未知地点"),
        },
        "scene_points": _scene_points(state),
        "intent_points": intent_points,
        "storylet_ids": [str(item.get("storylet_id", "")) for item in storylets if item.get("storylet_id")],
        "ambient_points": ambient_points,
        "projection_note": "仅为导演/观测台投影；不反向进入玩家页或 actor packet。",
    }
