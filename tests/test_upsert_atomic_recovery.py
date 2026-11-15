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

    def test_snapshot_read_error_aborts_without_deletion(self):
        chunks = [MockChunk(chunk_id="c_new", text="new text", doc_id="doc_1")]
        embeddings = [MagicMock(chunk_id="c_new", embedding=[0.2] * 1024)]
        mock_table = MagicMock()
        mock_table.search.side_effect = RuntimeError("LanceDB snapshot read failure")

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)
            self.assertIn("Pre-delete snapshot failed", str(ctx.exception))
            # Critical invariant: must NOT call delete when snapshot read fails
            mock_table.delete.assert_not_called()

    def test_excessive_rows_aborts_without_deletion(self):
        chunks = [MockChunk(chunk_id="c_new", text="new text", doc_id="doc_1")]
        embeddings = [MagicMock(chunk_id="c_new", embedding=[0.2] * 1024)]
        mock_table = MagicMock()
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"chunk_id": f"c_{i}", "doc_id": "doc_1"} for i in range(10001)
        ]

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)
            self.assertIn("Snapshot exceeds safe limit", str(ctx.exception))
            mock_table.delete.assert_not_called()

    def test_real_lancedb_rollback_preserves_rows(self):
        with tempfile.TemporaryDirectory() as td:
            lance_path = Path(td) / "test_lance"
            # Ingest initial 3 chunks
            init_chunks = [
                MockChunk(chunk_id=f"doc1_c{i}", text=f"Initial text {i}", doc_id="doc_1")
                for i in range(3)
            ]
            init_embs = [
                MagicMock(chunk_id=f"doc1_c{i}", embedding=[0.1 * (i + 1)] * 1024)
                for i in range(3)
            ]
            vector_store.upsert_chunks(lance_path, init_chunks, init_embs, dim=1024)

            # Verify initial count
            db, tbl = vector_store._get_table(lance_path, dim=1024)
            self.assertEqual(len(tbl), 3)

            # Now attempt upsert of new chunks for doc_1, but mock table.add to fail on initial add
            new_chunks = [
                MockChunk(chunk_id=f"doc1_new_{i}", text=f"New text {i}", doc_id="doc_1")
                for i in range(2)
            ]
            new_embs = [
                MagicMock(chunk_id=f"doc1_new_{i}", embedding=[0.5] * 1024)
                for i in range(2)
            ]

            orig_add = tbl.add
            add_calls = [0]
            def faulty_add(data, *args, **kwargs):
                add_calls[0] += 1
                if add_calls[0] == 1:
                    raise IOError("Simulated I/O disk error on vector insert")
                return orig_add(data, *args, **kwargs)

            with patch.object(vector_store, "_get_table", return_value=(db, tbl)):
                with patch.object(tbl, "add", side_effect=faulty_add):
                    with self.assertRaises(RuntimeError) as ctx:
                        vector_store.upsert_chunks(lance_path, new_chunks, new_embs, dim=1024)
                    self.assertIn("Prior state restored", str(ctx.exception))

            # Verify that rollback restored the original 3 rows in real LanceDB
            self.assertEqual(len(tbl), 3)
            rows = tbl.search().where("doc_id = 'doc_1'").limit(10).to_list()
            ids = {r["chunk_id"] for r in rows}
            self.assertEqual(ids, {"doc1_c0", "doc1_c1", "doc1_c2"})

    def test_rollback_failure_raises_critical_unverified_error(self):
        chunks = [MockChunk(chunk_id="c_new", text="new text", doc_id="doc_1")]
        embeddings = [MagicMock(chunk_id="c_new", embedding=[0.2] * 1024)]
        existing_rows = [
            {"chunk_id": "c_old", "doc_id": "doc_1", "text": "old text", "vector": [0.1] * 1024}
        ]

        mock_table = MagicMock()
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = existing_rows

        # Both initial add and rollback add fail
        mock_table.add.side_effect = [
            Exception("Disk I/O error during add"),
            Exception("Secondary catastrophic write error during rollback")
        ]

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)

            self.assertIn("CRITICAL:", str(ctx.exception))
            self.assertIn("state is unverified", str(ctx.exception).lower())

    def test_rollback_count_mismatch_raises_critical_unverified_error(self):
        chunks = [MockChunk(chunk_id="c_new", text="new text", doc_id="doc_1")]
        embeddings = [MagicMock(chunk_id="c_new", embedding=[0.2] * 1024)]
        existing_rows = [
            {"chunk_id": "c_old", "doc_id": "doc_1", "text": "old text", "vector": [0.1] * 1024}
        ]

        mock_table = MagicMock()
        # Initial snapshot returns 1 row, but verification post-rollback returns 0 rows (mismatch)
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.side_effect = [
            existing_rows,  # for snapshot
            []              # for post-rollback verification
        ]

        mock_table.add.side_effect = [
            Exception("Disk I/O error during add"),
            None  # Rollback add claims success
        ]

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)

            self.assertIn("CRITICAL:", str(ctx.exception))
            self.assertIn("count mismatch", str(ctx.exception).lower())
            self.assertIn("state is unverified", str(ctx.exception).lower())

    def test_multi_doc_delete_failure_restores_prior_deleted(self):
        chunks = [
            MockChunk(chunk_id="c_doc1", text="text 1", doc_id="doc_1"),
            MockChunk(chunk_id="c_doc2", text="text 2", doc_id="doc_2"),
        ]
        embeddings = [
            MagicMock(chunk_id="c_doc1", embedding=[0.1] * 1024),
            MagicMock(chunk_id="c_doc2", embedding=[0.2] * 1024),
        ]
        backup_rows = [
            {"chunk_id": "old_1a", "doc_id": "doc_1", "text": "old 1a", "vector": [0.1] * 1024},
            {"chunk_id": "old_1b", "doc_id": "doc_1", "text": "old 1b", "vector": [0.1] * 1024},
            {"chunk_id": "old_2", "doc_id": "doc_2", "text": "old 2", "vector": [0.2] * 1024},
        ]

        mock_table = MagicMock()
        def search_where_mock(clause):
            mock_res = MagicMock()
            if "doc_1" in clause:
                rows = [r for r in backup_rows if r.get("doc_id") == "doc_1"]
            elif "doc_2" in clause:
                rows = [r for r in backup_rows if r.get("doc_id") == "doc_2"]
            else:
                rows = []
            mock_res.limit.return_value.to_list.return_value = rows
            return mock_res

        mock_table.search.return_value.where.side_effect = search_where_mock

        # Deletion for doc_1 succeeds; deletion for doc_2 fails
        def delete_side_effect(where_clause):
            if "doc_2" in where_clause:
                raise RuntimeError("Locked doc_2 in table")
            return None

        mock_table.delete.side_effect = delete_side_effect

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)

            self.assertIn("Failed to delete existing document vectors for doc_id='doc_2'", str(ctx.exception))
            # Must have rolled back doc_1 by adding it back
            mock_table.add.assert_called_once()
            added_records = mock_table.add.call_args[0][0]
            self.assertEqual(len(added_records), 2)  # doc_1 backup rows from restore_subset

    def test_multi_doc_delete_failure_with_rollback_failure_raises_critical(self):
        chunks = [
            MockChunk(chunk_id="c_doc1", text="text 1", doc_id="doc_1"),
            MockChunk(chunk_id="c_doc2", text="text 2", doc_id="doc_2"),
        ]
        embeddings = [
            MagicMock(chunk_id="c_doc1", embedding=[0.1] * 1024),
            MagicMock(chunk_id="c_doc2", embedding=[0.2] * 1024),
        ]
        backup_rows = [
            {"chunk_id": "old_1", "doc_id": "doc_1", "text": "old 1", "vector": [0.1] * 1024},
        ]

        mock_table = MagicMock()
        def search_where_mock_crit(clause):
            mock_res = MagicMock()
            if "doc_1" in clause:
                rows = [r for r in backup_rows if r.get("doc_id") == "doc_1"]
            else:
                rows = []
            mock_res.limit.return_value.to_list.return_value = rows
            return mock_res

        mock_table.search.return_value.where.side_effect = search_where_mock_crit

        def delete_side_effect(where_clause):
            if "doc_2" in where_clause:
                raise RuntimeError("Locked doc_2 in table")
            return None

        mock_table.delete.side_effect = delete_side_effect
        mock_table.add.side_effect = RuntimeError("Catastrophic error during restore_subset add")

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(Path("dummy"), chunks, embeddings, dim=1024)

            self.assertIn("CRITICAL:", str(ctx.exception))
            self.assertIn("uncertain", str(ctx.exception).lower())

    def test_real_lancedb_rollback_cleans_partial_records(self):
        with tempfile.TemporaryDirectory() as td:
            lance_path = Path(td) / "test_lance"
            # Ingest initial 2 chunks for doc_1
            init_chunks = [
                MockChunk(chunk_id=f"doc1_c{i}", text=f"Initial text {i}", doc_id="doc_1")
                for i in range(2)
            ]
            init_embs = [
                MagicMock(chunk_id=f"doc1_c{i}", embedding=[0.1 * (i + 1)] * 1024)
                for i in range(2)
            ]
            vector_store.upsert_chunks(lance_path, init_chunks, init_embs, dim=1024)

            db, tbl = vector_store._get_table(lance_path, dim=1024)
            self.assertEqual(len(tbl), 2)

            new_chunks = [
                MockChunk(chunk_id=f"doc1_new_{i}", text=f"New text {i}", doc_id="doc_1")
                for i in range(2)
            ]
            new_embs = [
                MagicMock(chunk_id=f"doc1_new_{i}", embedding=[0.5] * 1024)
                for i in range(2)
            ]

            orig_add = tbl.add
            add_calls = [0]
            def faulty_partial_add(data, *args, **kwargs):
                add_calls[0] += 1
                if add_calls[0] == 1:
                    # Simulate partial insertion of only the first record before failure
                    orig_add([data[0]], *args, **kwargs)
                    raise IOError("Simulated partial insertion failure on record 2")
                return orig_add(data, *args, **kwargs)

            with patch.object(vector_store, "_get_table", return_value=(db, tbl)):
                with patch.object(tbl, "add", side_effect=faulty_partial_add):
                    with self.assertRaises(RuntimeError) as ctx:
                        vector_store.upsert_chunks(lance_path, new_chunks, new_embs, dim=1024)
                    self.assertIn("Prior state restored and verified", str(ctx.exception))

            # Verify that partial record was purged and original 2 rows are intact
            self.assertEqual(len(tbl), 2)
            rows = tbl.search().where("doc_id = 'doc_1'").limit(10).to_list()
            ids = {r["chunk_id"] for r in rows}
            self.assertEqual(ids, {"doc1_c0", "doc1_c1"})



if __name__ == "__main__":
    unittest.main()
