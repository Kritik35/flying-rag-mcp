"""Offline tests for public report Windows absolute path sanitization (TZ-019).

Strictly offline, synthetic-only fixtures: no real corpus, model, search or production storage.
"""
from __future__ import annotations

import json
import re
import unittest

from tests.postfix_pilot_harness_015 import sanitize_public_report_paths, sanitize_report_text


class ReportPathSanitizer019Tests(unittest.TestCase):
    def setUp(self):
        self.sample_report = {
            "schema_version": "1.1.0",
            "task_id": "FR-CHECK-TEST",
            "unique_run_id": "12345678_abcdef",
            "execution_timestamp": "2026-11-20T12:00:00+0300",
            "raw_results_temp_path": r"C:\Users\almax\AppData\Local\Temp\postfix_pilot_raw_results_FR-CHECK-TEST_12345678_abcdef.json",
            "raw_results_sha256": "a8521859625102bbf44daf405d570b77ef5d2adf5fb93c37fa353b77d84ed873",
            "preflight": {
                "storage_scope": {
                    "isolated_corpus_root": r"C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011",
                    "isolated_config_path": r"C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011\isolated_config.yaml",
                    "scope_check": "ISOLATED_COPY_VERIFIED",
                },
                "model_service": {
                    "model_name": r"C:\AI\models\Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "endpoint_url": "http://127.0.0.1:8089",
                },
                "production_invariants": {
                    "production_db_path": r"C:\RAG_Acer\data_imported\metadata.db",
                    "watcher_pause_path": r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\watcher.pause",
                    "watcher_pause_active": True,
                },
            },
            "calls": [
                {
                    "call_number": 1,
                    "query_id": "Q004",
                    "query_text": "СП 7.13130 пункт 6.4",
                    "success": True,
                    "elapsed_ms": 44492.8,
                    "top_hit": {
                        "chunk_id": "clause_6.4",
                        "source_path": r"H:\Мой диск\НТД\123-ФЗ\СП 7.13130.docx",
                        "snippet": "6.4 В пределах одного пожарного отсека...",
                    },
                }
            ],
            "overall_status": "PILOT_COMPLETED_SUCCESSFULLY",
        }

    def test_windows_paths_in_preflight_are_masked(self):
        sanitized = sanitize_public_report_paths(self.sample_report)
        storage = sanitized["preflight"]["storage_scope"]
        self.assertEqual(storage["isolated_corpus_root"], "<ISOLATED_TEMP_CORPUS>")
        self.assertEqual(storage["isolated_config_path"], "<ISOLATED_TEMP_CORPUS>/isolated_config.yaml")

        model = sanitized["preflight"]["model_service"]
        self.assertEqual(model["model_name"], "<MODEL_DIR>/Qwen3-Embedding-0.6B-Q8_0.gguf")

        invariants = sanitized["preflight"]["production_invariants"]
        self.assertEqual(invariants["production_db_path"], "<PRODUCTION_DB_METADATA>")
        self.assertEqual(invariants["watcher_pause_path"], "<WATCHER_PAUSE_MARKER>")

    def test_raw_temp_path_is_masked(self):
        sanitized = sanitize_public_report_paths(self.sample_report)
        self.assertEqual(
            sanitized["raw_results_temp_path"],
            "<PRIVATE_RAW_TEMP>/postfix_pilot_raw_results_FR-CHECK-TEST_12345678_abcdef.json"
        )

    def test_hit_paths_are_masked(self):
        sanitized = sanitize_public_report_paths(self.sample_report)
        top_hit = sanitized["calls"][0]["top_hit"]
        self.assertEqual(top_hit["source_path"], "<NTD_CORPUS>/СП 7.13130.docx")

    def test_non_path_strings_and_hashes_strictly_preserved(self):
        sanitized = sanitize_public_report_paths(self.sample_report)
        self.assertEqual(sanitized["schema_version"], "1.1.0")
        self.assertEqual(sanitized["task_id"], "FR-CHECK-TEST")
        self.assertEqual(sanitized["unique_run_id"], "12345678_abcdef")
        self.assertEqual(sanitized["raw_results_sha256"], "a8521859625102bbf44daf405d570b77ef5d2adf5fb93c37fa353b77d84ed873")
        self.assertEqual(sanitized["calls"][0]["elapsed_ms"], 44492.8)
        self.assertEqual(sanitized["overall_status"], "PILOT_COMPLETED_SUCCESSFULLY")

    def test_no_windows_drive_letter_survives_in_serialized_json(self):
        sanitized = sanitize_public_report_paths(self.sample_report)
        serialized = json.dumps(sanitized, ensure_ascii=False)
        # Windows drive letters: e.g. C:\ or C:/, avoiding URLs like http://
        drive_matches = re.findall(r"(?<![A-Za-z])[A-Za-z]:[\\/]", serialized)
        self.assertEqual(drive_matches, [], f"Leaked drive paths found: {drive_matches}")

    def test_generic_windows_path_fallback(self):
        custom = {"custom_path": r"D:\Random\Folder\data.bin"}
        sanitized = sanitize_public_report_paths(custom)
        self.assertEqual(sanitized["custom_path"], "<PATH_REDACTED>/data.bin")

    def test_isolated_metadata_db_not_masked_as_production(self):
        """Isolated corpus metadata.db must become <ISOLATED_TEMP_CORPUS>/metadata.db, not production."""
        isolated_meta = {
            "path": r"C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011\metadata.db"
        }
        sanitized = sanitize_public_report_paths(isolated_meta)
        self.assertEqual(sanitized["path"], "<ISOLATED_TEMP_CORPUS>/metadata.db")

    def test_inline_windows_path_inside_arbitrary_message(self):
        """Paths embedded in sentences or errors must be masked without affecting message text."""
        msg = {
            "error": r"Failed to open C:\RAG_Acer\data_imported\metadata.db: file locked.",
            "notice": r"Loaded config from C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011\isolated_config.yaml successfully.",
        }
        sanitized = sanitize_public_report_paths(msg)
        self.assertEqual(sanitized["error"], "Failed to open <PRODUCTION_DB_METADATA>: file locked.")
        self.assertEqual(sanitized["notice"], "Loaded config from <ISOLATED_TEMP_CORPUS>/isolated_config.yaml successfully.")

    def test_multiple_inline_paths_in_single_string(self):
        """Multiple paths in one string must all be masked appropriately."""
        text = (
            r"Compared production C:\RAG_Acer\data_imported\metadata.db "
            r"with testbed C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011\metadata.db "
            r"under marker C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\watcher.pause."
        )
        masked = sanitize_report_text(text)
        expected = (
            "Compared production <PRODUCTION_DB_METADATA> "
            "with testbed <ISOLATED_TEMP_CORPUS>/metadata.db "
            "under marker <WATCHER_PAUSE_MARKER>."
        )
        self.assertEqual(masked, expected)


if __name__ == "__main__":
    unittest.main()
