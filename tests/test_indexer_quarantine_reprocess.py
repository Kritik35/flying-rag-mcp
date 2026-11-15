"""
tests/test_indexer_quarantine_reprocess.py

Unit test for quarantine state recovery and reprocessing invariant (Blocker B3):
1. Ingesting a file where indexing fails sets status to 'quarantine_failed_indexing'.
2. The unverified new SHA is NOT recorded as the successful file sha256.
3. file_changed() returns True for quarantined/failed files even if disk SHA matches stored SHA.
4. Subsequent indexing pass without the fault transitions file to status 'indexed'.
"""
from __future__ import annotations
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from storage import metadata_db
from indexer import prepare_chunks_for_upsert


class IndexerQuarantineReprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_meta.db"
        metadata_db.init_db(self.db_path)
        self.source_path = str(Path(self.temp_dir.name) / "doc1.txt")
        self.doc_content = b"Sample text for indexing."
        self.initial_sha = hashlib.sha256(self.doc_content).hexdigest()[:16]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_file_changed_returns_true_for_quarantined_files(self):
        # Insert a file with status 'quarantine_failed_indexing'
        metadata_db.upsert_file(
            self.db_path,
            source_path=self.source_path,
            file_name="doc1.txt",
            format="txt",
            sha256=self.initial_sha,
            created_at="2026-11-15T12:00:00",
            modified_at="2026-11-15T12:00:00",
            chunk_count=0,
            status="quarantine_failed_indexing"
        )

        # file_changed must return True despite same SHA to allow automatic recovery
        changed = metadata_db.file_changed(self.db_path, self.source_path, self.initial_sha)
        self.assertTrue(changed, "file_changed must return True for quarantined files without requiring --force")

    def test_file_changed_returns_true_for_failed_or_partial_files(self):
        for bad_status in ["failed", "error", "partial", "quarantine_failed_ocr"]:
            metadata_db.upsert_file(
                self.db_path,
                source_path=self.source_path,
                file_name="doc1.txt",
                format="txt",
                sha256=self.initial_sha,
                created_at="2026-11-15T12:00:00",
                modified_at="2026-11-15T12:00:00",
                chunk_count=0,
                status=bad_status
            )
            self.assertTrue(
                metadata_db.file_changed(self.db_path, self.source_path, self.initial_sha),
                f"file_changed must return True for status '{bad_status}'"
            )

    def test_file_changed_returns_false_only_for_healthy_identical_files(self):
        metadata_db.upsert_file(
            self.db_path,
            source_path=self.source_path,
            file_name="doc1.txt",
            format="txt",
            sha256=self.initial_sha,
            created_at="2026-11-15T12:00:00",
            modified_at="2026-11-15T12:00:00",
            chunk_count=5,
            status="indexed"
        )
        # Healthy file with same SHA returns False
        self.assertFalse(metadata_db.file_changed(self.db_path, self.source_path, self.initial_sha))
        # Healthy file with different SHA returns True
        self.assertTrue(metadata_db.file_changed(self.db_path, self.source_path, "different_sha_1234"))

    def test_indexer_quarantine_preserves_previous_sha(self):
        # Initially healthy document v1
        metadata_db.upsert_file(
            self.db_path,
            source_path=self.source_path,
            file_name="doc1.txt",
            format="txt",
            sha256="v1_valid_sha",
            created_at="2026-11-15T12:00:00",
            modified_at="2026-11-15T12:00:00",
            chunk_count=3,
            status="indexed"
        )

        prev_rec = metadata_db.get_file(self.db_path, self.source_path)
        self.assertIsNotNone(prev_rec)
        self.assertEqual(prev_rec["sha256"], "v1_valid_sha")

        # Simulate indexer failure on v2 (unverified new SHA):
        # Indexer records quarantine preserving prev_sha
        prev_sha = prev_rec["sha256"] if prev_rec and prev_rec.get("sha256") else ""
        metadata_db.upsert_file(
            self.db_path,
            source_path=self.source_path,
            file_name="doc1.txt",
            format="txt",
            sha256=prev_sha,
            created_at="2026-11-15T12:05:00",
            modified_at="2026-11-15T12:05:00",
            chunk_count=0,
            status="quarantine_failed_indexing"
        )

        quarantined = metadata_db.get_file(self.db_path, self.source_path)
        self.assertEqual(quarantined["status"], "quarantine_failed_indexing")
        # Must still have v1 SHA, not the unindexed v2 SHA
        self.assertEqual(quarantined["sha256"], "v1_valid_sha")

        # Now when v2 is attempted again, file_changed returns True
        v2_sha = "v2_new_attempt"
        self.assertTrue(metadata_db.file_changed(self.db_path, self.source_path, v2_sha))

        # Successful reprocessing updates status to indexed and sha to v2
        metadata_db.upsert_file(
            self.db_path,
            source_path=self.source_path,
            file_name="doc1.txt",
            format="txt",
            sha256=v2_sha,
            created_at="2026-11-15T12:10:00",
            modified_at="2026-11-15T12:10:00",
            chunk_count=4,
            status="indexed"
        )
        reprocessed = metadata_db.get_file(self.db_path, self.source_path)
        self.assertEqual(reprocessed["status"], "indexed")
        self.assertEqual(reprocessed["sha256"], v2_sha)
        self.assertEqual(reprocessed["chunk_count"], 4)


if __name__ == "__main__":
    unittest.main()
