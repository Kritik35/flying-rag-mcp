from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_server.tools import build_search_scope_key
from storage.semantic_cache import SemanticCache


class RetrievalCacheRevisionTests(unittest.TestCase):
    """Offline regression: pre-fix SQLite cache results must not survive a retrieval-code revision."""

    def _current_scope(self) -> str:
        return build_search_scope_key(
            dataset=None,
            folder_filter=None,
            alpha=0.7,
            model_name="Qwen3-Embedding-0.6B-GGUF",
            route="normative_fire",
            corpus_generation="fixture-generation",
            top_k=5,
            rerank=None,
            auto_rerank=False,
            hyde=False,
        )

    def test_result_contract_revision_differs_from_prefixed_legacy_scope(self):
        current = self._current_scope()
        self.assertIn("retrieval-quality-v11-enr-clause-boundary", current)
        legacy = current.replace(
            "retrieval-quality-v11-enr-clause-boundary",
            "retrieval-quality-v10-enr",
        )
        self.assertNotEqual(legacy, current)
        self.assertEqual(
            current.count("retrieval-quality-v11-enr-clause-boundary"), 1
        )

    def test_persisted_old_exact_and_semantic_results_not_replayed(self):
        query = "СП 7.13130 пункт 6.10"
        current = self._current_scope()
        legacy = current.replace(
            "retrieval-quality-v11-enr-clause-boundary",
            "retrieval-quality-v10-enr",
        )
        stale = [{"chunk_id": "clause_6.10", "text": "STALE_PRE_FIX_RESULT"}]
        fresh = [{"chunk_id": "clause_6.10", "text": "NEW_BOUNDARY_RESULT"}]

        # A private temporary SQLite file is the only persistent fixture.
        # No real model, original corpus, real search, or production DB is used.
        with tempfile.TemporaryDirectory() as tmp:
            cache = SemanticCache(
                db_path=str(Path(tmp) / "fixture.db"),
                corpus_generation="fixture-generation",
            )
            cache._enabled = True
            embedding = [1.0, 0.0]
            cache.store(query, embedding, stale, scope_key=legacy)

            self.assertEqual(
                cache.lookup_exact(query, scope_key=legacy).results, stale
            )
            self.assertIsNone(cache.lookup_exact(query, scope_key=current))
            self.assertIsNone(
                cache.lookup(query, embedding, scope_key=current)
            )

            # Once the current scope stores a fresh result, it is reachable
            # without changing or deleting historical cache entries.
            cache.store(query, embedding, fresh, scope_key=current)
            self.assertEqual(
                cache.lookup_exact(query, scope_key=current).results, fresh
            )
            self.assertEqual(
                cache.lookup(query, embedding, scope_key=current).results,
                fresh,
            )
            self.assertEqual(
                cache.lookup_exact(query, scope_key=legacy).results, stale
            )


if __name__ == "__main__":
    unittest.main()
