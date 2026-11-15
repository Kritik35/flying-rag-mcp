"""
tests/test_p0_chunk_cache.py

Unit tests for Stage 4.1 P0 indexer hardening:
1. prepare_chunks_for_upsert preserves original chunk_id and does not overwrite with cached vector_id.
2. Incompatible callback signature never triggers automatic CACHE_VERIFIED fallback.
3. Multi-row conflicting vectors in LanceDB are detected and rejected.
4. LanceDB table.delete failure halts transaction with RuntimeError.
"""
from __future__ import annotations
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from indexer import prepare_chunks_for_upsert, _chunk_hash
from storage import vector_store


@dataclass
class DummyChunk:
    chunk_id: str
    text: str
    doc_id: str = "doc_test"
    metadata: dict = field(default_factory=dict)


class P0ChunkCacheHardeningTests(unittest.TestCase):
    def test_chunk_id_preserved_on_verified_cache_hit(self):
        c = DummyChunk(chunk_id="chunk_fresh_001", text="Тестовый нормативный пункт")
        c_hash = _chunk_hash(c.text)

        mock_get_cached = MagicMock(return_value={"vector_id": "legacy_vec_999"})
        mock_get_verified_vec = MagicMock(return_value=([0.1] * 1024, "CACHE_VERIFIED"))

        chunks_upsert, embs_upsert, new_cache = prepare_chunks_for_upsert(
            chunks=[c],
            lance_path=Path("dummy_lance"),
            meta_path=Path("dummy_meta"),
            embed_fn=MagicMock(),
            get_cached_chunk_fn=mock_get_cached,
            get_chunk_vector_fn=mock_get_verified_vec,
            use_cache=True,
            expected_dim=1024
        )

        # Chunk's own chunk_id MUST NOT be overwritten with legacy vector_id
        self.assertEqual(c.chunk_id, "chunk_fresh_001")
        self.assertEqual(len(chunks_upsert), 1)
        self.assertEqual(len(embs_upsert), 1)
        self.assertEqual(embs_upsert[0].chunk_id, "chunk_fresh_001")
        self.assertEqual(len(new_cache), 0)  # Reused from cache, no new embeddings needed

    def test_incompatible_callback_signature_does_not_auto_verify(self):
        c = DummyChunk(chunk_id="chunk_fresh_002", text="Текст с несовместимым коллбэком")

        mock_get_cached = MagicMock(return_value={"vector_id": "legacy_vec_888"})

        # Simulates legacy callback that rejects expected_hash / expected_dim
        def legacy_cb(lance_path, vec_id):
            raise TypeError("unexpected keyword argument 'expected_hash'")

        mock_embed = MagicMock(return_value=[MagicMock(chunk_id="chunk_fresh_002", embedding=[0.2] * 1024)])

        chunks_upsert, embs_upsert, new_cache = prepare_chunks_for_upsert(
            chunks=[c],
            lance_path=Path("dummy_lance"),
            meta_path=Path("dummy_meta"),
            embed_fn=mock_embed,
            get_cached_chunk_fn=mock_get_cached,
            get_chunk_vector_fn=legacy_cb,
            use_cache=True,
            expected_dim=1024
        )

        # Must fall back to embedding, NEVER auto-verifying unverified cache
        self.assertEqual(mock_embed.call_count, 1)
        self.assertEqual(len(new_cache), 1)
        self.assertEqual(new_cache[0][0].chunk_id, "chunk_fresh_002")

    def test_conflicting_vectors_rejected_by_verified_lookup(self):
        mock_table = MagicMock()
        # Two rows for same chunk_id with diverging vectors
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"vector": [0.1] * 1024, "text": "text_a"},
            {"vector": [0.9] * 1024, "text": "text_a"}
        ]

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            vec, status = vector_store.get_verified_chunk_vector(
                db_path=Path("dummy"),
                chunk_id="collision_chunk",
                expected_dim=1024
            )

        self.assertIsNone(vec)
        self.assertIn("ambiguous_conflicting_vectors", status)

    def test_upsert_chunks_halts_on_delete_failure(self):
        mock_table = MagicMock()
        mock_table.delete.side_effect = Exception("Disk I/O error or permission denied")

        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            with self.assertRaises(RuntimeError) as ctx:
                vector_store.upsert_chunks(
                    db_path=Path("dummy"),
                    chunks=[DummyChunk(chunk_id="c1", text="t1", doc_id="d1")],
                    embeddings=[MagicMock(chunk_id="c1", embedding=[0.1] * 1024)],
                    dim=1024
                )
            self.assertIn("Failed to delete existing document vectors", str(ctx.exception))

    def test_upsert_chunks_preflight_missing_embedding_raises_value_error(self):
        chunks = [
            DummyChunk(chunk_id="c1", text="t1", doc_id="d1"),
            DummyChunk(chunk_id="c2", text="t2", doc_id="d1"),
        ]
        # Only c1 has embedding, c2 is missing
        embeddings = [MagicMock(chunk_id="c1", embedding=[0.1] * 1024)]

        with self.assertRaises(ValueError) as ctx:
            vector_store.upsert_chunks(
                db_path=Path("dummy"),
                chunks=chunks,
                embeddings=embeddings,
                dim=1024
            )
        self.assertIn("Preflight check failed in upsert_chunks", str(ctx.exception))
        self.assertIn("c2", str(ctx.exception))

    def test_nan_inf_vector_rejected(self):
        mock_table = MagicMock()
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"vector": [float("nan")] * 1024, "text": "text_nan"}
        ]
        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            vec, status = vector_store.get_verified_chunk_vector(
                db_path=Path("dummy"),
                chunk_id="nan_chunk",
                expected_dim=1024
            )
        self.assertIsNone(vec)
        self.assertIn("non_finite_vector_values", status)

    def test_missing_row_text_when_hash_expected_rejected(self):
        mock_table = MagicMock()
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"vector": [0.1] * 1024, "text": None}
        ]
        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            vec, status = vector_store.get_verified_chunk_vector(
                db_path=Path("dummy"),
                chunk_id="no_text_chunk",
                expected_hash="abcd1234",
                expected_dim=1024
            )
        self.assertIsNone(vec)
        self.assertIn("missing_row_text_for_hash_verification", status)

    def test_excessive_collisions_rejected(self):
        mock_table = MagicMock()
        # 101 rows returned
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"vector": [0.1] * 1024, "text": "txt"} for _ in range(101)
        ]
        with patch.object(vector_store, "_get_table", return_value=(None, mock_table)):
            vec, status = vector_store.get_verified_chunk_vector(
                db_path=Path("dummy"),
                chunk_id="huge_collision_chunk",
                expected_dim=1024
            )
        self.assertIsNone(vec)
        self.assertIn("excessive_collisions", status)


if __name__ == "__main__":
    unittest.main()
