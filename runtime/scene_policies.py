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

_RYUYA_TOPIC_INTERFACE_MARKERS = (
    "弟弟", "修哉", "家人", "家里", "托付", "拜托", "有事", "想说",
    "临走", "走之前", "分别", "要走", "离开", "照顾", "帮忙", "以后",
    "保重", "挂坠", "吊坠", "项链", "怎么了", "还好吗", "有心事",
    "今天好像", "该走了", "时间不早", "有话",
)


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
class CanonSegmentSpec:
    segment_id: str
    trigger: str = ""
    after_stop: str = ""
    requires_branch: frozenset[str] = frozenset()
    requires_autonomous_decisions: frozenset[str] = frozenset()
    requires_autonomous_outcomes: tuple[tuple[str, str], ...] = ()
    auto_continue: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CanonSegmentSpec":
        outcomes = raw.get("requires_autonomous_outcomes")
        outcome_items: list[tuple[str, str]] = []
        if isinstance(outcomes, Mapping):
            outcome_items = sorted(
                (
                    str(key or "").strip(),
                    str(value or "").strip(),
                )
                for key, value in outcomes.items()
                if str(key or "").strip()
            )
        return cls(
            segment_id=str(raw.get("segment_id") or "").strip(),
            trigger=str(raw.get("trigger") or "").strip(),
            after_stop=str(raw.get("after_stop") or "").strip(),
            requires_branch=frozenset(
                str(item or "").strip()
                for item in (raw.get("requires_branch") or ())
                if str(item or "").strip()
            ),
            requires_autonomous_decisions=frozenset(
                str(item or "").strip()
                for item in (raw.get("requires_autonomous_decisions") or ())
                if str(item or "").strip()
            ),
            requires_autonomous_outcomes=tuple(outcome_items),
            auto_continue=bool(raw.get("auto_continue")),
        )


@dataclass(frozen=True)
class CanonSelectionInput:
    pending_stop: str
    completed_segments: frozenset[str] = frozenset()
    branch_progress: frozenset[str] = frozenset()
    resolved_decisions: frozenset[str] = frozenset()
    decision_outcomes: tuple[tuple[str, str], ...] = ()
    segments: tuple[CanonSegmentSpec, ...] = ()

    @classmethod
    def from_runtime(
        cls,
        *,
        pending_stop: str,
        completed_segments: Sequence[str] = (),
        branch_progress: Sequence[str] = (),
        actor_decisions: Sequence[Mapping[str, Any]] = (),
        segments: Sequence[Mapping[str, Any]] = (),
    ) -> "CanonSelectionInput":
        decisions: set[str] = set()
        outcomes: dict[str, str] = {}
        for item in actor_decisions:
            if not isinstance(item, Mapping):
                continue
            decision_id = str(item.get("autonomous_decision_id") or "").strip()
            if not decision_id:
                continue
            decisions.add(decision_id)
            outcomes[decision_id] = str(item.get("outcome") or "").strip()
        return cls(
            pending_stop=str(pending_stop or "").strip(),
            completed_segments=frozenset(
                str(item or "").strip()
                for item in completed_segments
                if str(item or "").strip()
            ),
            branch_progress=frozenset(
                str(item or "").strip()
                for item in branch_progress
                if str(item or "").strip()
            ),
            resolved_decisions=frozenset(decisions),
            decision_outcomes=tuple(sorted(outcomes.items())),
            segments=tuple(
                CanonSegmentSpec.from_mapping(item)
                for item in segments
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True)
class CanonSegmentSelection:
    segment_id: str
    auto_continue: bool = False


@dataclass(frozen=True)
class FlashbackHandoffInput:
    prologue_active: bool
    has_return_frame: bool
    all_must_happen_complete: bool


@dataclass(frozen=True)
class RyuyaCafeStateInput:
    flash_beats: int
    completed: frozenset[str] = frozenset()
    topic_interface: bool = False

    @classmethod
    def from_runtime(
        cls,
        *,
        flash_beats: int,
        completed: Sequence[str] = (),
        topic_interface: bool = False,
    ) -> "RyuyaCafeStateInput":
        return cls(
            flash_beats=max(0, int(flash_beats or 0)),
            completed=frozenset(str(item) for item in completed),
            topic_interface=bool(topic_interface),
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


def ryuya_topic_interface(snapshot: ScenePolicyInput) -> bool:
    """Detect a player-visible seam for naturally deepening the cafe conversation."""
    chunks: list[str] = []
    if snapshot.player_speech:
        chunks.append(snapshot.player_speech)
    if snapshot.player_action:
        chunks.append(snapshot.player_action)
    for item in reversed(snapshot.recent_history):
        if item.role != "player":
            continue
        text = item.text.strip()
        if text:
            chunks.append(text)
        if len(chunks) >= 3:
            break
    blob = re.sub(r"\s+", "", "".join(chunks))
    if not blob:
        return False
    return any(marker in blob for marker in _RYUYA_TOPIC_INTERFACE_MARKERS)


def evaluate_ryuya_cafe_state(snapshot: RyuyaCafeStateInput) -> ScenePolicyOutput:
    """Classify only the cafe desire-ladder phase; wording and state writes stay outside."""
    done = snapshot.completed
    beats = snapshot.flash_beats
    early_deepen = snapshot.topic_interface and beats >= 1
    if "RP4" in done:
        phase = "farewell"
    elif "RP3" in done:
        phase = "post_entrust_gift"
    elif "RP2" in done:
        phase = "entrust_clear"
    elif beats >= 2 or early_deepen:
        phase = "deepen"
    elif beats >= 1:
        phase = "banter"
    else:
        phase = "opening"
    return ScenePolicyOutput(proposals=(f"ryuya_cafe_phase:{phase}",))


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



def c16_milktea_disposition(snapshot: ScenePolicyInput) -> str:
    """Classify only explicit cafe acceptance/refusal from observable player input."""
    compact = re.sub(r"\s+", "", snapshot.player_public_text)
    accept = ("一起去", "我也去", "跟你们去", "去喝", "去奶茶店", "好啊", "可以")
    decline = ("不去", "不跟", "不用了", "别跟他去", "不想去", "不喝")
    if any(token in compact for token in decline):
        if any(token in compact for token in ("斑驳", "雨璇", "她们", "两个女生", "我们不")):
            return "girls_declined"
        return "player_declined"
    if any(token in compact for token in accept):
        return "accepted"
    return "undecided"


def c16_counter_encounter_diversion(snapshot: ScenePolicyInput) -> str:
    """Classify an observable action that diverts the later counter encounter."""
    compact = re.sub(r"\s+", "", snapshot.player_public_text)
    if not compact:
        return "undecided"
    girls = ("女生", "她们", "两人", "斑驳", "雨璇")
    redirect = ("另一条街", "另一家", "换一家", "带她们走", "带两人走", "别去那家", "离开校门")
    if any(token in compact for token in girls) and any(token in compact for token in redirect):
        return "girls_redirected"
    zhang_block = ("拦住张尘", "拦住那个男人", "阻止他接触", "不让他跟", "别跟过去")
    if any(token in compact for token in zhang_block):
        return "zhangchen_blocked"
    return "undecided"


def c16_shop_follow_disposition(snapshot: ScenePolicyInput) -> str:
    """Resolve only explicit shop-position choices; silence never means entry."""
    text = re.sub(r"\s+", "", snapshot.player_public_text)
    if not text:
        return "wait"
    leave_tokens = ("离开这里", "离开场景", "去别处", "去别的地方", "直接回家", "我先走了")
    if any(token in text for token in leave_tokens):
        return "left_scene"
    zhang_follow_tokens = (
        "跟上张尘", "跟着张尘", "跟上那个年轻男人", "跟着那个年轻男人",
        "跟上那男人", "跟着那男人", "跟上他", "跟着他",
    )
    if any(token in text for token in zhang_follow_tokens):
        return "follow_zhangchen"
    outside_tokens = ("不进去", "留在校门口", "待在校门口", "留在门外", "待在门外", "门外等")
    if any(token in text for token in outside_tokens):
        return "stay_outside"
    enter_tokens = ("跟进店", "跟进去", "进奶茶店", "走进店", "进店里", "到取餐口")
    observer_tokens = ("旁观", "旁边看", "只看", "不加入", "保持距离", "外围", "取餐口")
    if any(token in text for token in enter_tokens) and any(token in text for token in observer_tokens):
        return "inside_observer"
    join_tokens = ("加入他们", "加入你们", "一起坐", "一起吃", "上前打招呼", "主动加入")
    if any(token in text for token in enter_tokens) and any(token in text for token in join_tokens):
        return "join_request"
    return "undecided"


def c16_gate_disposition(snapshot: ScenePolicyInput) -> str:
    """The gate camera choice shares the explicit shop-follow vocabulary."""
    return c16_shop_follow_disposition(snapshot)


def c16_table_follow_disposition(snapshot: ScenePolicyInput) -> str:
    """Resolve the counter-to-table move without treating thought as movement."""
    text = re.sub(r"\s+", "", snapshot.player_public_text)
    if not text:
        return "wait"
    stay_tokens = ("留在取餐口", "待在取餐口", "站在取餐口", "不上楼", "不跟上楼")
    if any(token in text for token in stay_tokens):
        return "stay_counter"
    table_tokens = ("跟上楼", "跟到楼上", "上楼", "旁桌", "落座区")
    observer_tokens = ("旁桌", "继续看", "旁观", "不加入", "保持距离", "外围")
    if any(token in text for token in table_tokens) and any(token in text for token in observer_tokens):
        return "table_observer"
    join_tokens = ("一起坐", "坐到他们", "加入他们", "加入你们", "同桌")
    if any(token in text for token in table_tokens) and any(token in text for token in join_tokens):
        return "join_request"
    return "undecided"


def c16_subtle_peripheral_watch(snapshot: ScenePolicyInput) -> bool:
    """Low-salience peripheral observation that should not be broadcast to all actors."""
    speech = snapshot.player_speech.strip()
    action = snapshot.player_action.strip()
    if speech or not action:
        return False
    quiet_markers = ("看着", "观察", "围观", "旁观", "远远", "站在旁边", "站在一边", "不动")
    salient_markers = ("上前", "靠近", "走过去", "拦住", "拍", "喊", "叫住", "挥手", "挡住", "拉住")
    return any(marker in action for marker in quiet_markers) and not any(
        marker in action for marker in salient_markers
    )


def c16_overt_intervention(snapshot: ScenePolicyInput) -> bool:
    """Minimal deterministic evidence that the player openly enters the interaction."""
    speech = snapshot.player_speech.strip()
    action = snapshot.player_action.strip()
    if any(marker in action for marker in ("上前", "靠近", "走过去", "拦住", "插话", "解围", "护住", "制止")):
        return True
    return bool(
        speech
        and any(marker in speech for marker in ("我叫", "我是", "你们没事吧", "别骚扰", "想做什么"))
    )


def evaluate_c16(snapshot: ScenePolicyInput) -> ScenePolicyOutput:
    """Return C16 evidence/classification proposals without mutating runtime authority."""
    if snapshot.scene_id not in {"CARD_16ZHONG_GATE", "CARD_MILKTEA_WATCH"}:
        return ScenePolicyOutput()

    evidence: list[str] = []
    proposals: list[str] = []

    if snapshot.scene_id == "CARD_16ZHONG_GATE":
        if c16_subtle_peripheral_watch(snapshot):
            evidence.append("c16_subtle_peripheral_watch")
        if c16_overt_intervention(snapshot):
            evidence.append("c16_overt_intervention")

        diversion = c16_counter_encounter_diversion(snapshot)
        proposals.append(f"c16_counter_encounter_diversion:{diversion}")
        cafe = (
            c16_milktea_disposition(snapshot)
            if diversion == "undecided"
            else "undecided"
        )
        proposals.append(f"c16_milktea_disposition:{cafe}")
        proposals.append(
            f"c16_shop_follow_disposition:{c16_shop_follow_disposition(snapshot)}"
        )

    if snapshot.scene_id == "CARD_MILKTEA_WATCH":
        proposals.append(
            f"c16_table_follow_disposition:{c16_table_follow_disposition(snapshot)}"
        )

    return ScenePolicyOutput(
        evidence=tuple(evidence),
        proposals=tuple(proposals),
    )



def select_pending_canon_segment(
    snapshot: CanonSelectionInput,
) -> CanonSegmentSelection | None:
    """Select the first eligible after-stop segment without touching runtime state."""
    if not snapshot.pending_stop:
        return None
    outcome_by_decision = dict(snapshot.decision_outcomes)
    for segment in snapshot.segments:
        if not segment.segment_id or segment.segment_id in snapshot.completed_segments:
            continue
        if segment.trigger != "after_stop":
            continue
        if segment.after_stop != snapshot.pending_stop:
            continue
        if not segment.requires_branch.issubset(snapshot.branch_progress):
            continue
        if (
            segment.requires_autonomous_decisions
            and not segment.requires_autonomous_decisions.issubset(snapshot.resolved_decisions)
        ):
            continue
        if any(
            outcome_by_decision.get(decision_id) != expected
            for decision_id, expected in segment.requires_autonomous_outcomes
        ):
            continue
        return CanonSegmentSelection(
            segment_id=segment.segment_id,
            auto_continue=segment.auto_continue,
        )
    return None


def flashback_handoff_ready(snapshot: FlashbackHandoffInput) -> bool:
    """Only classify handoff readiness; pendant/world settlement stays outside policy."""
    return bool(
        snapshot.prologue_active
        and snapshot.has_return_frame
        and snapshot.all_must_happen_complete
    )

def proposal_value(
    output: ScenePolicyOutput,
    key: str,
    *,
    default: str = "undecided",
) -> str:
    """Read one opaque proposal value without giving the caller scene-specific logic."""
    prefix = f"{key}:"
    for proposal in output.proposals:
        if proposal.startswith(prefix):
            return proposal[len(prefix):]
    return default

def evaluate(snapshot: ScenePolicyInput) -> ScenePolicyOutput:
    """Dispatch a pure snapshot to the scene policy known to this module."""
    if snapshot.scene_id == "OPENING_TIANANMEN_002":
        return evaluate_tiananmen(snapshot)
    if snapshot.scene_id in {"CARD_16ZHONG_GATE", "CARD_MILKTEA_WATCH"}:
        return evaluate_c16(snapshot)
    return ScenePolicyOutput()
