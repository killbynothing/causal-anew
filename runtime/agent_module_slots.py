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
    self_core = packet.get("self_core") if isinstance(packet.get("self_core"), dict) else {}
    persona = packet.get("persona") if isinstance(packet.get("persona"), dict) else {}
    self_state = packet.get("self_state") if isinstance(packet.get("self_state"), dict) else {}
    inner_state = self_state.get("inner_state") if isinstance(self_state.get("inner_state"), dict) else {}

    manner = (
        self_core.get("seed_manners")
        or self_core.get("manner")
        or persona.get("manner")
        or packet.get("manner")
        or packet.get("voice_rule")
    )
    self_memory = packet.get("self_memory") if isinstance(packet.get("self_memory"), dict) else {}
    mem_act = packet.get("memory_activation") if isinstance(packet.get("memory_activation"), dict) else {}
    slow = (
        self_memory.get("slow_memory")
        or self_memory.get("slow_memory_activated")
        or mem_act.get("slow_memory_activated")
        or []
    )
    episodic = (
        self_memory.get("episodic_recent")
        or self_memory.get("episodic_memory")
        or packet.get("episodic_memory")
        or packet.get("memory_context")
        or []
    )
    rel_mem = self_memory.get("relationship_memory") or []
    knowledge = packet.get("relevant_knowledge_top_k") or packet.get("knowledge_activated") or []

    if isinstance(data.get("structured_memories"), dict):
        n_struct = sum(len(v) for v in data["structured_memories"].values() if isinstance(v, list))
    else:
        n_struct = 0
    n_mem = (
        (len(slow) if isinstance(slow, list) else 0)
        + (len(episodic) if isinstance(episodic, list) else 0)
        + (len(rel_mem) if isinstance(rel_mem, list) else 0)
        + (len(knowledge) if isinstance(knowledge, list) else 0)
        + n_struct
    )

    mem_bits: list[str] = []
    if slow and isinstance(slow, list):
        mem_bits.append(f"慢环×{len(slow)}")
    if episodic and isinstance(episodic, list):
        mem_bits.append(f"情景×{len(episodic)}")
    if rel_mem and isinstance(rel_mem, list):
        mem_bits.append(f"关系×{len(rel_mem)}")
    if knowledge and isinstance(knowledge, list):
        mem_bits.append(f"正典K×{len(knowledge)}")
    if n_struct:
        mem_bits.append(f"结构×{n_struct}")
    mem_summary = " · ".join(mem_bits) if mem_bits else (f"激活 {n_mem} 条" if n_mem else "—")

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

    contract = packet.get("conversation_contract") if isinstance(packet.get("conversation_contract"), dict) else {}
    slot_mode = str(contract.get("response_slot") or "").strip()
    part_mode = str(contract.get("participation_mode") or "").strip()
    pacing_signal = cog.get("pacing_signal") if isinstance(cog.get("pacing_signal"), dict) else {}
    if slot_mode or part_mode:
        tool_bits = [f"slot={slot_mode or 'primary'}", f"mode={part_mode or 'speak'}"]
        if pacing_signal.get("mode"):
            tool_bits.append(f"pace={pacing_signal.get('mode')}")
        if last_kind and last_kind != "quiet":
            tool_bits.append(last_kind)
        tool_summary = " · ".join(tool_bits)

    spoken = packet.get("spoken_this_turn") or []
    action_text = ""
    if isinstance(spoken, list) and spoken:
        first_spk = spoken[0]
        if isinstance(first_spk, dict):
            t = str(first_spk.get("text") or "")
            st = str(first_spk.get("stage") or "")
            action_text = f"{t} 〔stage: {st}〕" if st else t
        else:
            action_text = str(first_spk)
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
    char_name = self_core.get("name") or persona.get("name") or packet.get("name")
    if char_name:
        persona_bits.append(str(char_name))
    boundaries = self_core.get("seed_boundaries") or []
    voice_samples = self_core.get("voice_samples") or []
    if isinstance(manner, list) and manner:
        persona_bits.append(f"MANNER×{len(manner)}")
    elif manner:
        persona_bits.append(str(manner)[:30])
    if isinstance(boundaries, list) and boundaries:
        persona_bits.append(f"BOUNDARY×{len(boundaries)}")
    if isinstance(voice_samples, list) and voice_samples:
        persona_bits.append(f"VOICE×{len(voice_samples)}")
    identity = packet.get("identity_relations") or []
    if isinstance(identity, list) and identity:
        persona_bits.append(f"REL×{len(identity)}")
    if not persona_bits:
        for key in ("voice_rule", "core"):
            val = persona.get(key) or packet.get(key)
            if val:
                persona_bits.append(str(val)[:40])

    mh = data.get("must_happen_progress") if isinstance(data.get("must_happen_progress"), dict) else {}
    completed = mh.get("completed") or data.get("completed") or []
    cursor = data.get("world_cursor") if isinstance(data.get("world_cursor"), dict) else {}
    state_bits = [
        f"run={cursor.get('run', '—')}",
        f"ch={cursor.get('ch_anchor', '—')}",
        f"MH={','.join(str(x) for x in completed) or 'none'}",
    ]
    actor_states = data.get("actor_state") if isinstance(data.get("actor_state"), dict) else {}
    actor_state = actor_states.get(cons) if isinstance(actor_states.get(cons), dict) else {}
    persistent = actor_state.get("persistent") if isinstance(actor_state.get("persistent"), dict) else {}
    if actor_state.get("authority"):
        state_bits.insert(0, f"mind={actor_state.get('authority')}")
        state_bits.append(f"receipts={persistent.get('receipt_count', 0)}")
    pacing = cog.get("pacing_signal") if isinstance(cog.get("pacing_signal"), dict) else {}
    if pacing.get("mode"):
        state_bits.append(f"pace={pacing.get('mode')}")
    sediment = data.get("physical_state") if isinstance(data.get("physical_state"), dict) else {}
    if sediment.get("sediment_S") is not None:
        state_bits.append(f"S={sediment.get('sediment_S')}")
    bf = packet.get("body_frame_now") or self_state.get("body_frame_now") or {}
    if isinstance(bf, dict) and bf.get("holding"):
        state_bits.append(f"持物={bf.get('holding')}")

    plan_concern = (
        decide.get("top_concern")
        or decide.get("intention")
        or inner_state.get("want_now")
        or inner_state.get("top_concern")
        or ""
    )
    plan_band = str(decide.get("band") or "").strip()
    plan_summary = f"[{plan_band}] {plan_concern}" if plan_band and plan_concern else (plan_concern or "—")

    slots = {
        "Planning": _slot(
            bool(plan_concern),
            _clip(plan_summary),
            "cog_loop.decide / self_state.inner_state",
        ),
        "Memory": _slot(
            n_mem > 0,
            _clip(mem_summary),
            "self_memory / relevant_knowledge / structured_memories",
        ),
        "Tool Use": _slot(
            bool(last_kind and last_kind != "quiet") or bool(traces) or bool(slot_mode),
            _clip(tool_summary),
            "conversation_contract / director_port_trace",
        ),
        "Action": _slot(
            bool(action_text),
            _clip(action_text) if action_text else "—",
            "spoken_this_turn",
        ),
        "Reflection": _slot(
            bool(reflect_text),
            _clip(reflect_text) if reflect_text else "—",
            "cog_loop.reflect / private_reflections",
        ),
        "Persona": _slot(
            bool(persona_bits),
            _clip(" · ".join(persona_bits) if persona_bits else (cons or "—")),
            "self_core / actor packet",
        ),
        "State Tracking": _slot(
            True,
            _clip(" · ".join(state_bits)),
            "actor_state / world_cursor / must_happen_progress",
        ),
    }
    for key, row in slots.items():
        row["label"] = SLOT_LABELS[key]
        row["key"] = key
    return slots
