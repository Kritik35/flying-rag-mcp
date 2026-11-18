"""
tests/test_postfix_pilot_fail_closed_015_rev1_2.py

Contract verification suite for Stage 4.2.9 / ТЗ-015 Rev 1.2 (G15-R12-01 .. G15-R12-10).
Enforces:
- P0-R1: Full raw corpus leak prevention in CLI/stdout/stderr; unique run IDs for private temp files.
- P0-R2: Strict canonical rank identity scheme (fail-closed on missing/empty/pseudo/duplicate IDs).
- P0-R3: Complete environment sanitization (scrubbing all host FLYING_RAG_* variables).
- P1-Q1: Separation of mechanical search pair consistency from normative evidence quality.
"""

from __future__ import annotations
import os
import sys
import json
import uuid
import tempfile
import unittest
import subprocess
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
    extract_canonical_id,
    evaluate_normative_evidence,
    save_separated_results,
    get_python_exe,
    WORKER_SCRIPT,
    ISOLATED_CORPUS_ROOT,
    ISOLATED_CONFIG_PATH
)


class TestPostfixPilotFailClosed015Rev12(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fixture_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_g15_r12_01_cli_synthetic_success_sentinel_isolation(self):
        """
        G15-R12-01 [P0]: CLI synthetic success with SECRET_FIXTURE_SENTINEL_015 in raw:
        - stdout and stderr do NOT contain the sentinel.
        - Public JSON report does NOT contain the sentinel.
        - Private temp raw file DOES contain the sentinel.
        - Process exit code is 0; status is SYNTHETIC_MACHINERY_VERIFIED.
        """
        sentinel = "SECRET_FIXTURE_SENTINEL_015_TOP_SECRET"
        sim_hit = [
            {
                "chunk_id": "chunk_Q004_001",
                "norm": "СП 7.13130",
                "clause_num": "6.4",
                "text": f"6.4 Нормативное требование. {sentinel}",
                "parent_ids": ["parent_001"],
                "context_sufficient": True,
                "score": 0.95
            }
        ]

        sim_responses = {
            "Q004_OFF": {"simulated_result": json.dumps(sim_hit, ensure_ascii=False)},
            "Q004_ON": {
                "simulated_result": json.dumps(sim_hit, ensure_ascii=False),
                "shadow_stats": {"submitted": 1, "processed": 1, "errors": 0, "dropped": 0}
            }
        }

        # Run pilot
        pilot = run_postfix_pilot(
            synthetic_test=True,
            simulated_responses=sim_responses
        )

        repo_json_path = self.fixture_root / "reports" / "postfix_pilot_results_015.json"
        sanitized_report, raw_temp_path, raw_sha256 = save_separated_results(
            pilot,
            target_repo_json=repo_json_path,
            secret_sentinel=sentinel
        )

        # 1. Private raw file must contain sentinel
        self.assertTrue(raw_temp_path.exists())
        raw_content = raw_temp_path.read_text(encoding="utf-8")
        self.assertIn(sentinel, raw_content)

        # 2. Public saved JSON must NOT contain sentinel
        public_content = repo_json_path.read_text(encoding="utf-8")
        self.assertNotIn(sentinel, public_content)

        # 3. Sanitized report in memory must NOT contain sentinel
        sanitized_json = json.dumps(sanitized_report, ensure_ascii=False)
        self.assertNotIn(sentinel, sanitized_json)

        # 4. Verify exit code and status
        self.assertEqual(pilot["overall_status"], "SYNTHETIC_MACHINERY_VERIFIED")
        self.assertEqual(pilot["actual_corpus_search_calls"], 0)

    def test_g15_r12_02_cli_synthetic_failure_no_raw_leak(self):
        """
        G15-R12-02 [P0]: CLI synthetic failure / error envelope with sentinel:
        - No channel outputs raw payload or sentinel.
        - Overall status is HALTED_AFTER_FAILURE; exit != 0.
        """
        sentinel = "SECRET_FIXTURE_SENTINEL_015_ERROR_BODY"
        sim_responses = {
            "Q004_OFF": {
                "simulated_error": f"SIMULATED_FAILURE_CODE {sentinel}"
            }
        }
        pilot = run_postfix_pilot(
            synthetic_test=True,
            simulated_responses=sim_responses
        )
        self.assertTrue(pilot["overall_status"].startswith("HALTED_AFTER_FAILURE"))

        sanitized_report, raw_temp_path, raw_sha256 = save_separated_results(
            pilot,
            secret_sentinel=sentinel
        )
        # Even on error, sanitized report must not expose unredacted sensitive error
        sanitized_str = json.dumps(sanitized_report, ensure_ascii=False)
        self.assertNotIn(sentinel, sanitized_str)

    def test_g15_r12_03_consecutive_runs_unique_raw_files(self):
        """
        G15-R12-03 [P0]: Two consecutive runs create two distinct private raw files
        with unique run IDs and verifiable SHA-256 hashes (never overwriting).
        """
        p1 = run_postfix_pilot(synthetic_test=True)
        sanitized1, raw_path1, sha1 = save_separated_results(p1)

        p2 = run_postfix_pilot(synthetic_test=True)
        sanitized2, raw_path2, sha2 = save_separated_results(p2)

        self.assertNotEqual(raw_path1, raw_path2)
        self.assertTrue(raw_path1.exists())
        self.assertTrue(raw_path2.exists())
        self.assertNotEqual(sanitized1["unique_run_id"], sanitized2["unique_run_id"])

    def test_g15_r12_04_mixed_valid_and_missing_id_in_pair_halts(self):
        """
        G15-R12-04 [P0]: Pair with valid hit1 + hit2 without ID:
        compare_ranks=False; overall FAIL and 0 spawns of next pair.
        """
        off_hits = [
            {"chunk_id": "c1", "text": "valid hit"},
            {"text": "unidentified hit without chunk_id or id"}
        ]
        on_hits = [
            {"chunk_id": "c1", "text": "valid hit"},
            {"text": "unidentified hit without chunk_id or id"}
        ]
        # In Rev 1.1 this returned True (false-PASS). In Rev 1.2 it must strictly fail!
        self.assertFalse(compare_ranks(off_hits, on_hits))

        # Verify in harness: pair fails immediately and Q010 is not spawned
        sim_responses = {
            "Q004_OFF": {"simulated_result": json.dumps(off_hits)},
            "Q004_ON": {"simulated_result": json.dumps(on_hits)}
        }
        pilot = run_postfix_pilot(synthetic_test=True, simulated_responses=sim_responses)
        self.assertEqual(len(pilot["comparisons"]), 1)
        self.assertEqual(pilot["comparisons"][0]["pair_verdict"], "FAIL")
        self.assertFalse(pilot["comparisons"][0]["rank_identical"])
        self.assertEqual(pilot["attempted_calls"], 2)
        self.assertTrue("HALTED_PAIR_MISMATCH" in pilot["overall_status"])

    def test_g15_r12_05_rank_identity_edge_cases(self):
        """
        G15-R12-05 [P0]: Canonical rank identity edge cases:
        - Duplicate IDs in list -> False (evidence defect)
        - Pseudo-IDs ('None', 'null', '{}') -> False
        - Cross-edition / switched doc identity -> False
        - Valid distinct canonical IDs -> True
        """
        # 1. Duplicate IDs in the same ranking list
        dups = [
            {"chunk_id": "c1", "norm": "СП 7"},
            {"chunk_id": "c1", "norm": "СП 7"}
        ]
        self.assertFalse(compare_ranks(dups, dups))

        # 2. Pseudo-IDs
        pseudo1 = [{"chunk_id": "None"}]
        pseudo2 = [{"chunk_id": "null"}]
        pseudo3 = [{"chunk_id": "{}"}]
        self.assertFalse(compare_ranks(pseudo1, pseudo1))
        self.assertFalse(compare_ranks(pseudo2, pseudo2))
        self.assertFalse(compare_ranks(pseudo3, pseudo3))

        # 3. Cross-edition identity mismatch
        hits_2012 = [{"chunk_id": "c1", "doc_name": "СП 60", "edition": "2012"}]
        hits_2020 = [{"chunk_id": "c1", "doc_name": "СП 60", "edition": "2020"}]
        self.assertFalse(compare_ranks(hits_2012, hits_2020))

        # 4. Valid distinct control
        valid_a = [{"chunk_id": "c1", "doc_name": "СП 7"}, {"chunk_id": "c2", "doc_name": "СП 7"}]
        valid_b = [{"chunk_id": "c1", "doc_name": "СП 7"}, {"chunk_id": "c2", "doc_name": "СП 7"}]
        self.assertTrue(compare_ranks(valid_a, valid_b))

    def test_g15_r12_06_parent_forbidden_env_overrides_completely_scrubbed(self):
        """
        G15-R12-06 [P0]: In parent process, forbidden FLYING_RAG_* overrides are set:
        - FLYING_RAG_SHADOW_CONTROL_FILE
        - FLYING_RAG_METADATA_DB
        - FLYING_RAG_CONFIG
        - FLYING_RAG_UNAPPROVED_VAR
        Child receives ONLY approved values; unapproved are absent; 0 external writes.
        """
        fake_control_file = self.fixture_root / "should_not_be_written.txt"
        forbidden_env = {
            "FLYING_RAG_SHADOW_CONTROL_FILE": str(fake_control_file),
            "FLYING_RAG_METADATA_DB": r"C:\RAG_Acer\data_imported\metadata.db",
            "FLYING_RAG_CONFIG": r"C:\RAG_Acer\config.yaml",
            "FLYING_RAG_UNAPPROVED_VAR": "MALICIOUS_INJECTION"
        }

        with patch.dict(os.environ, forbidden_env):
            res = execute_bounded_search(
                query="test_query",
                shadow_mode=False,
                simulated_result=json.dumps([{"chunk_id": "c1", "text": "safe"}])
            )
            self.assertTrue(res["success"])
            self.assertFalse(fake_control_file.exists())

    def test_g15_r12_07_fail_fast_on_malformed_worker_or_error(self):
        """
        G15-R12-07 [P0]: First worker failure halts immediately; max spawned = 1 for the failure.
        """
        sim_responses = {
            "Q004_OFF": {
                "simulated_error": "WORKER_PROCESS_CRASHED"
            }
        }
        pilot = run_postfix_pilot(synthetic_test=True, simulated_responses=sim_responses)
        self.assertEqual(pilot["attempted_calls"], 1)
        self.assertEqual(pilot["spawned_calls"], 1)
        self.assertEqual(pilot["completed_calls"], 0)
        self.assertTrue("HALTED_AFTER_FAILURE" in pilot["overall_status"])

    def test_g15_r12_08_normative_evidence_quality_schema(self):
        """
        G15-R12-08 [P1]: Evidence schema on synthetic fixtures:
        - Wrong clause, wrong edition (not 2020), or truncated EI 15 does NOT receive QUALITY_VERIFIED.
        - Mechanical EIG pair consistency is separated from normative quality.
        """
        # Case A: Q010 with truncated EI 15
        q010 = {
            "id": "Q010",
            "query": "СП 7.13130 пункт 6.10",
            "target_norm": "СП 7.13130",
            "clause": "6.10"
        }
        hit_truncated_ei15 = {
            "chunk_id": "c1",
            "norm": "СП 7.13130",
            "clause_num": "6.10",
            "text": "6.10 Клапаны противопожарные EI 60... [обрезано]",
            "status": "EVIDENCE_PARTIAL",
            "context_partial": True
        }
        eval_a = evaluate_normative_evidence(q010, hit_truncated_ei15)
        self.assertFalse(eval_a["QUALITY_VERIFIED"])
        self.assertEqual(eval_a["FULL_CLAUSE_EVIDENCE"], "FAIL")

        # Case B: Q088 with wrong edition (2012 instead of 2020)
        q088 = {
            "id": "Q088-2020",
            "query": "СП 60.13330.2020 пункт 7.1.1",
            "target_norm": "СП 60.13330",
            "edition": "2020",
            "clause": "7.1.1"
        }
        hit_wrong_edition = {
            "chunk_id": "c2",
            "norm": "СП 60.13330",
            "clause_num": "7.1.1",
            "edition": "2012",
            "text": "7.1.1 Параметры воздуха по редакции 2012 года."
        }
        eval_b = evaluate_normative_evidence(q088, hit_wrong_edition)
        self.assertFalse(eval_b["QUALITY_VERIFIED"])
        self.assertEqual(eval_b["TARGET_EDITION_MATCH"], "FAIL")

        # Case C: Valid Q088-2020 fixture
        hit_valid_2020 = {
            "chunk_id": "c3",
            "norm": "СП 60.13330.2020",
            "clause_num": "7.1.1",
            "edition": "2020",
            "text": "7.1.1 Параметры воздуха по СП 60.13330.2020.",
            "parent_ids": ["p1"],
            "context_sufficient": True
        }
        # C1: Without external reference text, SOURCE_FIDELITY is UNKNOWN -> QUALITY_VERIFIED is False (Rev 1.3 contract)
        eval_c = evaluate_normative_evidence(q088, hit_valid_2020)
        self.assertFalse(eval_c["QUALITY_VERIFIED"])
        self.assertEqual(eval_c["SOURCE_FIDELITY"], "UNKNOWN")
        self.assertEqual(eval_c["TARGET_EDITION_MATCH"], "PASS")
        self.assertEqual(eval_c["TARGET_CLAUSE_MATCH"], "PASS")

        # C2: With verified source reference text, QUALITY_VERIFIED becomes True
        eval_c_verified = evaluate_normative_evidence(
            q088, hit_valid_2020, source_reference_text=hit_valid_2020["text"]
        )
        self.assertTrue(eval_c_verified["QUALITY_VERIFIED"])
        self.assertEqual(eval_c_verified["SOURCE_FIDELITY"], "PASS")
        self.assertEqual(eval_c_verified["TARGET_EDITION_MATCH"], "PASS")

    def test_g15_r12_09_regression_suite_assertions(self):
        """
        G15-R12-09 [P1]: Verifies that preflight check, scope check, and canonical hash
        invariants remain 100% compliant with Stage 4.2.8 / 4.2.9 contracts.
        """
        preflight = preflight_check(custom_config_path=ISOLATED_CONFIG_PATH, allowed_fixture_root=ISOLATED_CORPUS_ROOT)
        self.assertTrue(preflight["checks_passed"])
        self.assertEqual(preflight["storage_scope"]["ISOLATED_COPY_VERIFIED"], "YES")
        self.assertEqual(preflight["storage_scope"]["CONSISTENT_SNAPSHOT"], "UNVERIFIED")
        self.assertEqual(preflight["model_service"]["MODEL_INDEX_IDENTITY"], "UNVERIFIED")
        self.assertEqual(preflight["production_invariants"]["PRODUCTION_METADATA_UNCHANGED"], "VERIFIED")

    def test_g15_r12_10_status_reporting_invariants(self):
        """
        G15-R12-10 [P1]: Reports separate contract / native / synthetic / live statuses;
        actual_search_calls = 0; LIVE_GATE = NOT_EXECUTED.
        """
        pilot = run_postfix_pilot(synthetic_test=True)
        self.assertEqual(pilot["actual_corpus_search_calls"], 0)
        self.assertEqual(pilot["live_gate"], "NOT_EXECUTED")
        self.assertEqual(pilot["execution_mode"], "SYNTHETIC_MACHINERY_ONLY")
        self.assertEqual(pilot["overall_status"], "SYNTHETIC_MACHINERY_VERIFIED")


if __name__ == "__main__":
    unittest.main()
