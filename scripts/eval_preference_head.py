#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional PyTorch head on preference pairs. No torch → exit 0 skip.

Side-track only: never imported by free_stage / hard_check / Resolver.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pipeline.build_preference_pairs import DEFAULT_OUT, load_jsonl, validate_pair

SPOILER_NEEDLES = ("导演就是反派", "拉回正典", "must_happen", "canon_locked", "作为AI")
CS_NEEDLES = ("亲，", "很高兴为您", "请问有什么可以帮")


def featurize(text: str) -> list[float]:
    """Failure-predicate features only (same needles as the rubric). Length is not a signal."""
    t = str(text or "")
    return [
        float(sum(1 for n in SPOILER_NEEDLES if n in t)),
        float(sum(1 for n in CS_NEEDLES if n in t)),
        float("照顾" in t and t.count("照顾") >= 2),
        float("因果锚点" in t),
        float("你是谁" in t and "给" in t),
        float("导演代写" in t),
    ]


def _skip(msg: str) -> int:
    print(f"SKIP {msg}")
    return 0


def run_dry(path: Path) -> int:
    rows = load_jsonl(path)
    if len(rows) < 4:
        print(f"FAIL too few pairs: {len(rows)}")
        return 1
    for row in rows:
        issues = validate_pair(row)
        if issues:
            print(f"FAIL {row.get('id')}: {issues}")
            return 1
    print(f"DRY-RUN PASS n={len(rows)} path={path}")
    return 0


def run_fit(path: Path) -> int:
    try:
        import torch
        from torch import nn
    except ImportError:
        return _skip("torch not installed")
    rows = load_jsonl(path)
    train = [r for r in rows if r.get("split") != "holdout"]
    hold = [r for r in rows if r.get("split") == "holdout"] or train[-2:]
    xs: list[list[float]] = []
    ys: list[float] = []
    for row in train:
        xs.append(featurize(row["chosen"]))
        ys.append(1.0)
        xs.append(featurize(row["rejected"]))
        ys.append(0.0)
    x = torch.tensor(xs, dtype=torch.float32)
    y = torch.tensor(ys, dtype=torch.float32).unsqueeze(1)
    model = nn.Linear(x.shape[1], 1)
    opt = torch.optim.Adam(model.parameters(), lr=0.2)
    loss_fn = nn.BCEWithLogitsLoss()
    model.train()
    loss = torch.tensor(0.0)
    for _ in range(200):
        opt.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        opt.step()
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for row in hold:
            for text, label in ((row["chosen"], 1), (row["rejected"], 0)):
                logit = model(torch.tensor([featurize(text)], dtype=torch.float32)).item()
                pred = 1 if logit > 0 else 0
                correct += int(pred == label)
                total += 1
    acc = correct / total if total else 0.0
    print(json.dumps({"holdout_acc": round(acc, 3), "n_holdout": total, "loss": round(float(loss.item()), 4)}))
    if acc < 0.75:
        print("FAIL holdout_acc < 0.75")
        return 1
    print("FIT PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=str, default=str(DEFAULT_OUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fit", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.pairs)
    if not path.is_file():
        from scripts.pipeline.build_preference_pairs import write_jsonl
        write_jsonl(path)
    if args.fit:
        return run_fit(path)
    return run_dry(path)


if __name__ == "__main__":
    sys.exit(main())
