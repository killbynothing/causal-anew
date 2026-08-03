# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SERVER_DIR = ROOT / "c1_web_console"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from runtime import free_stage_prototype as proto
import server
import free_stage_prototype as server_proto


def test_step_session_matches_one_shot_selftest(tmp_path):
    config = {"api_key": "", "api_url": "", "model": "mock"}
    # Keep this equivalence probe inside the same unfinished scene state;
    # run_session deliberately appends an end marker once all source beats end.
    inputs = ["你好。", "你们叫什么？", "真纪去哪儿了？"]

    one_shot = proto.run_session(inputs, config, caller=proto.fixed_selftest_actor)
    session = proto.FreeStageSession(
        session_id="equivalence",
        state_dir=tmp_path,
        config=config,
        caller=proto.fixed_selftest_actor,
    )
    for item in inputs:
        session.step(item)
    stepped = session.result()

    assert stepped["completed"] == one_shot["completed"]
    assert stepped["issues"] == one_shot["issues"]
    assert proto.visible_transcript(stepped["history"]) == proto.visible_transcript(one_shot["history"])


def test_session_persists_and_resumes_after_process_restart(tmp_path):
    config = {"api_key": "", "api_url": "", "model": "mock"}
    first = proto.FreeStageSession(
        session_id="resume",
        state_dir=tmp_path,
        config=config,
        caller=proto.fixed_selftest_actor,
    )
    first.step("你好。")

    resumed = proto.FreeStageSession(
        session_id="resume",
        state_dir=tmp_path,
        config=config,
        caller=proto.fixed_selftest_actor,
    )
    assert resumed.completed == ["TM1"]
    assert resumed.card["scene_id"] == "OPENING_TIANANMEN_002"
    assert any("为什么都要长得这么高" in item.get("text", "") for item in resumed.history)

    resumed.step("可以，视频给你们看。")
    assert resumed.completed == ["TM1", "TM2"]


def test_server_free_stage_route_smoke_uses_new_endpoint(tmp_path):
    config = {"api_key": "", "api_url": "", "model": "mock"}
    res = server.handle_free_stage_request(
        {"op": "player_say", "session_id": "server-smoke", "player_input": "你好。"},
        config,
        state_dir=tmp_path,
        caller=proto.fixed_selftest_actor,
    )

    assert res["status"] == "ok"
    assert res["surface"]["scene"] == "天安门广场"
    assert res["session_id"] == "server-smoke"
    assert res["completed"] == ["TM1"]
    assert any(item["role"] == "npc" for item in res["turns"])
    assert json.loads((tmp_path / "server-smoke.json").read_text(encoding="utf-8"))["completed"] == ["TM1"]


def test_server_free_stage_accepts_text_alias(tmp_path):
    config = {"api_key": "", "api_url": "", "model": "mock"}
    res = server.handle_free_stage_request(
        {"op": "player_say", "session_id": "text-alias", "text": "你好。"},
        config,
        state_dir=tmp_path,
        caller=proto.fixed_selftest_actor,
    )

    assert res["completed"] == ["TM1"]
    stored = json.loads((tmp_path / "text-alias.json").read_text(encoding="utf-8"))
    assert stored["inputs"] == ["你好。"]


def test_server_free_stage_loads_experiment_config():
    cfg = server.load_free_stage_config()
    assert cfg["model"] == "deepseek-v4-flash"
    assert cfg["api_url"].endswith("/chat/completions")


def test_server_free_stage_default_uses_runtime_actor(monkeypatch=None):
    captured = {}
    old_session = server_proto.FreeStageSession

    class FakeSession:
        def __init__(self, **kwargs):
            captured["caller"] = kwargs.get("caller")
            self.session_id = kwargs.get("session_id")
            self.completed = []
            self.last_issues = []
            self.ended = False

        def surface(self):
            return {"scene": "天安门广场"}

    try:
        server_proto.FreeStageSession = FakeSession
        res = server.handle_free_stage_request(
            {"op": "start", "session_id": "default-caller"},
            {"api_key": "k", "api_url": "u", "model": "m"},
        )
    finally:
        server_proto.FreeStageSession = old_session

    assert res["status"] == "ok"
    assert captured["caller"] is None


def _run_directly():
    for name in sorted(n for n in globals() if n.startswith("test_")):
        fn = globals()[name]
        if "tmp_path" in fn.__code__.co_varnames:
            with tempfile.TemporaryDirectory() as tmp:
                fn(Path(tmp))
        else:
            fn()
        print(f"PASS {name}")


if __name__ == "__main__":
    _run_directly()
