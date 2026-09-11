# -*- coding: utf-8 -*-
"""Knife 5 Test Suite: Read Scars (Cross-run sediment & threshold softening)."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.scars_reader import (
    compute_node_effective_threshold,
    read_run_scars,
)
from runtime.softening_params import KIND_WEIGHT, S_MAX_DEFAULT, W_PRECEDENT, W_SCAR
from scripts.settle_run import settle


DDL_SCHEMA = """
CREATE TABLE causal_constants (
    const_id TEXT PRIMARY KEY,
    name TEXT,
    dependency_chain TEXT
);
CREATE TABLE delta_sediment (
    sid INTEGER PRIMARY KEY,
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    cons_id TEXT,
    weight REAL NOT NULL,
    src_run INTEGER NOT NULL,
    src_delta TEXT NOT NULL,
    revoked INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


class TestReadScars(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_truth.db"
        con = sqlite3.connect(str(self.db_path))
        con.executescript(DDL_SCHEMA)
        # Fixed-bottom node
        con.execute(
            "INSERT INTO causal_constants (const_id, name, dependency_chain) "
            "VALUES ('E_PLAYER_ENTRUST', '??', '[\"E_PLAYER_ENTRUST\"]')"
        )
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run1_reads_zero_scars(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO delta_sediment (node_id, kind, payload, weight, src_run, src_delta, created_at) "
            "VALUES ('NODE-085-TIANJIN', 'scar', '{}', 0.10, 1, 'd1', '2026-08-03')"
        )
        con.commit()
        con.close()

        res = read_run_scars(self.db_path, "NODE-085-TIANJIN", current_run=1)
        self.assertEqual(res["run"], 1)
        self.assertEqual(res["S"], 0.0)
        self.assertEqual(res["n_scars"], 0)
        self.assertFalse(res["has_scars"])
        self.assertIsNone(res["ambient_scar"])

    def test_run2_reads_run1_sediment(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO delta_sediment (node_id, kind, payload, weight, src_run, src_delta, created_at) "
            "VALUES ('NODE-085-TIANJIN', 'scar', '{}', 0.10, 1, 'd1', '2026-08-03')"
        )
        con.commit()
        con.close()

        res = read_run_scars(self.db_path, "NODE-085-TIANJIN", current_run=2)
        self.assertEqual(res["run"], 2)
        self.assertEqual(res["S"], 0.1)
        self.assertEqual(res["n_scars"], 1)
        self.assertTrue(res["has_scars"])
        self.assertTrue(len(res["ambient_scar"]) > 0)
        self.assertTrue(any(res["ambient_scar"].startswith(prefix) for prefix in ("\u7a7a\u6c14", "\u96e8\u58f0", "\u7a97\u5916")))

    def test_fixed_bottom_node_never_softens(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO delta_sediment (node_id, kind, payload, weight, src_run, src_delta, created_at) "
            "VALUES ('E_PLAYER_ENTRUST', 'scar', '{}', 0.50, 1, 'd1', '2026-08-03')"
        )
        con.commit()
        con.close()

        res = read_run_scars(self.db_path, "E_PLAYER_ENTRUST", current_run=2)
        self.assertTrue(res["is_fixed_bottom"])
        self.assertEqual(res["S"], 0.0)
        self.assertFalse(res["has_scars"])

    def test_ambient_scar_no_leak(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO delta_sediment (node_id, kind, payload, weight, src_run, src_delta, created_at) "
            "VALUES ('NODE-085-TIANJIN', 'precedent', '{}', 0.25, 1, 'd1', '2026-08-03')"
        )
        con.commit()
        con.close()

        res = read_run_scars(self.db_path, "NODE-085-TIANJIN", current_run=2)
        scar_text = res["ambient_scar"]
        self.assertIsNotNone(scar_text)
        # H4 & E_SELF_REF checks: no leak of meta words
        for banned in ("\u5468\u76ee", "\u7cfb\u7edf", "AI", "\u73a9\u5bb6", "\u5267\u672c", "run", "player", "node"):
            self.assertNotIn(banned, scar_text)

    def test_effective_threshold_softening(self) -> None:
        contract = {
            "node_id": "NODE-085-TIANJIN",
            "combine_threshold": 2,
            "softening": {"floor": 1, "per_delta": 3},
        }
        # Run 1: no sediment -> threshold is 2.0
        eff1 = compute_node_effective_threshold(
            contract, 0, node_id="NODE-085-TIANJIN", db_path=self.db_path, current_run=1
        )
        self.assertEqual(eff1, 2.0)

        # Populate sediment from run 1
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO delta_sediment (node_id, kind, payload, weight, src_run, src_delta, created_at) "
            "VALUES ('NODE-085-TIANJIN', 'precedent', '{}', 0.25, 1, 'd1', '2026-08-03')"
        )
        con.commit()
        con.close()

        # Run 2: has precedent -> threshold softens to 1.0 (floor(1.75)=1)
        eff2 = compute_node_effective_threshold(
            contract, 0, node_id="NODE-085-TIANJIN", db_path=self.db_path, current_run=2
        )
        self.assertEqual(eff2, 1.0)

    def test_free_stage_session_reads_scars(self) -> None:
        from runtime.free_stage_prototype import FreeStageSession

        session1 = FreeStageSession(
            run_no=1,
            truth_db=self.db_path,
            autosave=False,
            load_existing=False,
        )
        self.assertEqual(session1.sediment_S, 0.0)
        self.assertFalse(session1.scar_info["has_scars"])

        payload = session1._state_payload()
        self.assertIn("sediment_S", payload)
        self.assertIn("scar_info", payload)
        self.assertEqual(payload["sediment_S"], 0.0)


if __name__ == "__main__":
    unittest.main()
