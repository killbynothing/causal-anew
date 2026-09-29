#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import free_stage_prototype as proto
from runtime import run_lifecycle
from runtime.runtime_store import RuntimeStore, RuntimeStoreError
from web import server


def _card() -> Path:
    return ROOT / "runtime" / "free_stage_card_ryuya_prologue.json"


def _caller_should_not_run(*args, **kwargs):
    raise AssertionError("LLM/caller must not run while close is pending/closed")


def test_legacy_ended_without_receipt_recovers_as_closing():
    assert run_lifecycle.derive_state({"ended": True, "run_closed": False}) == run_lifecycle.CLOSING
    assert run_lifecycle.derive_state({"ended": True, "run_receipt": {"run": 1}}) == run_lifecycle.CLOSED


def test_runtime_store_atomic_save_and_corruption_are_strict():
    with tempfile.TemporaryDirectory() as tmp:
        store = RuntimeStore(tmp, "s")
        store.save({"version": 1})
        before = store.state_path.read_bytes()
        try:
            store.save({"version": 2}, failpoint="after_temp_write")
        except RuntimeStoreError:
            pass
        else:
            raise AssertionError("save failpoint must fail")
        assert store.state_path.read_bytes() == before
        assert store.load() == {"version": 1}
        assert not store.state_path.with_name(store.state_path.name + ".tmp").exists()

        store.state_path.write_text("{broken", encoding="utf-8")
        try:
            store.load()
        except RuntimeStoreError:
            pass
        else:
            raise AssertionError("corrupt snapshot must not look like a missing/new session")


def test_close_snapshot_failure_recovers_from_outbox_without_model():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        runtime_state = Path(tmp) / "runtime_state.db"
        session = proto.FreeStageSession(
            session_id="p1b-snapshot-fail",
            card_path=_card(),
            state_dir=state_dir,
            runtime_state_path=runtime_state,
            autosave=True,
            load_existing=False,
            caller=_caller_should_not_run,
        )
        session.save()
        original_save = session.runtime_store.save

        def fail_main_snapshot(*args, **kwargs):
            raise RuntimeStoreError("injected main snapshot failure")

        session.runtime_store.save = fail_main_snapshot
        assert session._mark_ended() is False
        assert session.runtime_store.load_commit_cursor().pending is not None
        disk = json.loads(session.runtime_store.state_path.read_text(encoding="utf-8"))
        assert disk.get("lifecycle_state") == run_lifecycle.OPEN
        session.runtime_store.save = original_save

        resumed = proto.FreeStageSession(
            session_id="p1b-snapshot-fail",
            card_path=_card(),
            state_dir=state_dir,
            runtime_state_path=runtime_state,
            autosave=True,
            load_existing=True,
            caller=_caller_should_not_run,
        )
        assert resumed.lifecycle_state == run_lifecycle.CLOSING
        result = resumed.step("不得进入模型")
        assert result["ended"] is True
        assert result["turns"] == []
        assert resumed.runtime_store.load_commit_cursor().pending is None


def test_close_failure_persists_closing_and_retries_without_model():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        runtime_state = Path(tmp) / "runtime_state.db"
        session = proto.FreeStageSession(
            session_id="p1b-close",
            card_path=_card(),
            state_dir=state_dir,
            runtime_state_path=runtime_state,
            autosave=True,
            load_existing=False,
            caller=_caller_should_not_run,
        )
        session.truth_db_path = Path(tmp) / "truth.db"

        with patch("runtime.end_run.close_run", side_effect=RuntimeError("db down")):
            assert session._mark_ended() is False
        assert session.lifecycle_state == run_lifecycle.CLOSING
        assert session.ended is False
        saved = json.loads(session.runtime_store.state_path.read_text(encoding="utf-8"))
        assert saved["lifecycle_state"] == run_lifecycle.CLOSING

        resumed = proto.FreeStageSession(
            session_id="p1b-close",
            card_path=_card(),
            state_dir=state_dir,
            runtime_state_path=runtime_state,
            autosave=True,
            load_existing=True,
            caller=_caller_should_not_run,
        )
        resumed.truth_db_path = Path(tmp) / "truth.db"
        receipt = {
            "run": resumed.run_no,
            "opening_id": resumed.opening_id,
            "closed_at": "2026-09-29T00:00:00Z",
            "done": [],
            "rejected_fixed": [],
            "n_delta": 0,
            "n_sediment": 0,
            "n_rejected_fixed": 0,
        }
        with patch("runtime.end_run.close_run", return_value=receipt):
            result = resumed.step("这句话不得进入模型")
        assert result["ended"] is True
        assert result["lifecycle_state"] == run_lifecycle.CLOSED
        assert result["turns"] == []
        assert resumed.inputs == []


def test_closed_run_refuses_mutating_methods_and_reset():
    with tempfile.TemporaryDirectory() as tmp:
        session = proto.FreeStageSession(
            session_id="p1b-closed",
            card_path=_card(),
            state_dir=Path(tmp) / "states",
            runtime_state_path=Path(tmp) / "runtime_state.db",
            autosave=False,
            load_existing=False,
            caller=_caller_should_not_run,
        )
        session._set_lifecycle_state(run_lifecycle.CLOSING)
        session._set_lifecycle_state(run_lifecycle.CLOSED)
        for name, fn in [
            ("start", session.start),
            ("reset", session.reset),
            ("skip_scene", session.skip_scene),
            ("advance_utterance", session.advance_utterance),
        ]:
            try:
                fn()
            except (RuntimeError, ValueError):
                pass
            else:
                raise AssertionError(f"{name} must not mutate a closed run")


def test_save_as_is_read_only_and_cannot_become_second_run_writer():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "states"
        source = proto.FreeStageSession(
            session_id="source",
            card_path=_card(),
            state_dir=state_dir,
            runtime_state_path=Path(tmp) / "runtime_state.db",
            autosave=True,
            load_existing=False,
            caller=_caller_should_not_run,
        )
        source.save()
        response = server.handle_free_stage_request(
            {"op": "save_as", "session_id": "source", "target_session_id": "copy"},
            {},
            state_dir=str(state_dir),
            caller=_caller_should_not_run,
        )
        assert response["status"] == "ok"
        assert response["write_mode"] == "snapshot_read_only"
        copied = json.loads((state_dir / "copy.json").read_text(encoding="utf-8"))
        assert copied["run_no"] == source.run_no
        assert copied["write_mode"] == "snapshot_read_only"
        assert copied["source_session_id"] == "source"

        blocked = server.handle_free_stage_request(
            {"op": "player_say", "session_id": "copy", "text": "继续"},
            {},
            state_dir=str(state_dir),
            caller=_caller_should_not_run,
        )
        assert blocked["status"] == "error"
        assert "read-only" in blocked["error"]


if __name__ == "__main__":
    test_legacy_ended_without_receipt_recovers_as_closing()
    test_runtime_store_atomic_save_and_corruption_are_strict()
    test_close_snapshot_failure_recovers_from_outbox_without_model()
    test_close_failure_persists_closing_and_retries_without_model()
    test_closed_run_refuses_mutating_methods_and_reset()
    test_save_as_is_read_only_and_cannot_become_second_run_writer()
    print("PASS test_run_lifecycle_p1b")
