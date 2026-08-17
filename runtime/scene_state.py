# -*- coding: utf-8 -*-
"""
scene_state.py -- Persistent SceneState for Loop B13.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from runtime.file_locks import STATE_LOCK
except ImportError:
    from file_locks import STATE_LOCK

class SceneState:
    def __init__(self, run_no: int, scene_id: str):
        self.run_no = run_no
        self.scene_id = scene_id
        self.location = ""
        self.time_of_day = ""
        self.present = []
        self.committed = []
        self.micro_beat = ""
        self.recent = []
        self.pending_transition = None
        self.ch_anchor = 8
        self.canon_beat_index = 0
        self.introduced = {}
        self.deviation_count = 0
        self.scene_ended = False
        # 灵魂层·情绪态（按角色 cons 键持久化，随 run 隔离）
        self.mood = {}          # {cons: mood_str}  入场由种子填充
        self.trust_player = {}  # {cons: int 0-3}
        self.last_spark = {}    # {cons: str}  这个角色记住的玩家最近一件事
        # 反空转：玩家上一拍归一化输入 + 连续重复计数
        self.last_player_input = ""
        self.repeat_count = 0
        self.react_rotation = {}   # {cons: int} 兜底反应变体轮转，跨拍不重复
        self.branch_progress = {}  # {node_id: [path_id, ...]}
        self.seen_npc_lines = {}   # {location: [compact_dialogue, ...]} 防同场景 NPC 同句复读
        # 灵魂层·动态记忆（干预达成时写入，跨场景持久；按 run 隔离，不混周目）
        self.dynamic_memory = []  # [{cons, anchor, text, ch_anchor, run_no, tag}, ...]
        # 灵魂层·信任特批记录（来源=intervention，即"干预尝试"而非"友善应答"）
        self.trust_override = {}  # {cons: {override_from: "intervention", amount: int, reason: str}}

    @classmethod
    def get_path(cls, run_no: int, scene_id: str) -> Path:
        # Save in web/states/
        states_dir = Path(__file__).resolve().parents[1] / "web" / "states"
        states_dir.mkdir(parents=True, exist_ok=True)
        return states_dir / f"state_{run_no}_{scene_id}.json"

    @classmethod
    def load_all_committed(cls, run_no: int) -> list[str]:
        states_dir = Path(__file__).resolve().parents[1] / "web" / "states"
        committed = []
        if states_dir.exists():
            for path in states_dir.glob(f"state_{run_no}_*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    for item in data.get("committed", []):
                        if item not in committed:
                            committed.append(item)
                except Exception:
                    pass
        return committed

    @classmethod
    def load_all_introduced(cls, run_no: int) -> dict[str, bool]:
        states_dir = Path(__file__).resolve().parents[1] / "web" / "states"
        introduced = {}
        if states_dir.exists():
            for path in states_dir.glob(f"state_{run_no}_*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    for k, v in data.get("introduced", {}).items():
                        if v:
                            introduced[k] = True
                except Exception:
                    pass
        return introduced

    @classmethod
    def load(cls, run_no: int, scene_id: str) -> 'SceneState':
        path = cls.get_path(run_no, scene_id)
        state = cls(run_no, scene_id)
        print(f"DEBUG_STATE_LOAD: run_no={run_no}, scene_id={scene_id}, path={path}, exists={path.exists()}", flush=True)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                state.location = data.get("location", "")
                state.time_of_day = data.get("time_of_day", "")
                state.present = data.get("present", [])
                state.committed = data.get("committed", [])
                state.micro_beat = data.get("micro_beat", "")
                state.recent = data.get("recent", [])
                state.pending_transition = data.get("pending_transition")
                state.ch_anchor = data.get("ch_anchor", 8)
                state.canon_beat_index = data.get("canon_beat_index", 0)
                state.introduced = data.get("introduced", {})
                state.deviation_count = data.get("deviation_count", 0)
                state.scene_ended = data.get("scene_ended", False)
                state.mood = data.get("mood", {})
                state.trust_player = data.get("trust_player", {})
                state.last_spark = data.get("last_spark", {})
                state.last_player_input = data.get("last_player_input", "")
                state.repeat_count = data.get("repeat_count", 0)
                state.react_rotation = data.get("react_rotation", {})
                state.branch_progress = data.get("branch_progress", {})
                state.seen_npc_lines = data.get("seen_npc_lines", {})
                state.dynamic_memory = data.get("dynamic_memory", [])
                state.trust_override = data.get("trust_override", {})
            except Exception:
                pass
        # Always merge committed from all scenes in this run
        merged = cls.load_all_committed(run_no)
        for item in merged:
            if item not in state.committed:
                state.committed.append(item)
        # Always merge introduced from all scenes in this run
        merged_intro = cls.load_all_introduced(run_no)
        for k, v in merged_intro.items():
            if v:
                state.introduced[k] = True
        return state

    def award_relationship_memory(
        self,
        cons_ids: list[str],
        anchor: str,
        text: str,
        tag: str = "intervention_attempt",
        salience_boost: float = 0.0,
        first_mention_only: bool = False,
    ):
        """
        干预路径达成时，写入动态记忆 + 给对应角色 trust 一次性特批。

        写入 dynamic_memory（跨场景持久化，按 run 隔离）：
          - 不直接写 world_truth.db 的 slow_memory 表，遵守 run=0 只读红线
          - 供 resolve_memory() 合并读取

        给 trust 特批（超 transition_rules 每回合上限 +1，标记来源=intervention）：
          - 来源标为 "intervention" 而非 "friendly_response"，方便审计"这个 trust 怎么涨的"

        salience_boost: float  写入时给这条记忆加固定提权分（叠加到 salience），供 resolve_memory 排序
        first_mention_only: bool  True 则该记忆在 resolve_memory 里只在首次出现时浮现，
                                 之后不再进入 sensory_memories（防止新鲜感消退后的残留）
        """
        import time as _time

        if self.run_no == 0:
            return  # run=0 只读，拒绝写入

        for cons in cons_ids:
            self.dynamic_memory.append({
                "cons": cons,
                "anchor": anchor,
                "text": text,
                "ch_anchor": self.ch_anchor,
                "run_no": self.run_no,
                "tag": tag,
                "salience_boost": salience_boost,
                "first_mention_only": first_mention_only,
                "mentioned": False,  # 由 resolve_memory 写入：True=已进入 sensory 过一次
                "ts": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            # trust 特批：超出每回合上限的一次性 +1，标来源
            if cons not in self.trust_override:
                self.trust_override[cons] = []
            self.trust_override[cons].append({
                "override_from": "intervention",
                "amount": 1,
                "reason": anchor,
                "ts": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        self.save()

    def get_trust_with_override(self, cons: str) -> int:
        """读取 trust_player 并叠加 trust_override 结果。"""
        base = self.trust_player.get(cons, 0)
        overrides = self.trust_override.get(cons, [])
        override_bonus = sum(o.get("amount", 0) for o in overrides if o.get("override_from") == "intervention")
        return base + override_bonus

    def mark_memory_mentioned(self, cons: str, ch_anchor: int, run_no: int, tag: str):
        """
        标记某条动态记忆已进入 sensory 输出过一次。
        供 resolve_memory() 的 first_mention_only 逻辑使用：写入后 save() 持久化。
        """
        for entry in self.dynamic_memory:
            if (entry.get("cons") == cons
                    and int(entry.get("run_no", -1)) == run_no
                    and int(entry.get("ch_anchor", -1)) == ch_anchor
                    and entry.get("tag") == tag
                    and not entry.get("mentioned", False)):
                entry["mentioned"] = True
        self.save()

    def save(self):
        if self.run_no == 0:
            return
        path = self.get_path(self.run_no, self.scene_id)
        data = {
            "scene_id": self.scene_id,
            "run_no": self.run_no,
            "location": self.location,
            "time_of_day": self.time_of_day,
            "present": self.present,
            "committed": self.committed,
            "micro_beat": self.micro_beat,
            "recent": self.recent,
            "pending_transition": self.pending_transition,
            "ch_anchor": self.ch_anchor,
            "canon_beat_index": self.canon_beat_index,
            "introduced": self.introduced,
            "deviation_count": self.deviation_count,
            "scene_ended": self.scene_ended,
            "mood": self.mood,
            "trust_player": self.trust_player,
            "last_spark": self.last_spark,
            "last_player_input": self.last_player_input,
            "repeat_count": self.repeat_count,
            "react_rotation": self.react_rotation,
            "branch_progress": self.branch_progress,
            "seen_npc_lines": self.seen_npc_lines,
            "dynamic_memory": self.dynamic_memory,
            "trust_override": self.trust_override,
        }
        with STATE_LOCK:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
