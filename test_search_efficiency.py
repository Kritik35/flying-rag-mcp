from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class SearchEfficiencyTests(unittest.TestCase):
    def test_search_documents_reuses_primary_query_embedding_on_cache_miss(self):
        import rag_server.tools as tools
        from rag_server.query_planner import QueryPlan

        calls: list[list[str]] = []

        def fake_embeddings(texts, is_query=False):
            calls.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

        class FakeProvider:
            def get_model_name(self):
                return "fake-model"

        class FakeCache:
            def __init__(self, db_path):
                self.db_path = db_path

            def lookup(self, query, embedding, scope_key):
                return None

            def store(self, query, embedding, results, scope_key):
                return None

        route = SimpleNamespace(
            route="default",
            dataset=None,
            folder_filter=None,
            inferred_dataset=None,
            inferred_folder_filter=None,
            reason="test",
            confidence=0.0,
            matched_terms=[],
            ambiguous=False,
            structured=False,
            structured_label=None,
        )
        decision = SimpleNamespace(apply=False, reason="not_needed")
        verdict = SimpleNamespace(needs_correction=False, label="correct", confidence=1.0, reason="test")
        result = {"chunk_id": "c1", "doc_id": "d1", "text": "answer", "source_path": "a.pdf", "score": 0.9}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(tools, "_db_paths", return_value=(Path(tmp) / "lancedb", Path(tmp) / "metadata.db")):
                with patch.object(tools, "_cfg", return_value={"retrieval": {"auto_rerank": False}}):
                    with patch("embedder.client._DEFAULT_PROVIDER", FakeProvider()):
                        with patch("embedder.client.get_embeddings", side_effect=fake_embeddings):
                            with patch("storage.semantic_cache.SemanticCache", FakeCache):
                                with patch("rag_server.query_router.route_query", return_value=route):
                                    with patch("rag_server.query_planner.plan_query", return_value=QueryPlan("default", "test", ["plain query"], False)):
                                        with patch("storage.vector_store.search", return_value=[result]):
                                            with patch("rag_server.retrieval_quality.apply_retrieval_quality", side_effect=lambda _q, results, **_kw: results):
                                                with patch("rag_server.rerank_policy.decide_rerank", return_value=decision):
                                                    with patch("storage.source_focus.concentrate_sources", side_effect=lambda results, **_kw: results):
                                                        with patch("rag_server.crag.grade_retrieval", return_value=verdict):
                                                            out = tools.search_documents("plain query", top_k=1, use_cache=True)

        self.assertEqual(out, [result])
        self.assertEqual(calls, [["plain query"]])


if __name__ == "__main__":
    unittest.main()
