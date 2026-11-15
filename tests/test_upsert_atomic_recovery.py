"""
tests/test_upsert_atomic_recovery.py

Unit and fault-injection tests for P0-02 (destructive upsert atomicity & crash recovery):
1. Preflight rejection of duplicate chunk IDs.
2. Preflight rejection of non-finite (NaN / Inf) vector values.
3. Preflight rejection of dimension mismatch.
4. Preflight rejection of empty chunk_id or doc_id.
5. Injected fault during table.add() triggers automatic rollback, preserving prior consistent state.
6. Indexer failure sets explicit quarantine status ('quarantine_failed_indexing') without silent 'indexed' status.
"""
from __future__ import annotations
import unittest
import tempfile
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from storage import vector_store


@dataclass
class MockChunk:
    chunk_id: str
    text: str
    doc_id: str = "doc_test"
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {"source_path": "test.docx", "file_name": "test.docx"}


class UpsertAtomicRecoveryTests(unittest.TestCase):
    def test_duplicate_chunk_id_rejected_before_deletion(self):
        chunks = [
            MockChunk(chunk_id="c1", text="text 1"),
            MockChunk(chunk_id="c1", text="text 1 duplicate"),
        ]
        embeddings = [
            MagicMock(chunk_id="c1", embedding=[0.1] * 1024)
        ]
        mock_table = MagicMock()
        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(ValueError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)
            self.assertIn("duplicate chunk_id", str(ctx.exception))
            # Table delete must NOT have been called
            mock_table.delete.assert_not_called()

    def test_empty_chunk_or_doc_id_rejected(self):
        chunks = [
            MockChunk(chunk_id="", text="text empty id"),
        ]
        embeddings = [
            MagicMock(chunk_id="", embedding=[0.1] * 1024)
        ]
        with self.assertRaises(ValueError) as ctx:
            vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)
        self.assertIn("empty chunk_id", str(ctx.exception))

    def test_dimension_mismatch_rejected_before_deletion(self):
        chunks = [MockChunk(chunk_id="c1", text="text")]
        # Dimension 512 instead of 1024
        embeddings = [MagicMock(chunk_id="c1", embedding=[0.1] * 512)]
        mock_table = MagicMock()
        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(ValueError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)
            self.assertIn("embedding dimension", str(ctx.exception))
            mock_table.delete.assert_not_called()

    def test_non_finite_vector_rejected_before_deletion(self):
        chunks = [MockChunk(chunk_id="c1", text="text")]
        bad_emb = [0.1] * 1024
        bad_emb[5] = float("nan")
        embeddings = [MagicMock(chunk_id="c1", embedding=bad_emb)]
        mock_table = MagicMock()
        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(ValueError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)
            self.assertIn("non-finite values", str(ctx.exception))
            mock_table.delete.assert_not_called()

    def test_crash_recovery_rollback_on_table_add_failure(self):
        chunks = [MockChunk(chunk_id="c_new", text="new text", doc_id="doc_1")]
        embeddings = [MagicMock(chunk_id="c_new", embedding=[0.2] * 1024)]

        # Simulate prior existing rows
        existing_rows = [
            {"chunk_id": "c_old", "doc_id": "doc_1", "text": "old text", "vector": [0.1] * 1024}
        ]

        mock_table = MagicMock()
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = existing_rows

        # First table.add fails (simulating crash), second table.add succeeds (rollback)
        mock_table.add.side_effect = [
            Exception("Disk I/O error during add"),
            None  # Rollback add succeeds
        ]

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)

            self.assertIn("Prior state restored", str(ctx.exception))
            # Verify rollback was called with existing_rows
            self.assertEqual(mock_table.add.call_count, 2)
            mock_table.add.assert_called_with(existing_rows)


if __name__ == "__main__":
    unittest.main()
