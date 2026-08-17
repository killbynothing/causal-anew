"""N5 director harness: closed move set, legality gates, slim world prompt, output recheck.

The director is a harness, not a fifth agent. It reads the ledger / spine
remaining / player thought / physical state, proposes a move from a closed set,
Resolver adjudicates legality before any LLM, and the LLM only fills
Stage / Dramaturgy / Voice.

Pure module: no Session or live refs and no import of free_stage_prototype
(avoids a cycle). The production path injects the text checks it already owns
(banned notes / ambient) via ``text_check``.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping

CLOSED_MOVES: tuple[str, ...] = (
    "quiet", "ambient_extra", "time_pressure", "admit_extra", "close_window",
)

MOVE_LABELS: dict[str, str] = {
    "quiet": "安静",
    "ambient_extra": "店员薄声",
    "time_pressure": "时间压",
    "admit_extra": "放进路人",
    "close_window": "收窗",
}

_FORBIDDEN_OUTPUT_KEYS = ("actor_decision", "decision", "accepted", "accept", "refuse", "refused", "outcome")


def snapshot_harness_inputs(
    *,
    scene_id: str = "",
    prologue_active: bool = False,
    stall: int = 0,
    active_exit_state: str = "converged",
    exit_clock_active: bool = False,
    casual_cap: bool = False,
    player_requested_stage: bool = False,
    player_ordering: bool = False,
    has_barista: bool = False,
    has_stranger_profile: bool = False,
    close_window_near: bool = False,
    spine_remaining: int = 0,
) -> dict[str, Any]:
    """Pack the deterministic signals the move table reads (看见层).

    All values are plain scalars; the production path computes them from the
    ledger / spine / thought / physical state before calling this module.
    """
    return {
        "scene_id": str(scene_id or ""),
        "prologue_active": bool(prologue_active),
        "stall": int(stall or 0),
        "active_exit_state": str(active_exit_state or "converged"),
        "exit_clock_active": bool(exit_clock_active),
        "casual_cap": bool(casual_cap),
        "player_requested_stage": bool(player_requested_stage),
        "player_ordering": bool(player_ordering),
        "has_barista": bool(has_barista),
        "has_stranger_profile": bool(has_stranger_profile),
        "close_window_near": bool(close_window_near),
        "spine_remaining": int(spine_remaining or 0),
    }


def trigger_move_candidates(inputs: Mapping[str, Any]) -> list[str]:
    """出招：确定性触发 → 闭集子集。quiet 恒在。"""
    candidates: list[str] = ["quiet"]
    if inputs.get("has_barista") and (
        inputs.get("player_ordering") or inputs.get("stall", 0) >= 1
    ):
        candidates.append("ambient_extra")
    if (
        inputs.get("spine_remaining", 0) > 0
        and (
            inputs.get("exit_clock_active")
            or inputs.get("casual_cap")
            or inputs.get("stall", 0) >= 2
        )
    ):
        candidates.append("time_pressure")
    if inputs.get("has_stranger_profile") and (
        inputs.get("player_requested_stage") or inputs.get("casual_cap")
    ):
        candidates.append("admit_extra")
    if inputs.get("close_window_near") or inputs.get("active_exit_state") not in ("", "converged"):
        candidates.append("close_window")
    return candidates


def adjudicate_move(move_id: str, inputs: Mapping[str, Any]) -> tuple[bool, str]:
    """Resolver-B：逐招过合法前置，先于 LLM。"""
    if move_id == "quiet":
        return True, "quiet is always legal"
    if move_id == "ambient_extra":
        if not inputs.get("has_barista"):
            return False, "no barista / ambient person declared in this scene"
        if not (inputs.get("player_ordering") or inputs.get("stall", 0) >= 1):
            return False, "no ordering signal and no beat without progress"
        return True, "barista thin voice is legal"
    if move_id == "time_pressure":
        if inputs.get("spine_remaining", 0) <= 0:
            return False, "no spine remaining to press"
        if (
            inputs.get("stall", 0) < 2
            and not inputs.get("exit_clock_active")
            and not inputs.get("casual_cap")
        ):
            return False, "no clock / cap / stall evidence for pressure"
        return True, "time pressure is legal"
    if move_id == "admit_extra":
        if not inputs.get("has_stranger_profile"):
            return False, "no stranger profile declared on this card"
        if not (inputs.get("player_requested_stage") or inputs.get("casual_cap")):
            return False, "player did not ask for the stage and no cap signal"
        return True, "admitting a passerby is legal"
    if move_id == "close_window":
        if not (
            inputs.get("close_window_near") or inputs.get("active_exit_state") not in ("", "converged")
        ):
            return False, "scene close window is not open"
        return True, "closing the window is legal"
    return False, f"unknown move: {move_id}"


def legal_moves(inputs: Mapping[str, Any]) -> list[str]:
    """Resolver-B output：闭集的合法子集（quiet 恒在）。"""
    return [m for m in CLOSED_MOVES if adjudicate_move(m, inputs)[0]]


def is_closed_move(move_id: str) -> bool:
    return str(move_id or "").strip() in CLOSED_MOVES


def _ambient_dict(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        text = raw.strip()
        return {"text": text[:240], "speaker": "旁白"} if text else None
    if isinstance(raw, dict):
        text = str(raw.get("text") or "").strip()
        speaker = str(raw.get("speaker") or "旁白").strip() or "旁白"
        return {"text": text[:240], "speaker": speaker[:40]} if text else None
    return None


def fold_world_skin_into_ambient(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge Voice / Stage.scene_hint into ambient so the visible layer can land.

    Contract field is ``voice``; the production narrate path still reads
    ``ambient``. Prefer an existing ambient text; otherwise copy voice, then
    the stage hint.
    """
    out = dict(payload or {})
    if _ambient_dict(out.get("ambient")):
        return out
    voice = _ambient_dict(out.get("voice"))
    if voice:
        out["ambient"] = voice
        return out
    stage = out.get("stage")
    if isinstance(stage, dict):
        hint = str(stage.get("scene_hint") or "").strip()
        if hint:
            out["ambient"] = {"text": hint[:240], "speaker": "旁白"}
    return out


def _recent_visible(rows: Any, limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in (rows or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "player_thought":
            continue
        out.append({
            "role": str(item.get("role", "") or ""),
            "speaker": str(item.get("speaker", "") or ""),
            "text": str(item.get("text", "") or ""),
        })
    return out


def build_harness_prompt(
    prompt_payload: Mapping[str, Any],
    legal: list[str],
    *,
    physical_state: Mapping[str, Any] | None = None,
) -> str:
    """Slim world-side prompt for the director call.

    No persona cards, no ``turns`` output, no MH self-report as truth. The LLM
    picks one legal move (Dramaturgy) and fills Stage / Voice / a hint.
    """
    card = prompt_payload.get("constraint_card") if isinstance(prompt_payload.get("constraint_card"), dict) else {}
    allowed = [
        str(item.get("id", "") or "").strip()
        for item in card.get("must_happen", []) or []
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    ]
    completed = {
        str(x) for x in (prompt_payload.get("completed_must_happen") or []) if str(x).strip()
    }
    remaining = [x for x in allowed if x not in completed]
    scene_frame = dict(prompt_payload.get("scene_frame") or {})
    branch_progress = [
        str(x) for x in (prompt_payload.get("branch_progress") or []) if str(x).strip()
    ]
    harness = {
        "role": "导演是世界与玩家的初遇面：观察，记录做成之事，只改条件、盖收据。"
        "不为感情加入，不为拯救预谋。你演的是世界的皮肤，意志在因果和闸里。",
        "legal_moves": list(legal),
        "closed_moves": dict(MOVE_LABELS),
        "forbidden": [
            "不写主卡台词(turns)",
            "不自报 must_happen 成立（成立与否由引擎证据裁决）",
            "不改正典事实",
            "不加入/不更改关系",
            "不替任何角色点头或拒绝",
        ],
        "output_contract": {
            "director_note": "一句只描述本拍已成立的可见事实；禁预告、禁“完成XX”、禁姓名播报",
            "opportunity": "可选对象 {\\\"kind\\\":\\\"time_pressure|admit_extra|close_window\\\","
            " \\\"visible_reason\\\":\\\"条件怎么变的\\\", \\\"actor_target\\\":\\\"可选，仅已有在场者\\\"}",
            "stage": "可选对象 {\\\"active\\\": true或false, \\\"scene_hint\\\":\\\"雨/吧台/路人，可空\\\"}",
            "voice": "可选对象 {\\\"text\\\":\\\"薄声，可空\\\", \\\"speaker\\\":\\\"店员|路人|旁白\\\"}",
            "mh_progress": "可选提示，0或1个合法id；成立与否由引擎证据裁决，不是你的报告",
        },
    }
    body = {
        "director_harness": harness,
        "scene_id": str(card.get("scene_id", "") or ""),
        "scene_frame": scene_frame,
        "physical_state": dict(physical_state or prompt_payload.get("physical_state") or {}),
        "ledger_summary": {
            "completed_must_happen": sorted(completed),
            "remaining_must_happen": remaining,
            "branch_progress": branch_progress[-24:],
            "stall_turns_without_progress": prompt_payload.get("stall_turns_without_mh_progress", 0),
            "active_exit_state": prompt_payload.get("active_exit_state", "converged"),
        },
        "player_input": prompt_payload.get("player_input", ""),
        "recent_history": _recent_visible(prompt_payload.get("recent_history")),
    }
    return json.dumps(body, ensure_ascii=False, indent=2)


def validate_harness_output(
    payload: Mapping[str, Any],
    *,
    allowed_mh_ids: Iterable[str] = (),
    legal_moves: Iterable[str] | None = None,
    card: Mapping[str, Any] | None = None,
    text_check: Callable[[str], list[str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Resolver-C：导演 LLM 产物的结构性复核。

    Returns (clean_payload, degradations, fatal_errors).

    turns       → dropped with degradation, never fatal (main-card lines come
                  only from call_actor_packet).
    mh_progress → kept only as a hint; ids outside the card's must_happen are
                  dropped. Never written to ``completed`` by itself.
    opportunity → kind must be a non-quiet closed move; if ``legal_moves`` is
                  given it must also sit in that beat's set, else dropped.
    voice/stage → schema-guarded then folded into ambient for the visible path.
    text_check  → optional callback that flags banned note/ambient text (fatal).
    """
    clean: dict[str, Any] = {}
    degradations: list[dict[str, Any]] = []
    fatal: list[str] = []
    raw = dict(payload)
    allowed = {str(x).strip() for x in allowed_mh_ids if str(x).strip()}

    for key in _FORBIDDEN_OUTPUT_KEYS:
        if key in raw:
            degradations.append({"kind": "director_forbidden_key", "key": key, "severity": "SOFT"})
            raw.pop(key, None)

    turns = raw.get("turns")
    if isinstance(turns, list) and turns:
        degradations.append({
            "kind": "director_turns_rejected",
            "severity": "SOFT",
            "reason": "主卡台词只由 call_actor_packet 产出，导演不写 turns",
            "count": len(turns),
        })
        raw.pop("turns", None)

    hint: list[str] = []
    mh = raw.get("mh_progress")
    if isinstance(mh, list):
        for item in mh:
            value = str(item or "").strip()
            if not value:
                continue
            if allowed and value not in allowed:
                degradations.append({"kind": "director_mh_hint_dropped", "id": value, "severity": "SOFT"})
                continue
            if hint:
                # 已保留第一个 hint，其余合法 id 只是多余提示。
                degradations.append({"kind": "director_mh_hint_extra_dropped", "id": value, "severity": "SOFT"})
                continue
            hint.append(value)
        raw.pop("mh_progress", None)
    clean["mh_progress"] = hint

    this_beat_legal = None
    if legal_moves is not None:
        this_beat_legal = {str(x).strip() for x in legal_moves if str(x).strip()}

    opportunity = raw.get("opportunity")
    if isinstance(opportunity, dict):
        kind = str(opportunity.get("kind") or "").strip()
        if kind in CLOSED_MOVES and kind != "quiet":
            if this_beat_legal is not None and kind not in this_beat_legal:
                degradations.append({
                    "kind": "director_opportunity_not_legal",
                    "move": kind,
                    "severity": "SOFT",
                    "reason": "opportunity.kind 不在本拍 legal_moves",
                })
            else:
                clean["opportunity"] = {
                    key: opportunity[key]
                    for key in ("kind", "visible_reason", "actor_target")
                    if key in opportunity
                }
        elif kind:
            fatal.append(f"director chose illegal move: {kind}")

    voice = raw.get("voice")
    if isinstance(voice, dict):
        text = str(voice.get("text") or "").strip()
        speaker = str(voice.get("speaker") or "旁白").strip() or "旁白"
        if text:
            if text_check:
                issues = text_check(text)
                if issues:
                    fatal.append(f"director voice banned: {issues[:3]}")
                else:
                    clean["voice"] = {"text": text[:240], "speaker": speaker[:40]}
            else:
                clean["voice"] = {"text": text[:240], "speaker": speaker[:40]}

    stage = raw.get("stage")
    if isinstance(stage, dict) and stage.get("active") is True:
        clean["stage"] = {"active": True, "scene_hint": str(stage.get("scene_hint") or "")[:200]}

    ambient = raw.get("ambient")
    if isinstance(ambient, (str, dict)) and ambient not in ("", None, [], False):
        text = ambient if isinstance(ambient, str) else str(ambient.get("text") or "")
        speaker = "旁白" if isinstance(ambient, str) else str(ambient.get("speaker") or "旁白")
        text = str(text or "").strip()
        if text:
            if text_check:
                issues = text_check(text)
                if issues:
                    fatal.append(f"director ambient banned: {issues[:3]}")
                else:
                    clean["ambient"] = {"text": text[:240], "speaker": speaker[:40]}
            else:
                clean["ambient"] = {"text": text[:240], "speaker": speaker[:40]}

    note = str(raw.get("director_note") or "").strip()
    if note:
        if text_check:
            issues = text_check(note)
            if issues:
                fatal.append(f"director_note banned: {issues[:3]}")
        clean["director_note"] = note[:400]

    folded = fold_world_skin_into_ambient(clean)
    if folded.get("ambient") and not clean.get("ambient"):
        clean["ambient"] = folded["ambient"]
    return clean, degradations, fatal
