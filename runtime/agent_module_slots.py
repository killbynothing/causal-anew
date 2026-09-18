"""Project debug_payload onto the seven JD Agent module slots.

Read-only. Does not change Decide / Enact / Reflect or the director contract.
"""
from __future__ import annotations

from typing import Any, Mapping

SLOT_KEYS: tuple[str, ...] = (
    "Planning",
    "Memory",
    "Tool Use",
    "Action",
    "Reflection",
    "Persona",
    "State Tracking",
)

SLOT_LABELS: dict[str, str] = {
    "Planning": "规划",
    "Memory": "记忆",
    "Tool Use": "工具",
    "Action": "行动",
    "Reflection": "反思",
    "Persona": "人格",
    "State Tracking": "状态",
}


def _first_packet(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    packets = payload.get("actor_context_packets") or {}
    if not isinstance(packets, dict) or not packets:
        return "", {}
    for cons, pkt in packets.items():
        if isinstance(pkt, dict) and "ryuya" in str(cons):
            return str(cons), pkt
    cons = next(iter(packets))
    pkt = packets[cons]
    return str(cons), pkt if isinstance(pkt, dict) else {}


def _clip(text: Any, n: int = 80) -> str:
    s = re_sub_ws(str(text or "").strip())
    return s[:n] + ("…" if len(s) > n else "")


def re_sub_ws(s: str) -> str:
    return " ".join(s.split())


def _slot(filled: bool, summary: str, source: str = "") -> dict[str, Any]:
    return {
        "label": "",
        "filled": bool(filled),
        "summary": summary or "—",
        "source": source,
    }


def project_agent_modules(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return seven slots, always keyed, never raises."""
    data = dict(payload or {})
    cons, packet = _first_packet(data)
    cog = packet.get("cog_loop") if isinstance(packet.get("cog_loop"), dict) else {}
    decide = cog.get("decide") if isinstance(cog.get("decide"), dict) else {}
    reflect = cog.get("reflect") if isinstance(cog.get("reflect"), dict) else {}
    persona = packet.get("persona") if isinstance(packet.get("persona"), dict) else {}
    manner = packet.get("manner") or persona.get("manner") or packet.get("voice_rule")
    mem_act = packet.get("memory_activation") if isinstance(packet.get("memory_activation"), dict) else {}
    slow = mem_act.get("slow_memory_activated") or []
    episodic = packet.get("episodic_memory") or packet.get("memory_context") or []
    if isinstance(data.get("structured_memories"), dict):
        n_struct = sum(len(v) for v in data["structured_memories"].values() if isinstance(v, list))
    else:
        n_struct = 0
    n_mem = (len(slow) if isinstance(slow, list) else 0) + (
        len(episodic) if isinstance(episodic, list) else 0
    ) + n_struct

    traces = data.get("director_port_trace") or []
    last_kind = ""
    if isinstance(traces, list):
        for row in reversed(traces):
            if isinstance(row, dict):
                last_kind = str(row.get("opportunity_kind") or row.get("kind") or "").strip()
                if last_kind:
                    break
    opp = data.get("opportunity") if isinstance(data.get("opportunity"), dict) else {}
    if not last_kind:
        last_kind = str(opp.get("kind") or "").strip()
    legal = data.get("legal_moves")
    tool_summary = last_kind or "quiet"
    if isinstance(legal, list) and last_kind:
        tool_summary = f"{last_kind} · legal={last_kind in legal}"

    spoken = packet.get("spoken_this_turn") or []
    action_text = ""
    if isinstance(spoken, list) and spoken:
        action_text = str(spoken[0].get("text") or "") if isinstance(spoken[0], dict) else str(spoken[0])
    if not action_text:
        vis = data.get("player_visible_turns") or []
        for row in reversed(list(vis) if isinstance(vis, list) else []):
            if isinstance(row, dict) and str(row.get("role") or "") == "npc":
                action_text = str(row.get("text") or "")
                break

    reflections = data.get("private_reflections") or []
    reflect_text = ""
    if isinstance(reflect, dict) and reflect.get("thought"):
        reflect_text = str(reflect.get("thought"))
    elif isinstance(reflections, list) and reflections:
        last = reflections[-1]
        if isinstance(last, dict):
            reflect_text = str(last.get("thought") or "")

    persona_bits = []
    for key in ("name", "voice_rule", "core"):
        val = persona.get(key) or packet.get(key)
        if val:
            persona_bits.append(str(val)[:40])
    if manner:
        persona_bits.append(str(manner)[:40])
    identity = packet.get("identity_relations") or []
    if isinstance(identity, list) and identity:
        persona_bits.append(f"REL×{len(identity)}")

    mh = data.get("must_happen_progress") if isinstance(data.get("must_happen_progress"), dict) else {}
    completed = mh.get("completed") or data.get("completed") or []
    cursor = data.get("world_cursor") if isinstance(data.get("world_cursor"), dict) else {}
    state_bits = [
        f"run={cursor.get('run', '—')}",
        f"ch={cursor.get('ch_anchor', '—')}",
        f"MH={','.join(str(x) for x in completed) or 'none'}",
    ]
    sediment = data.get("physical_state") if isinstance(data.get("physical_state"), dict) else {}
    if sediment.get("sediment_S") is not None:
        state_bits.append(f"S={sediment.get('sediment_S')}")

    slots = {
        "Planning": _slot(
            bool(decide.get("top_concern") or decide.get("intention")),
            _clip(decide.get("top_concern") or decide.get("intention") or "—"),
            "cog_loop.decide",
        ),
        "Memory": _slot(
            n_mem > 0,
            f"激活 {n_mem} 条" if n_mem else "—",
            "memory_activation / structured_memories",
        ),
        "Tool Use": _slot(
            bool(last_kind and last_kind != "quiet") or bool(traces),
            _clip(tool_summary),
            "director_port_trace",
        ),
        "Action": _slot(
            bool(action_text),
            _clip(action_text) if action_text else "—",
            "spoken_this_turn",
        ),
        "Reflection": _slot(
            bool(reflect_text),
            _clip(reflect_text) if reflect_text else "—",
            "private_reflections",
        ),
        "Persona": _slot(
            bool(persona_bits),
            _clip(" / ".join(persona_bits) if persona_bits else (cons or "—")),
            "actor packet",
        ),
        "State Tracking": _slot(
            True,
            _clip(" · ".join(state_bits)),
            "world_cursor / must_happen_progress",
        ),
    }
    for key, row in slots.items():
        row["label"] = SLOT_LABELS[key]
        row["key"] = key
    return slots
