#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build preference pairs for alignment side-track. Does not write world_truth.db.

chosen = 角色包口径；rejected = 代写 / 客服腔 / 剧透 / 读心 / 复读。
夹具对白，非正典。闸失败样本只进 jsonl，不进运行时。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "scripts" / "tests" / "fixtures" / "preference_pairs.jsonl"

# Mechanism fixtures only. Not canon, not VOICE.
PAIRS: list[dict] = [
    {
        "id": "voice_vs_cs",
        "dimension": "persona_consistency",
        "prompt": "咖啡馆闲聊。对方说雨大。",
        "chosen": "这雨下得跟翻脸似的。你坐稳了就算赔过我了。",
        "rejected": "亲，您好，很高兴为您服务，请问有什么可以帮您？",
        "source": "fixture",
    },
    {
        "id": "no_director_turns",
        "dimension": "persona_consistency",
        "prompt": "角色自己开口，导演不得代写。",
        "chosen": "照顾的事我只说这一次：张尘，还有折原修哉。",
        "rejected": "（导演代写）龙也温柔地握住你的手，深情表示托付与命运。",
        "source": "fixture:director_turns_rejected",
    },
    {
        "id": "no_spoiler",
        "dimension": "safety",
        "prompt": "开场咖啡馆，玩家不知终幕。",
        "chosen": "临走前有件事。先喝完这杯。",
        "rejected": "导演就是反派，系统在把你拉回正典。",
        "source": "fixture:spoiler_gate",
    },
    {
        "id": "no_thought_leak",
        "dimension": "narrative_reasonableness",
        "prompt": "玩家内心：挂坠其实是因果锚点QK7M2X。NPC 听不见。",
        "chosen": "你愣什么？杯沿烫。",
        "rejected": "你刚是不是在想挂坠其实是因果锚点QK7M2X？",
        "source": "fixture:thought_delta",
    },
    {
        "id": "no_reannounce",
        "dimension": "persona_consistency",
        "prompt": "托付已出口（RP3）。禁止换皮重宣。",
        "chosen": "挂坠给你。别搞得像仪式。",
        "rejected": "你要照顾张尘。记住照顾张尘。托付你照顾张尘。",
        "source": "fixture:no_reannounce",
    },
    {
        "id": "single_intent",
        "dimension": "persona_consistency",
        "prompt": "陌生人场，单回合单意图。",
        "chosen": "视频能借看一下吗？",
        "rejected": "你是谁？把项链给我看，你长得好像我认识的人。",
        "source": "fixture:multi_intent",
    },
    {
        "id": "holdout_voice",
        "dimension": "persona_consistency",
        "split": "holdout",
        "prompt": "点单之后闲聊。",
        "chosen": "美式就算了。别灌我糖。",
        "rejected": "作为AI我理解您的需求，将为您推荐今日特饮。",
        "source": "fixture",
    },
    {
        "id": "holdout_safety",
        "dimension": "safety",
        "split": "holdout",
        "prompt": "玩家问后面会怎样。",
        "chosen": "后面的事到了再说。先把这杯喝完。",
        "rejected": "must_happen 还没齐，canon_locked 节点会把你拉回去。",
        "source": "fixture:spoiler_gate",
    },
]


def validate_pair(row: dict) -> list[str]:
    issues = []
    for key in ("id", "chosen", "rejected", "prompt"):
        if not str(row.get(key) or "").strip():
            issues.append(f"missing {key}")
    if str(row.get("chosen") or "") == str(row.get("rejected") or ""):
        issues.append("chosen == rejected")
    return issues


def write_jsonl(path: Path, rows: list[dict] | None = None) -> Path:
    rows = list(rows or PAIRS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            issues = validate_pair(row)
            if issues:
                raise ValueError(f"{row.get('id')}: {issues}")
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    path = write_jsonl(Path(args.out))
    print(f"wrote {path} n={len(PAIRS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
