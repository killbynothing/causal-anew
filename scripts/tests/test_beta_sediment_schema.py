# -*- coding: utf-8 -*-
"""β schema + settle + soft-field guards (stage 4 / S6)."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.softening_params import (  # noqa: E402
    KIND_WEIGHT,
    S_MAX_DEFAULT,
    W_PRECEDENT,
    W_SCAR,
)

sys.path.insert(0, str(ROOT / "scripts"))
from settle_run import soft_field, settle  # noqa: E402

DB = ROOT / "data" / "world_truth.db"

REQUIRED_RUN_META = {
    "run",
    "parent_run",
    "kind",
    "fork_event",
    "inherit_level",
    "player_line",
    "opening_id",
    "player_profile_hash",
    "opened_at",
    "closed_at",
    "final_delta_summary",
}
REQUIRED_SEDIMENT = {
    "sid",
    "node_id",
    "kind",
    "payload",
    "cons_id",
    "weight",
    "src_run",
    "src_delta",
    "revoked",
    "created_at",
}


class TestBetaSedimentSchema(unittest.TestCase):
    def test_weights_match_human_cut(self):
        self.assertEqual(W_PRECEDENT, 0.25)
        self.assertEqual(W_SCAR, 0.10)
        self.assertEqual(S_MAX_DEFAULT, 0.6)
        self.assertEqual(KIND_WEIGHT["precedent"], 0.25)
        self.assertEqual(KIND_WEIGHT["scar"], 0.10)
        self.assertEqual(KIND_WEIGHT["unlock"], 0.0)
        self.assertEqual(KIND_WEIGHT["witness"], 0.0)

    def test_soft_field_bounded_and_diminishing(self):
        s1 = soft_field([0.25])
        s2 = soft_field([0.25, 0.25])
        s3 = soft_field([0.25, 0.25, 0.25, 0.25, 0.25, 0.25])
        self.assertAlmostEqual(s1, 0.25)
        self.assertGreater(s2, s1)
        self.assertLessEqual(s3, S_MAX_DEFAULT)
        self.assertLess(s3, 1.0)

    def test_threshold_from_S_run1_unchanged_and_softens(self):
        from runtime.softening_params import (
            compute_S,
            effective_combine_threshold,
            threshold_from_S,
        )

        self.assertAlmostEqual(threshold_from_S(2, 1, 0.0), 2.0)
        self.assertAlmostEqual(threshold_from_S(2, 1, 1.0), 1.0)
        self.assertLess(threshold_from_S(2, 1, 0.25), 2.0)
        # Empty sediment on live db ⇒ S≡0
        self.assertEqual(compute_S(DB, "NODE-085-TIANJIN"), 0.0)
        contract = {
            "node_id": "NODE-085-TIANJIN",
            "combine_threshold": 2,
            "softening": {"floor": 1, "per_delta": 3},
        }
        self.assertEqual(
            effective_combine_threshold(contract, 0, node_id="NODE-085-TIANJIN", db_path=DB),
            2.0,
        )
        soft = effective_combine_threshold(
            contract, 0, node_id="NODE-085-TIANJIN", sediment_S=0.25
        )
        self.assertEqual(soft, 1.0)  # floor(1.75)=1
        # Within-run still stacks
        self.assertEqual(
            effective_combine_threshold(
                contract, 3, node_id="NODE-085-TIANJIN", sediment_S=0.0
            ),
            1.0,
        )

    def test_director_effective_threshold_uses_S(self):
        sys.path.insert(0, str(ROOT / "c1_web_console"))
        import director

        contract = {
            "node_id": "NODE-085-TIANJIN",
            "combine_threshold": 2,
            "softening": {"floor": 1, "per_delta": 3},
        }
        self.assertEqual(director.effective_threshold(contract, 0, node_id="NODE-085-TIANJIN"), 2)
        self.assertEqual(
            director.effective_threshold(contract, 0, node_id="NODE-085-TIANJIN", sediment_S=0.5),
            1,
        )

    def test_tables_present_with_cols(self):
        self.assertTrue(DB.is_file(), "world_truth.db missing")
        con = sqlite3.connect(str(DB))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("run_meta", tables)
        self.assertIn("delta_sediment", tables)
        rm = {r[1] for r in con.execute("PRAGMA table_info(run_meta)")}
        ds = {r[1] for r in con.execute("PRAGMA table_info(delta_sediment)")}
        self.assertEqual(REQUIRED_RUN_META - rm, set())
        self.assertEqual(REQUIRED_SEDIMENT - ds, set())
        con.close()

    def test_settle_rejects_fixed_bottom_and_is_deterministic(self):
        # isolated temp db cloned schema + minimal rows
        src = sqlite3.connect(str(DB))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.db"
            dst = sqlite3.connect(str(path))
            for ddl in src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name IN ('run_meta','delta_sediment','delta_ledger','causal_constants') "
                "AND sql IS NOT NULL"
            ):
                dst.execute(ddl[0])
            # copy causal_constants rows
            cols = [r[1] for r in src.execute("PRAGMA table_info(causal_constants)")]
            for row in src.execute("SELECT * FROM causal_constants"):
                placeholders = ",".join("?" * len(row))
                dst.execute(
                    f"INSERT INTO causal_constants ({','.join(cols)}) VALUES ({placeholders})",
                    row,
                )
            dst.execute(
                "INSERT INTO run_meta (run, parent_run, kind, inherit_level, player_line, opened_at) "
                "VALUES (1, 0, 'fresh', 0, 'a_qi', '2026-08-03T00:00:00Z')"
            )
            dst.execute(
                "INSERT INTO delta_ledger (delta_id, run, node_id, description, converged, emo_tag, src_event) "
                "VALUES (1, 1, 'E_PLAYER_ENTRUST', 'try soften entrust', 0, 'grief', NULL)"
            )
            dst.execute(
                "INSERT INTO delta_ledger (delta_id, run, node_id, description, converged, emo_tag, src_event) "
                "VALUES (2, 1, 'N.hospital.ch16', 'detour', 0, 'anxiety', NULL)"
            )
            dst.commit()

            try:
                a = settle(dst, 1, apply=True)
                b = settle(dst, 1, apply=True)
                self.assertEqual(a["n_rejected_fixed"], 1)
                self.assertEqual(a["n_sediment"], 1)
                self.assertEqual(a["sediment"][0]["kind"], "scar")
                self.assertEqual(a["sediment"][0]["weight"], W_SCAR)
                n = dst.execute(
                    "SELECT COUNT(*) FROM delta_sediment WHERE src_run=1"
                ).fetchone()[0]
                self.assertEqual(n, 1)
                self.assertEqual(a["n_sediment"], b["n_sediment"])
            finally:
                dst.close()
                src.close()
        # TemporaryDirectory cleans after connections closed
        return

if __name__ == "__main__":
    unittest.main()
