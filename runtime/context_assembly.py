"""P5 authoritative actor-context assembly.

This module owns retrieval sequencing, context layering, actor prompt projection
and the assembly receipt. FreeStage may supply scene-specific hooks, but it no
longer fetches or recomposes actor context in parallel.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from runtime import actor_context_v2 as acv2
from runtime import opening_top_tier as ott
from runtime import view_projection
from runtime.actor_mind import build_actor_mind


SCHEMA_VERSION = "free_stage.context_assembly.v2"


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AssemblyHooks:
    player_guide_scene_frame_keys: Sequence[str]
    prologue_friend_known_keys: Sequence[str]
    build_visible_holding_map: Callable[..., Any]
    extract_object_use_memory: Callable[..., Any]
    build_verbatim_field_window: Callable[..., Any]
    select_situation_facets: Callable[..., Any]
    prologue_friend_known_profile: Callable[..., Any]
    observable_player_for_actor: Callable[..., Any]
    merge_identity_relations: Callable[..., Any]
    normalize_card_identity_relations: Callable[..., Any]
    ensure_card_body_frames: Callable[..., Any]
    body_frame_for_cons: Callable[..., Any]
    activate_scene_episode_candidates: Callable[..., Any]
    c16_subtle_peripheral_watch: Callable[..., Any]
    activate_keyed_lorebook: Callable[..., Any]


def actor_prompt_projection(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Strip observatory-only candidate/withheld material before actor transport."""
    prompt_packet = copy.deepcopy(dict(packet))
    for key in ("memory_activation", "knowledge_candidates"):
        prompt_packet.pop(key, None)
    self_memory = prompt_packet.get("self_memory")
    if isinstance(self_memory, dict):
        self_memory.pop("slow_memory_candidates", None)
    return prompt_packet


def _layers(packet: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    memory = packet.get("self_memory") if isinstance(packet.get("self_memory"), Mapping) else {}
    return {
        "stable_identity": {
            "actor_cons": packet.get("actor_cons"),
            "self_core": packet.get("self_core", {}),
            "disclosure_policy": packet.get("disclosure_policy", {}),
        },
        "authoritative_present": {
            "scene": packet.get("scene"),
            "world_cursor": packet.get("world_cursor", {}),
            "physical_scene": packet.get("physical_scene", {}),
            "self_state": packet.get("self_state", {}),
            "body_frame_now": packet.get("body_frame_now", {}),
            "world_signals": packet.get("world_signals", []),
        },
        "scene_window": {
            "observable_player": packet.get("observable_player", {}),
            "observable_dialogue": packet.get("observable_dialogue", []),
            "private_perceptions": packet.get("private_perceptions", []),
        },
        "goal_conditioned_memory": {
            "scene_working_memory": memory.get("scene_working_memory", {}),
            "episodic_recent": memory.get("episodic_recent", []),
            "slow_memory_top_k": memory.get("slow_memory_top_k", []),
            "relevant_knowledge_top_k": packet.get("relevant_knowledge_top_k", []),
            "identity_relations": packet.get("identity_relations", []),
            "interaction_dynamics": packet.get("interaction_dynamics", []),
        },
        "scene_overlay": {
            "conversation_contract": packet.get("conversation_contract", {}),
            "decision_request": packet.get("decision_request", {}),
            "cog_loop": packet.get("cog_loop", {}),
            "director_instruction": packet.get("director_instruction", {}),
        },
    }


def finalize_actor_context(packet: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Finalize the exact actor-visible packet and sign a source-safe receipt."""
    prompt_packet = actor_prompt_projection(packet)
    layers = _layers(prompt_packet)
    memory = layers["goal_conditioned_memory"]
    source_trace = (
        prompt_packet.get("source_trace")
        if isinstance(prompt_packet.get("source_trace"), list)
        else []
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "enforcement": "authoritative",
        "actor_cons": str(prompt_packet.get("actor_cons") or ""),
        "scene": str(prompt_packet.get("scene") or ""),
        "turn": int(prompt_packet.get("turn") or 0),
        "prompt_sha256": _digest(prompt_packet),
        "layers": {
            name: {
                "chars": _size(value),
                "sha256": _digest(value),
            }
            for name, value in layers.items()
        },
        "memory": {
            "slow_memory_activated": len(memory.get("slow_memory_top_k") or []),
            "knowledge_activated": len(memory.get("relevant_knowledge_top_k") or []),
            "episodes_activated": len(memory.get("episodic_recent") or []),
        },
        "sources": {
            "trace_count": len(source_trace),
            "trace_sha256": _digest(source_trace),
        },
    }
    return prompt_packet, receipt


def assemble_actor_context(prompt_packet: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compatibility name: finalization is now authoritative rather than observe-only."""
    return finalize_actor_context(prompt_packet)



def build_actor_context_draft(
    card: dict[str, Any],
    actor_cons: str,
    history: list[dict[str, Any]],
    player_input: dict[str, Any] | None,
    turn_no: int,
    world_cursor: dict[str, Any] | None,
    runtime_inner_state: dict[str, Any] | None = None,
    actor_mind: dict[str, Any] | None = None,
    player_profile: dict[str, Any] | None = None,
    *,
    hooks: AssemblyHooks,
) -> dict[str, Any]:
    """Build per-consciousness actor projection (v2): full life-scene + shared core + Top-K memory."""
    persona_cards = card.get("persona_cards") if isinstance(card.get("persona_cards"), dict) else {}
    persona = persona_cards.get(actor_cons)
    if not isinstance(persona, dict):
        raise ValueError(f"actor consciousness is not present on card: {actor_cons}")

    persona = copy.deepcopy(persona)
    ch_anchor = int((world_cursor or {}).get("ch_anchor", 0) or card.get("ch_anchor", 0) or 0)
    run_no = int((world_cursor or {}).get("run", 1) or 1)
    relation_stage = str(persona.get("relation_stage") or "S0")

    physical_scene = acv2.normalize_scene_frame(card)
    if not physical_scene:
        physical_scene = {"degradation": "scene_projection_incomplete"}
    # 导览三字段是玩家/导演散文，不是演员身体事实；角色已有 want_now /
    # relationship_memory / interaction_dynamics。一律不进 NPC 包。
    for player_only_key in hooks.player_guide_scene_frame_keys:
        physical_scene.pop(player_only_key, None)
    environment_deltas = [item for item in card.get("_public_environment_deltas", []) if isinstance(item, dict)]
    if environment_deltas:
        physical_scene["刚刚发生的环境变化"] = [str(item.get("text", "")) for item in environment_deltas]
    visible_scene_facts = [str(item) for item in card.get("_player_visible_scene_facts", []) if str(item).strip()]
    if visible_scene_facts:
        # 玩家已经公开说出的否定/承诺，是现场所有人共同要面对的事实；
        # 它不是导演指令，也绝不能被人格模型当成可忽略的闲聊。
        physical_scene["玩家已确认的现场事实"] = visible_scene_facts
    solidified = [str(item) for item in card.get("_solidified_visible_facts", []) if str(item).strip()]
    if solidified:
        physical_scene["场面已成立的事实"] = solidified
    holding_map = hooks.build_visible_holding_map(card)
    if holding_map:
        physical_scene["场上可见物态"] = holding_map
    object_use = hooks.extract_object_use_memory(card, history)
    if object_use:
        physical_scene["本场用过的物件"] = object_use
    language_obs = str(card.get("_language_discovery_observation") or "").strip()
    if language_obs:
        physical_scene["你刚听见的"] = language_obs
    verbatim = [str(item).strip() for item in (card.get("_verbatim_field_window") or []) if str(item).strip()]
    if not verbatim:
        verbatim = hooks.build_verbatim_field_window(history, limit=8)
    if verbatim:
        physical_scene["场上原话"] = verbatim
    situation_facets = hooks.select_situation_facets(
        card,
        card.get("_branch_progress_for_facets") or [],
        card.get("_completed_for_facets") or [],
        actor_cons,
        flash_beats=int(card.get("_flash_beats_for_facets") or 0),
        director_facet_ids=list(card.get("_director_facet_ids") or []),
    )
    if situation_facets:
        physical_scene["当前情境"] = [
            {
                "id": row["id"],
                "fact": row["fact"],
                "boundary": row.get("boundary") or "",
                "label": row.get("label") or "",
                "source": row.get("source") or "",
            }
            for row in situation_facets
        ]

    known_friend_profile: dict[str, Any] | None = None
    if card.get("prologue_active"):
        known_friend_profile = hooks.prologue_friend_known_profile(player_profile)
        friend_slice = {
            key: known_friend_profile[key]
            for key in hooks.prologue_friend_known_keys
            if known_friend_profile.get(key)
        }
        if friend_slice:
            physical_scene["两年朋友已知"] = friend_slice
        if known_friend_profile.get("instruction"):
            physical_scene["朋友关系口径"] = str(known_friend_profile["instruction"])

    raw_input = player_input if isinstance(player_input, dict) else {}
    observable_player = hooks.observable_player_for_actor(card, actor_cons, raw_input)
    query_text = " ".join(str(value).strip() for value in observable_player.values() if str(value).strip())
    for item in history[-8:]:
        if isinstance(item, dict):
            query_text += " " + str(item.get("text", ""))

    knowledge_candidates = acv2.fetch_relevant_knowledge(
        actor_cons, ch_anchor, query_text=query_text, top_k=8
    )
    # DB schedule is truth; card/persona fills gaps (esp. prologue ch_anchor=0).
    identity_relations = hooks.merge_identity_relations(
        acv2.fetch_identity_relations(actor_cons, ch_anchor),
        hooks.normalize_card_identity_relations(persona.get("identity_relations")),
        hooks.normalize_card_identity_relations(card.get("identity_relations")),
    )
    present_for_dynamics = [
        str(c) for c in (card.get("present") or [])
        if str(c) in (card.get("persona_cards") or {})
    ]
    interaction_dynamics = acv2.fetch_interaction_dynamics(
        actor_cons, present_for_dynamics, ch_anchor,
    )
    # Candidate pool (owned+章窗); activation Top-K is separate (cue∪cos+emo).
    slow_memory_candidates = acv2.fetch_slow_memory(
        actor_cons, ch_anchor, run_no=run_no, top_k=64, include_anchor=True,
    )

    working_seed = persona.get("scene_working_memory") if isinstance(persona.get("scene_working_memory"), dict) else {}
    inner_seed = persona.get("inner_state") if isinstance(persona.get("inner_state"), dict) else {}
    explicit_goals = [str(x) for x in working_seed.get("goals", []) if str(x).strip()]
    explicit_unresolved = [str(x) for x in working_seed.get("unresolved_topics", []) if str(x).strip()]
    # Every present consciousness needs an actionable, own working state.  A
    # card may optionally give a source-bound scene seed (as Zhang Chen's C16
    # task does); otherwise derive only the immediate desire/knot already
    # present in that actor's own persona projection.  This is not a new fact
    # nor a director instruction, merely the decision-facing form of its
    # existing inner state.
    working_goals = explicit_goals or [str(inner_seed.get("want_now", "")).strip()]
    working_unresolved = explicit_unresolved or [str(inner_seed.get("knot", "")).strip()]
    scene_working_memory = {
        "scene_uid": str(working_seed.get("scene_uid") or card.get("scene_id") or ""),
        "where": str(physical_scene.get("where") or ""),
        "goals": [item for item in working_goals if item],
        "commitments": [str(x) for x in working_seed.get("commitments", []) if str(x).strip()],
        "unresolved_topics": [item for item in working_unresolved if item],
        "body_state": str(working_seed.get("body_state") or ""),
        "source": copy.deepcopy(working_seed.get("source") or (
            {"projection": "persona.inner_state", "kind": "own_immediate_desire"}
            if not explicit_goals else {}
        )),
    }
    if not isinstance(card.get("_body_frames"), dict):
        hooks.ensure_card_body_frames(card)
    body_frame_now = hooks.body_frame_for_cons(card, actor_cons)
    if body_frame_now:
        # Keep prose note in sync with structured frame (holding drives note when empty).
        if body_frame_now.get("note"):
            scene_working_memory["body_state"] = str(body_frame_now["note"])
        elif body_frame_now.get("holding"):
            scene_working_memory["body_state"] = f"持有 {body_frame_now['holding']}"
        else:
            scene_working_memory["body_state"] = scene_working_memory.get("body_state") or "双手空闲"
    activation_context = "\n".join(
        [
            query_text,
            json.dumps(physical_scene, ensure_ascii=False),
            json.dumps(scene_working_memory, ensure_ascii=False),
            json.dumps(body_frame_now or {}, ensure_ascii=False),
        ]
    )
    activation = acv2.activate_memory_candidates(
        knowledge_candidates,
        slow_memory_candidates,
        activation_context,
        slow_activation_cues=persona.get("slow_memory_activation_cues"),
    )
    for item in slow_memory_candidates:
        if isinstance(item, dict):
            item.pop("_activation_anchor", None)
    relevant_knowledge = activation["knowledge_activated"]
    slow_memory_top_k = activation["slow_memory_activated"]
    kge_meta: dict[str, Any] = {}
    if ott.is_opening_top_tier_scene(card):
        emo_hint = ""
        if isinstance(runtime_inner_state, dict):
            emo_hint = str(runtime_inner_state.get("knot") or runtime_inner_state.get("want_now") or "")
        scored = ott.score_slow_memory_cos_emo(
            slow_memory_candidates, activation_context, emo_hint, top_k=2
        )
        slow_memory_top_k = ott.merge_slow_activations(slow_memory_top_k, scored, max_n=4)
        try:
            kge_meta = ott.kge_slice(actor_cons, ch_anchor)
            # Prefer schedule-activated knowledge; append KGE knows not already present.
            seen_pids = {str(x.get("prop_id")) for x in relevant_knowledge if isinstance(x, dict)}
            for row in kge_meta.get("knows") or []:
                pid = str(row.get("prop_id") or "")
                if pid and pid not in seen_pids:
                    relevant_knowledge.append(
                        {
                            "prop_id": pid,
                            "statement": row.get("statement"),
                            "tier": row.get("tier"),
                            "source": "KnowledgeGateEngine",
                        }
                    )
                    seen_pids.add(pid)
        except Exception as exc:  # noqa: BLE001 — degrade soft; card gates remain
            kge_meta = {"error": str(exc), "engine": "KnowledgeGateEngine"}
    scene_episode_candidates = [
        copy.deepcopy(item)
        for item in persona.get("scene_episode_history", [])
        if isinstance(item, dict)
    ]
    episode_activation = hooks.activate_scene_episode_candidates(scene_episode_candidates, activation_context)
    activated_scene_episodes = episode_activation["activated"]

    audible = acv2.turns_audible_to_actor(history, actor_cons)
    observable_dialogue = [
        {
            "speaker": item["speaker"],
            "text": item["text"],
            "stage": item.get("stage", ""),
            "turn": item.get("turn"),
        }
        for item in audible
        if item.get("channel") == "public"
    ]
    private_perceptions = [
        {
            "speaker": item["speaker"],
            "text": item["text"],
            "turn": item.get("turn"),
            "channel": "private_perception",
        }
        for item in audible
        if item.get("channel") == "private_perception"
    ]
    # C16 的“旧校友”是玩家与导演共享的落点背景，不是角色既知事实。
    # 张尘能在外围静默旁观时察觉到有人在看，并从站姿/视线作出暂定判断；
    # 斑驳、雨璇此刻正处理眼前搭讪，既不收到这条感知，也不能据此知晓玩家身份。
    if (
        str(card.get("scene_id", "")) == "CARD_16ZHONG_GATE"
        and actor_cons == "C.zhangchen.WMAIN"
        and hooks.c16_subtle_peripheral_watch(raw_input)
    ):
        private_perceptions.append(
            {
                "speaker": "现场感知",
                "text": "外围有人停得很自然，视线在校门和人流上落得像对这里有点熟。只能猜测对方可能与学校有关，不能当成事实；对方也没有显出敌意。",
                "turn": int(turn_no),
                "channel": "private_perception",
                "certainty": "tentative_inference",
            }
        )

    persona_core = acv2.resolve_persona_core(actor_cons, ch_anchor, relation_stage)
    self_core = {
        "name": persona.get("name"),
        "constraints": persona.get("constraints", []),
        "voice": persona.get("voice", {}),
        "relation_stage": relation_stage,
        "persona_core_hash": persona_core["persona_core_hash"],
        "voice_core_hash": persona_core["voice_core_hash"],
        "core_excerpt": persona_core["core_text"][:400],
        "constraint_text": persona_core["constraint_text"],
        "origin": persona_core.get("origin", "file"),
    }
    raw_samples = persona.get("voice_samples") or []
    processed_samples = []
    for sample in raw_samples:
        if isinstance(sample, dict) and "text" in sample:
            processed_samples.append(sample["text"])
        else:
            processed_samples.append(str(sample))
    # Seed facets win when card voice_samples cleared (S3 persona_core migration).
    if not processed_samples and persona_core.get("voice_samples"):
        processed_samples = list(persona_core.get("voice_samples") or [])
    self_core["voice_samples"] = processed_samples
    if persona_core.get("boundaries") and not (persona.get("boundaries") or {}).get("hard"):
        self_core["seed_boundaries"] = list(persona_core.get("boundaries") or [])
    if persona_core.get("manners"):
        self_core["seed_manners"] = list(persona_core.get("manners") or [])
    if persona_core.get("acts"):
        self_core["seed_acts"] = list(persona_core.get("acts") or [])
    # A phase profile is authored scene material, rather than a generic style
    # label.  It tells the actor what the character is trying to sound like in
    # this specific appearance, and keeps the receipt inspectable by the player.
    phase_voice_profile = persona.get("phase_voice_profile")
    if isinstance(phase_voice_profile, dict):
        self_core["phase_voice_profile"] = copy.deepcopy(phase_voice_profile)

    lorebook = persona.get("opening_lorebook") if isinstance(persona.get("opening_lorebook"), dict) else {}
    lore_always = [
        str(item.get("text", "")).strip()
        for item in lorebook.get("always", [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    lore_keyed = hooks.activate_keyed_lorebook(lorebook.get("keyed", []), raw_input, history)
    card_layers = card.get("memory_layers") if isinstance(card.get("memory_layers"), dict) else {}
    # 卡面事实层必须进角色包，否则「写在卡上」不等于「API 里记得」。
    # 过滤导演元说明（怎么分配/禁止照念），只留可被角色当现场事实用的句子。
    def _actor_usable_memory_line(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        meta_markers = ("导演只", "禁止照念", "具体台词由角色", "观测台", "must_happen")
        if any(marker in text for marker in meta_markers):
            return ""
        return text

    shared_relationship = [
        line
        for line in (_actor_usable_memory_line(item) for item in (card_layers.get("relationship_memory") or []))
        if line
    ]
    shared_context = [
        line
        for line in (_actor_usable_memory_line(item) for item in (card_layers.get("context_memory") or []))
        if line
    ]
    persona_memory = [str(item).strip() for item in (persona.get("memory_context") or []) if str(item).strip()]
    episode_lines = [
        f"[{item.get('scene_uid', 'previous_scene')}] {item.get('first_person_episode', '')}".strip()
        for item in activated_scene_episodes
        if str(item.get("first_person_episode", "")).strip()
    ]
    episodic_recent = list(dict.fromkeys(persona_memory + shared_context + shared_relationship + episode_lines))
    self_memory = {
        "opening_lorebook": lore_always + [f"[关键词] {text}" for text in lore_keyed],
        "episodic_recent": episodic_recent,
        "relationship": copy.deepcopy(persona.get("structured_memory", {})),
        "slow_memory_top_k": slow_memory_top_k,
        "slow_memory_candidates": slow_memory_candidates,
        "privileged_facts": copy.deepcopy(persona.get("privileged_facts", [])),
        "scene_working_memory": scene_working_memory,
    }
    if shared_relationship:
        self_memory["relationship_memory"] = shared_relationship
    if shared_context:
        self_memory["scene_context"] = shared_context
    if interaction_dynamics:
        self_memory["companion_views"] = [
            {
                "other": item["other"],
                "fact": item["fact"],
                "shared_public": item.get("shared_public") or "",
            }
            for item in interaction_dynamics
        ]
    if card.get("prologue_active") and known_friend_profile:
        self_memory["known_friend_profile"] = copy.deepcopy(known_friend_profile)
    self_state = {
        "inner_state": copy.deepcopy(runtime_inner_state if isinstance(runtime_inner_state, dict) else persona.get("inner_state", {})),
        "fsm": copy.deepcopy(
            (card.get("_session_fsm") or {}).get(actor_cons)
            if isinstance(card.get("_session_fsm"), dict)
            and isinstance((card.get("_session_fsm") or {}).get(actor_cons), dict)
            else persona.get("fsm", {})
        ),
        "offscreen": copy.deepcopy(persona.get("offscreen_state", {})),
        "body_props": [
            str(x).strip() for x in (persona.get("body_props") or []) if str(x).strip()
        ],
        "body_frame_now": body_frame_now,
        # N3: this actor sees its own structured mind, never another
        # consciousness's.  A missing persisted mind is seeded only from the
        # already-projected persona/core material, not from a model guess.
        "actor_mind": copy.deepcopy(actor_mind) if isinstance(actor_mind, dict) else build_actor_mind(
            actor_cons, persona, persona_core_hash=persona_core["persona_core_hash"],
        ),
    }
    disclosure_policy = acv2.build_disclosure_policy(persona, actor_cons, ch_anchor)
    if kge_meta.get("disclosure_lines"):
        disclosure_policy = list(disclosure_policy) + list(kge_meta["disclosure_lines"])
    director_instruction = acv2.build_director_instruction(
        card,
        actor_cons,
        turn_no,
        history,
        observable_player,
        completed=[],
    )

    source_trace = []
    for key, val in physical_scene.items():
        if val and key != "degradation":
            source_trace.append(
                {"source": f"scene_frame.{key}", "reason": f"物理现场·{key}", "value": val}
            )
    if observable_player:
        source_trace.append({"source": "player_input", "reason": "玩家本拍可被听见或看见的言行"})
    if observable_dialogue:
        source_trace.append({"source": "history", "reason": "角色在场时已经听到的公开台词"})
    if private_perceptions:
        source_trace.append(
            {
                "source": "director_share",
                "reason": f"导演选择性投递给该意识的现场感知×{len(private_perceptions)}",
            }
        )
        if any(item.get("certainty") == "tentative_inference" for item in private_perceptions):
            source_trace.append(
                {
                    "source": "c16_perception_rule",
                    "reason": "张尘仅凭外围静默旁观作出的未确认现场推断",
                }
            )
    if relevant_knowledge:
        source_trace.append(
            {
                "source": "knowledge_schedule",
                "reason": f"本拍实际激活的相关长期知识×{len(relevant_knowledge)}",
                "hits": [item["prop_id"] for item in relevant_knowledge],
            }
        )
    if identity_relations:
        source_trace.append(
            {
                "source": "knowledge_schedule.identity_relations",
                "reason": f"常驻身份关系×{len(identity_relations)}（不靠当拍关键词召回）",
                "hits": [item["prop_id"] for item in identity_relations],
            }
        )
    if interaction_dynamics:
        source_trace.append(
            {
                "source": "interaction_dynamics",
                "reason": f"在场他人共处事实×{len(interaction_dynamics)}（跟意识走，不跟卡）",
                "hits": [item["other"] for item in interaction_dynamics],
            }
        )
    if slow_memory_top_k:
        source_trace.append(
            {
                "source": "slow_memory",
                "reason": f"本拍实际激活的慢环×{len(slow_memory_top_k)}",
                "hits": [item.get("mem_id") for item in slow_memory_top_k],
            }
        )
    if activated_scene_episodes:
        source_trace.append(
            {
                "source": "scene_episode_history",
                "reason": f"本拍因当前话题重新激活的个人场景经历×{len(activated_scene_episodes)}",
                "hits": [item.get("scene_uid") for item in activated_scene_episodes],
            }
        )
    source_trace.append(
        {"source": f"persona_core.{actor_cons}", "reason": "共享人格核", "hash": persona_core["persona_core_hash"]}
    )

    world = acv2.project_world_events(
        ch_anchor,
        list(physical_scene.get("present") or card.get("present") or []),
        current_location=str(
            physical_scene.get("scene")
            or card.get("scene")
            or (card.get("scene_frame") or {}).get("where")
            or ""
        ),
        current_scene_id=str(card.get("scene_id") or ""),
    )
    world_signals = world.get("actor_world_signals", {}).get(actor_cons, [])
    stage_projection = view_projection.build_stage_projection(card)
    actor_space = next(
        (item for item in stage_projection["characters"] if item.get("cons") == actor_cons),
        {"cons": actor_cons, "relation_to_player": "beside_player", "zone": stage_projection["player_position"]},
    )

    return {
        "actor_cons": actor_cons,
        "turn": int(turn_no),
        "scene": str(card.get("scene_id", "")).strip(),
        "world_cursor": copy.deepcopy(world_cursor or {}),
        "physical_scene": physical_scene,
        "observable_scene": physical_scene,
        "director_observation": {
            "spatial_truth": {
                "player_position": stage_projection["player_position"],
                "self_position": actor_space,
                "co_present": [item for item in stage_projection["characters"] if item.get("cons") != actor_cons],
            },
            "event_delivery": "仅本角色可观察的现场事件与导演当拍安排；不是全局真相。",
        },
        "observable_player": observable_player,
        "observable_dialogue": observable_dialogue,
        "private_perceptions": private_perceptions,
        "self_core": self_core,
        "self_memory": self_memory,
        "self_state": self_state,
        "body_frame_now": body_frame_now,
        # Distinct from relation_stage (dynamic feeling) and episodes (what
        # happened): this is the actor's already-known social identity map.
        # The disclosure policy remains separate so this never instructs an
        # actor to introduce a secret merely because it knows it.
        "identity_relations": identity_relations,
        "interaction_dynamics": interaction_dynamics,
        "social_context": {
            "identity_relations": copy.deepcopy(identity_relations),
            "interaction_dynamics": copy.deepcopy(interaction_dynamics),
            "rel_state": copy.deepcopy(
                ((card.get("_session_rel_state") or {}).get(actor_cons))
                if isinstance(card.get("_session_rel_state"), dict)
                else None
            ),
            "projection_policy": (
                "身份常识与在场共处事实常驻于理解与行动；是否主动说出仍受 disclosure_policy 约束。"
            ),
        },
        "relevant_knowledge_top_k": relevant_knowledge,
        "known_fact_ids": relevant_knowledge,
        "knowledge_candidates": knowledge_candidates,
        "memory_activation": {
            "knowledge_candidates": knowledge_candidates,
            "slow_memory_candidates": slow_memory_candidates,
            "scene_episode_candidates": scene_episode_candidates,
            "scene_episode_activated": activated_scene_episodes,
            "scene_episode_withheld": episode_activation["withheld"],
            "kge": {k: kge_meta.get(k) for k in ("engine", "blocked_prop_ids", "error") if kge_meta},
            **activation,
        },
        "disclosure_policy": disclosure_policy,
        "director_instruction": director_instruction,
        "biographical_fact_allowlist": [],
        "world_signals": world_signals,
        "source_trace": source_trace,
    }

