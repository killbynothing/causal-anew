# -*- coding: utf-8 -*-
"""P6 pure scene policies.

Policies receive immutable, already-observable snapshots and return evidence,
opportunities or proposals. They never hold a session reference and never
write runtime authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_JA_MARK_PREFIXES = ("（日）", "(日)", "（日语）", "(日语)")


@dataclass(frozen=True)
class PublicTurn:
    role: str
    text: str = ""
    lang: str = ""
    original_text: str = ""
    player_visible: bool = True
    audience: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PublicTurn":
        return cls(
            role=str(raw.get("role") or ""),
            text=str(raw.get("text") or ""),
            lang=str(raw.get("lang") or ""),
            original_text=str(raw.get("original_text") or ""),
            player_visible=raw.get("player_visible") is not False,
            audience=str(raw.get("audience") or ""),
        )


@dataclass(frozen=True)
class ScenePolicyInput:
    scene_id: str
    player_speech: str = ""
    player_action: str = ""
    recent_history: tuple[PublicTurn, ...] = ()

    @classmethod
    def from_runtime(
        cls,
        *,
        scene_id: str,
        player_input: str | Mapping[str, Any],
        recent_history: Sequence[Mapping[str, Any]] | None = None,
    ) -> "ScenePolicyInput":
        if isinstance(player_input, Mapping):
            speech = str(player_input.get("speech") or "").strip()
            action = str(player_input.get("action") or "").strip()
        else:
            speech = str(player_input or "").strip()
            action = ""
        history = tuple(
            PublicTurn.from_mapping(item)
            for item in (recent_history or ())
            if isinstance(item, Mapping)
        )
        return cls(
            scene_id=str(scene_id or ""),
            player_speech=speech,
            player_action=action,
            recent_history=history,
        )

    @property
    def player_public_text(self) -> str:
        return " ".join(
            item for item in (self.player_speech, self.player_action) if item
        )


@dataclass(frozen=True)
class ScenePolicyOutput:
    evidence: tuple[str, ...] = ()
    opportunities: tuple[str, ...] = ()
    proposals: tuple[str, ...] = ()


def _history_item_is_japanese_npc(item: PublicTurn | None) -> bool:
    if item is None or item.role != "npc":
        return False
    if item.lang == "ja":
        return True
    blob = f"{item.original_text}{item.text}"
    if any(blob.startswith(prefix) for prefix in _JA_MARK_PREFIXES):
        return True
    return bool(_KANA_RE.search(blob))


def _latest_visible_npc(history: Sequence[PublicTurn]) -> PublicTurn | None:
    for item in reversed(tuple(history)):
        if item.role in {"player", "player_thought"}:
            continue
        if not item.player_visible or item.audience == "director_only":
            continue
        if item.role == "npc" and item.text.strip():
            return item
        if item.role in {"narrate", "bridge"}:
            continue
        break
    return None


def _player_chinese_reply_signals_japanese_comprehension(
    snapshot: ScenePolicyInput,
) -> bool:
    text = re.sub(r"\s+", "", snapshot.player_public_text)
    if not text or not re.search(r"[\u4e00-\u9fff]", text):
        return False
    if any(
        token in text
        for token in ("听不懂", "听不懂日语", "不会日语", "不会日文", "看不懂")
    ):
        return False
    return True


def evaluate_tiananmen(snapshot: ScenePolicyInput) -> ScenePolicyOutput:
    """Return public evidence only; committing it remains a runtime owner job."""
    if snapshot.scene_id != "OPENING_TIANANMEN_002":
        return ScenePolicyOutput()

    text = re.sub(r"\s+", "", snapshot.player_public_text)
    facts: set[str] = set()

    if any(
        token in text
        for token in ("没录到", "没有录到", "没拍到", "没有视频", "没录视频", "忘了拍", "错过升旗")
    ):
        facts.add("tiananmen_video_unavailable")

    video_words = ("视频", "录像", "手机")
    if any(token in text for token in video_words) and any(
        token in text for token in ("给你", "给你们", "可以", "拿去", "传给", "拷")
    ):
        facts.add("tiananmen_video_offered")

    latest = _latest_visible_npc(snapshot.recent_history)
    if (
        any(
            token in text
            for token in ("听得懂日语", "听得懂日文", "会日语", "会日文", "能听懂日语")
        )
        or (
            any(token in text for token in ("日语", "日文"))
            and any(token in text for token in ("会", "懂", "听得"))
        )
        or bool(_KANA_RE.search(text))
        or (
            _history_item_is_japanese_npc(latest)
            and _player_chinese_reply_signals_japanese_comprehension(snapshot)
        )
    ):
        facts.add("tiananmen_japanese_understood")

    aquarium_tokens = ("海洋馆", "水族馆", "海族馆")
    aquarium_in_text = any(token in text for token in aquarium_tokens)
    aquarium_already_on_table = any(
        item.role == "npc"
        and any(token in item.text for token in aquarium_tokens)
        for item in snapshot.recent_history
    )
    if any(token in text for token in ("我自己去海洋馆", "我一个人去海洋馆")) or (
        aquarium_in_text and any(token in text for token in ("我自己去", "我一个人去"))
    ):
        facts.add("tiananmen_independent_aquarium_destination")
    elif aquarium_in_text and any(
        token in text
        for token in (
            "不去海洋馆",
            "我不去海洋馆",
            "不去水族馆",
            "不一起去",
            "不跟你们去",
            "不去了",
            "算了不去",
        )
    ):
        facts.add("tiananmen_aquarium_declined")
    elif aquarium_already_on_table and any(
        token in text
        for token in ("不去了", "算了不去", "不一起去", "不跟你们去", "先回去", "我先走了")
    ):
        facts.add("tiananmen_aquarium_declined")
    elif any(token in text for token in ("一起去海洋馆", "跟你们去海洋馆")) or (
        (aquarium_in_text or aquarium_already_on_table)
        and any(token in text for token in ("一起走", "跟你们一起", "一起去"))
    ):
        facts.add("tiananmen_aquarium_accepted")

    return ScenePolicyOutput(evidence=tuple(sorted(facts)))


def evaluate(snapshot: ScenePolicyInput) -> ScenePolicyOutput:
    """Dispatch a pure snapshot to the scene policy known to this module."""
    if snapshot.scene_id == "OPENING_TIANANMEN_002":
        return evaluate_tiananmen(snapshot)
    return ScenePolicyOutput()
