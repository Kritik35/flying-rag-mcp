"""
tests/test_postfix_pilot_fail_closed_015.py

Contract verification suite for Stage 4.2.9 / ТЗ-015 Rev 1.1 (P15-01 .. P15-10).
Enforces fail-closed safety, scope protection, immediate fail-fast termination,
strict nonzero exit veto, empty retrieval rejection, and raw corpus result isolation.
"""

from __future__ import annotations
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.postfix_pilot_harness_015 import (
    preflight_check,
    execute_bounded_search,
    run_postfix_pilot,
    compare_ranks,
    save_separated_results,
    ISOLATED_CORPUS_ROOT,
    ISOLATED_CONFIG_PATH
)


class TestPostfixPilotFailClosed015(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fixture_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_p15_01_host_env_metadata_db_triggers_stop_scope(self):
        """P15-01 [P0]: Host env FLYING_RAG_METADATA_DB pointing to production triggers STOP_SCOPE; 0 calls."""
        prod_db_path = r"C:\RAG_Acer\data_imported\metadata.db"
        with patch.dict(os.environ, {"FLYING_RAG_METADATA_DB": prod_db_path}):
            report = preflight_check(custom_config_path=ISOLATED_CONFIG_PATH, allowed_fixture_root=ISOLATED_CORPUS_ROOT)
            self.assertFalse(report["checks_passed"])
            self.assertEqual(report["storage_scope"]["ISOLATED_COPY_VERIFIED"], "NO")
            self.assertTrue("STOP_SCOPE" in report["storage_scope"]["scope_check"])

            # Verify run_postfix_pilot stops before any child launch
            pilot = run_postfix_pilot(execute_approved_pilot=True, config_path=ISOLATED_CONFIG_PATH, allowed_fixture_root=ISOLATED_CORPUS_ROOT)
            self.assertEqual(pilot["attempted_calls"], 0)
            self.assertEqual(pilot["spawned_calls"], 0)
            self.assertEqual(pilot["actual_corpus_search_calls"], 0)
            self.assertEqual(pilot["overall_status"], "PREFLIGHT_CHECKS_FAILED")

    def test_p15_02_yaml_production_alias_or_traversal_triggers_stop_scope(self):
        """P15-02 [P0]: YAML containing production alias, UNC, or path traversal triggers STOP_SCOPE; 0 calls."""
        # 1. Config with traversal
        bad_cfg_traversal = self.fixture_root / "bad_traversal.yaml"
        bad_cfg_traversal.write_text(
            "storage:\n  lancedb_path: ../../lancedb\n  metadata_db: ../../metadata.db\n",
            encoding="utf-8"
        )
        rep1 = preflight_check(custom_config_path=bad_cfg_traversal, allowed_fixture_root=self.fixture_root)
        self.assertFalse(rep1["checks_passed"])
        self.assertTrue("STOP_SCOPE" in rep1["storage_scope"]["scope_check"])

        # 2. Config with UNC path
        bad_cfg_unc = self.fixture_root / "bad_unc.yaml"
        bad_cfg_unc.write_text(
            "storage:\n  lancedb_path: \\\\server\\share\\lancedb\n  metadata_db: \\\\server\\share\\meta.db\n",
            encoding="utf-8"
        )
        rep2 = preflight_check(custom_config_path=bad_cfg_unc, allowed_fixture_root=self.fixture_root)
        self.assertFalse(rep2["checks_passed"])
        self.assertTrue("STOP_SCOPE" in rep2["storage_scope"]["scope_check"])

    def test_p15_03_first_worker_failure_halts_immediately_fail_fast(self):
        """P15-03 [P0]: First worker failure (error envelope / nonzero exit) stops immediately; calls 2..6 are NOT spawned."""
        sim_responses = {
            "Q004_OFF": {
                "simulated_error": "SIMULATED_FIRST_CALL_FAILURE"
            }
        }
        pilot = run_postfix_pilot(synthetic_test=True, simulated_responses=sim_responses)
        self.assertEqual(pilot["attempted_calls"], 1)
        self.assertEqual(pilot["spawned_calls"], 1)
        self.assertEqual(pilot["completed_calls"], 0)
        self.assertEqual(len(pilot["calls"]), 1)
        self.assertFalse(pilot["calls"][0]["success"])
        self.assertTrue("HALTED_AFTER_FAILURE" in pilot["overall_status"])

    def test_p15_04_off_on_rank_mismatch_halts_subsequent_pairs(self):
        """P15-04 [P0]: OFF and ON returning different ranks on first pair halts immediately; Q010 and Q088 are NOT started."""
        sim_responses = {
            "Q004_OFF": {
                "simulated_result": json.dumps([
                    {"chunk_id": "chunk_A", "text": "Clause 6.4 text", "parent_ids": ["p1"]}
                ])
            },
            "Q004_ON": {
                "simulated_result": json.dumps([
                    {"chunk_id": "chunk_B", "text": "Clause 6.4 different hit", "parent_ids": ["p2"]}
                ])
            }
        }
        pilot = run_postfix_pilot(synthetic_test=True, simulated_responses=sim_responses)
        self.assertEqual(pilot["attempted_calls"], 2)
        self.assertEqual(pilot["spawned_calls"], 2)
        self.assertEqual(len(pilot["calls"]), 2)
        self.assertEqual(len(pilot["comparisons"]), 1)
        self.assertEqual(pilot["comparisons"][0]["pair_verdict"], "FAIL")
        self.assertFalse(pilot["comparisons"][0]["rank_identical"])
        self.assertTrue("HALTED_PAIR_MISMATCH" in pilot["overall_status"])

    def test_p15_05_nonzero_exit_with_success_json_is_nonzero_exit_no_go(self):
        """P15-05 [P0]: Child exiting with code 1 despite stdout JSON having success=true is NONZERO_EXIT_NO_GO, not PASS."""
        res = execute_bounded_search(
            query="test_query",
            shadow_mode=False,
            simulated_error="SIMULATED_NONZERO_FAILURE"  # shadow_pilot_worker exits with 0 on simulated_error, so we test execute_bounded_search directly
        )
        self.assertFalse(res["success"])
        self.assertTrue("SIMULATED_NONZERO_FAILURE" in res["error"])

        # Directly verify nonzero exit handling in execute_bounded_search
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = mock_popen.return_value
            mock_proc.communicate.return_value = (json.dumps({"success": True, "result": [{"chunk_id": "c1"}]}), "some stderr")
            mock_proc.returncode = 1
            mock_proc.poll.return_value = 1

            ret = execute_bounded_search(query="test", shadow_mode=False)
            self.assertFalse(ret["success"])
            self.assertEqual(ret["exitcode"], 1)
            self.assertTrue("NONZERO_EXIT_NO_GO" in ret["error"])

    def test_p15_06_empty_retrieval_lists_fail_shadow_match(self):
        """P15-06 [P0]: Both OFF and ON returning result=[] and success=True fails retrieval_match and halts; no false PASS."""
        sim_responses = {
            "Q004_OFF": {
                "simulated_result": "[]"
            },
            "Q004_ON": {
                "simulated_result": "[]"
            }
        }
        pilot = run_postfix_pilot(synthetic_test=True, simulated_responses=sim_responses)
        self.assertEqual(pilot["attempted_calls"], 1)  # Fails fast on call 1 because hits is empty!
        self.assertEqual(pilot["completed_calls"], 0)
        self.assertFalse(pilot["calls"][0]["retrieval_match"])
        self.assertTrue("HALTED_AFTER_FAILURE" in pilot["overall_status"])

    def test_p15_07_on_observer_inactive_or_error_fails_shadow_pass(self):
        """P15-07 [P0]: ON observer missing, errors > 0, or drops > 0 fails pair and halts without next pair."""
        # Test case: ON result has observer error
        hit = [{"chunk_id": "c1", "text": "some norm", "parent_ids": ["p1"]}]
        sim_responses = {
            "Q004_OFF": {
                "simulated_result": json.dumps(hit)
            },
            "Q004_ON": {
                "simulated_result": json.dumps(hit)
            }
        }
        # In shadow_pilot_worker, simulated_result sets shadow_stats=None
        # Our harness requires valid shadow_stats for ON, so with shadow_stats=None it fails observer check!
        pilot = run_postfix_pilot(synthetic_test=True, simulated_responses=sim_responses)
        self.assertEqual(pilot["attempted_calls"], 2)
        self.assertEqual(len(pilot["comparisons"]), 1)
        self.assertFalse(pilot["comparisons"][0]["observer_valid"])
        self.assertEqual(pilot["comparisons"][0]["pair_verdict"], "FAIL")
        self.assertTrue("HALTED_PAIR_MISMATCH" in pilot["overall_status"])

    def test_p15_08_empty_or_missing_chunk_ids_rejected_by_compare_ranks(self):
        """P15-08 [P0]: Hits without real chunk/parent IDs are strictly rejected by compare_ranks."""
        hits_no_ids_1 = [{"text": "foo"}]
        hits_no_ids_2 = [{"text": "foo"}]
        self.assertFalse(compare_ranks(hits_no_ids_1, hits_no_ids_2))

        hits_empty_ids = [{"chunk_id": "", "parent_id": None}]
        self.assertFalse(compare_ranks(hits_empty_ids, hits_empty_ids))

        # Valid IDs are accepted
        valid_hits = [{"chunk_id": "c1", "text": "foo"}]
        self.assertTrue(compare_ranks(valid_hits, valid_hits))

    def test_p15_09_synthetic_machinery_mode_clean_pass_with_proper_labels(self):
        """P15-09 [P1]: All 6 synthetic calls successful with valid IDs; labelled SYNTHETIC_MACHINERY_ONLY, live_gate=NOT_EXECUTED."""
        pilot = run_postfix_pilot(synthetic_test=True)
        self.assertEqual(pilot["overall_status"], "SYNTHETIC_MACHINERY_VERIFIED")
        self.assertEqual(pilot["execution_mode"], "SYNTHETIC_MACHINERY_ONLY")
        self.assertEqual(pilot["actual_corpus_search_calls"], 0)
        self.assertEqual(pilot["live_gate"], "NOT_EXECUTED")
        self.assertEqual(pilot["completed_calls"], 6)
        self.assertEqual(len(pilot["comparisons"]), 3)
        for c in pilot["comparisons"]:
            self.assertEqual(c["pair_verdict"], "PASS")

    def test_p15_10_raw_result_separation_and_leak_prevention(self):
        """P15-10 [P1]: Raw results saved only in temp with SHA-256; git report contains only sanitized excerpts (<= 200 chars)."""
        pilot = run_postfix_pilot(synthetic_test=True)
        repo_json_path = self.fixture_root / "reports" / "postfix_pilot_results_015.json"

        raw_temp_path = save_separated_results(pilot, repo_json_path)
        self.assertTrue(raw_temp_path.exists())

        # Check repo report contains no raw_result full dumps
        with open(repo_json_path, "r", encoding="utf-8") as f:
            saved_report = json.load(f)

        self.assertIn("raw_results_temp_path", saved_report)
        self.assertIn("raw_results_sha256", saved_report)
        self.assertEqual(len(saved_report["raw_results_sha256"]), 64)

        for c in saved_report["calls"]:
            self.assertNotIn("raw_result", c)
            if c.get("top_hit"):
                snippet = c["top_hit"].get("snippet", "")
                self.assertLessEqual(len(snippet), 200)


if __name__ == "__main__":
    unittest.main()
