"""Director closed moves as Function Calling tools.

Does not change the production LLM contract. Maps ``CLOSED_MOVES`` to JSON
schemas and rejects illegal tool calls before any model output is applied.
Resolver legality still lives in ``director_harness.adjudicate_move``.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from runtime.director_harness import (
    CLOSED_MOVES,
    MOVE_LABELS,
    adjudicate_move,
    is_closed_move,
    snapshot_harness_inputs,
)

_SPEAKER_ENUM = ["店员", "路人", "旁白"]

_REASON_PROP = {
    "type": "string",
    "minLength": 1,
    "maxLength": 120,
    "description": "本拍场上条件怎么变了（可见理由，不是内心）",
}

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "quiet": {
        "type": "function",
        "function": {
            "name": "quiet",
            "description": "本拍不改场上条件，保持静默。",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    "ambient_extra": {
        "type": "function",
        "function": {
            "name": "ambient_extra",
            "description": "店员或环境薄声。不写主卡台词。",
            "parameters": {
                "type": "object",
                "properties": {
                    "visible_reason": _REASON_PROP,
                    "text": {"type": "string", "maxLength": 240},
                    "speaker": {"type": "string", "enum": list(_SPEAKER_ENUM)},
                },
                "required": ["visible_reason"],
                "additionalProperties": False,
            },
        },
    },
    "time_pressure": {
        "type": "function",
        "function": {
            "name": "time_pressure",
            "description": "时间压：场变紧，不代写角色词。",
            "parameters": {
                "type": "object",
                "properties": {"visible_reason": _REASON_PROP},
                "required": ["visible_reason"],
                "additionalProperties": False,
            },
        },
    },
    "admit_extra": {
        "type": "function",
        "function": {
            "name": "admit_extra",
            "description": "放进已声明的路人。",
            "parameters": {
                "type": "object",
                "properties": {
                    "visible_reason": _REASON_PROP,
                    "actor_target": {"type": "string", "maxLength": 40},
                },
                "required": ["visible_reason"],
                "additionalProperties": False,
            },
        },
    },
    "close_window": {
        "type": "function",
        "function": {
            "name": "close_window",
            "description": "收窗：本场可结束。",
            "parameters": {
                "type": "object",
                "properties": {"visible_reason": _REASON_PROP},
                "required": ["visible_reason"],
                "additionalProperties": False,
            },
        },
    },
}


def list_tools(legal_moves: list[str] | None = None) -> list[dict[str, Any]]:
    """OpenAI-style tool list, filtered to this beat's legal subset."""
    allowed = list(legal_moves) if legal_moves is not None else list(CLOSED_MOVES)
    out: list[dict[str, Any]] = []
    for name in CLOSED_MOVES:
        if name in allowed and name in TOOL_SPECS:
            out.append(dict(TOOL_SPECS[name]))
    return out


def _extract_call(call: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(call, Mapping):
        return "", {}
    name = str(call.get("name") or "").strip()
    args: Any = call.get("arguments")
    fn = call.get("function")
    if not name and isinstance(fn, Mapping):
        name = str(fn.get("name") or "").strip()
        if args is None:
            args = fn.get("arguments")
    if isinstance(args, str):
        raw = args.strip()
        if not raw:
            args = {}
        else:
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                return name, {"__invalid_json__": True}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return name, {"__invalid_args__": True}
    return name, args


def _schema_errors(name: str, args: Mapping[str, Any]) -> list[str]:
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return [f"unknown tool: {name}"]
    params = spec["function"]["parameters"]
    props = params.get("properties") or {}
    required = list(params.get("required") or [])
    extra = [k for k in args if k not in props]
    if extra and params.get("additionalProperties") is False:
        return [f"extra fields: {', '.join(extra)}"]
    if args.get("__invalid_json__"):
        return ["arguments is not valid JSON"]
    if args.get("__invalid_args__"):
        return ["arguments must be an object"]
    missing = [k for k in required if not str(args.get(k) or "").strip()]
    if missing:
        return [f"missing required: {', '.join(missing)}"]
    speaker = args.get("speaker")
    if speaker is not None and "speaker" in props:
        enum = (props["speaker"] or {}).get("enum") or []
        if enum and str(speaker) not in enum:
            return [f"speaker not in {enum}"]
    return []


def parse_tool_call(
    call: Mapping[str, Any] | None,
    *,
    legal_moves: list[str] | None = None,
    harness_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a Function Call against schema + this-beat legality.

    Returns ``{ok, name, arguments, reason}``. Never raises.
    """
    if not call:
        return {"ok": False, "name": "", "arguments": {}, "reason": "empty tool call"}
    name, args = _extract_call(call)
    if not name:
        return {"ok": False, "name": "", "arguments": {}, "reason": "missing tool name"}
    if not is_closed_move(name):
        return {"ok": False, "name": name, "arguments": args, "reason": f"illegal move: {name}"}
    schema_fail = _schema_errors(name, args)
    if schema_fail:
        return {"ok": False, "name": name, "arguments": args, "reason": schema_fail[0]}
    clean_args = {k: v for k, v in args.items() if not str(k).startswith("__")}
    allowed = {str(x).strip() for x in (legal_moves if legal_moves is not None else CLOSED_MOVES)}
    if name not in allowed:
        return {
            "ok": False,
            "name": name,
            "arguments": clean_args,
            "reason": "opportunity.kind 不在本拍 legal_moves",
        }
    inputs = dict(harness_inputs or snapshot_harness_inputs())
    ok, why = adjudicate_move(name, inputs)
    if not ok:
        return {"ok": False, "name": name, "arguments": clean_args, "reason": why}
    return {"ok": True, "name": name, "arguments": clean_args, "reason": why}


def opportunity_to_tool_call(
    opportunity: Mapping[str, Any] | None,
    *,
    voice: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map harness ``opportunity`` (+ optional voice) to a tool call dict."""
    if not isinstance(opportunity, Mapping):
        return {"name": "quiet", "arguments": {}}
    kind = str(opportunity.get("kind") or "quiet").strip() or "quiet"
    args: dict[str, Any] = {}
    reason = str(opportunity.get("visible_reason") or "").strip()
    if kind != "quiet" and reason:
        args["visible_reason"] = reason
    target = str(opportunity.get("actor_target") or "").strip()
    if target:
        args["actor_target"] = target
    if kind == "ambient_extra" and isinstance(voice, Mapping):
        text = str(voice.get("text") or "").strip()
        speaker = str(voice.get("speaker") or "").strip()
        if text:
            args["text"] = text[:240]
        if speaker:
            args["speaker"] = speaker
    if kind not in CLOSED_MOVES:
        return {"name": kind, "arguments": args}
    return {"name": kind, "arguments": args}


def tool_label(name: str) -> str:
    return MOVE_LABELS.get(str(name or "").strip(), str(name or ""))
