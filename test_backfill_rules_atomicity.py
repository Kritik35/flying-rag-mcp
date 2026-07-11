import sqlite3
import tempfile
import unittest
from pathlib import Path

from backfill_rules import _select_missing_files, backfill_file
from storage.metadata_db import init_db, replace_engineering_rules, save_parent_chunk


class SequencedExtractor:
    enabled = True
    api_key = "test"

    def __init__(self, responses):
        self.responses = iter(responses)

    def extract_rules(self, **_kwargs):
        if hasattr(self, "seen_chunks"):
            self.seen_chunks.append(_kwargs["chunk_id"])
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class BackfillAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "metadata.db"
        init_db(self.db_path)
        self.source = "fixture.pdf"
        save_parent_chunk(self.db_path, "c1", self.source, "Limit 10 kW")
        save_parent_chunk(self.db_path, "c2", self.source, "Limit 20 kW")
        replace_engineering_rules(self.db_path, self.source, [{
            "chunk_id": "old", "rule_text": "Old 5 kW", "subject": "old",
        }])

    def rules(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT chunk_id, rule_text, subject FROM engineering_rules WHERE source_path = ? ORDER BY id",
                (self.source,),
            ).fetchall()
        finally:
            conn.close()

    def test_provider_failure_preserves_existing_rules_and_reports_partial(self):
        extractor = SequencedExtractor([[{"subject": "new"}], RuntimeError("provider failed")])

        result = backfill_file(self.db_path, self.source, extractor)

        self.assertEqual("partial", result["status"])
        self.assertEqual(1, result["processed_chunks"])
        self.assertEqual([("old", "Old 5 kW", "old")], self.rules())

    def test_failure_before_any_chunk_reports_failed_and_preserves_rules(self):
        result = backfill_file(
            self.db_path, self.source, SequencedExtractor([RuntimeError("provider failed")])
        )
        self.assertEqual("failed", result["status"])
        self.assertEqual([("old", "Old 5 kW", "old")], self.rules())

    def test_full_success_replaces_rules_once_all_chunks_are_extracted(self):
        result = backfill_file(
            self.db_path, self.source,
            SequencedExtractor([[{"subject": "first"}], [{"subject": "second"}]]),
        )
        self.assertEqual("success", result["status"])
        self.assertEqual(2, result["rule_count"])
        self.assertEqual(
            [("c1", "Limit 10 kW", "first"), ("c2", "Limit 20 kW", "second")],
            self.rules(),
        )

    def test_insert_failure_rolls_back_delete_and_reports_failed(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """CREATE TRIGGER reject_new_rule BEFORE INSERT ON engineering_rules
                   WHEN NEW.chunk_id != 'old' BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END"""
            )
            conn.commit()
        finally:
            conn.close()

        result = backfill_file(
            self.db_path, self.source,
            SequencedExtractor([[{"subject": "first"}], [{"subject": "second"}]]),
        )

        self.assertEqual("failed", result["status"])
        self.assertIn("injected insert failure", result["error"])
        self.assertEqual([("old", "Old 5 kW", "old")], self.rules())

    def test_chunks_are_extracted_in_deterministic_parent_id_order(self):
        extractor = SequencedExtractor([[{"subject": "first"}], [{"subject": "second"}]])
        extractor.seen_chunks = []

        backfill_file(self.db_path, self.source, extractor)

        self.assertEqual(["c1", "c2"], extractor.seen_chunks)

    def test_production_backfill_selection_remains_missing_only(self):
        files = [("existing.pdf", "Existing"), ("missing.pdf", "Missing")]
        self.assertEqual(
            [("missing.pdf", "Missing")],
            _select_missing_files(files, {"existing.pdf"}),
        )


if __name__ == "__main__":
    unittest.main()
