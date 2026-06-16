from __future__ import annotations

import math
import unittest


class RerankerPureLogicTests(unittest.TestCase):
    def test_sigmoid_normalizes_logits_to_unit_interval(self):
        from rag_server.reranker import _sigmoid

        self.assertAlmostEqual(_sigmoid(0.0), 0.5, places=4)
        self.assertGreater(_sigmoid(3.31), 0.95)      # relevant logit
        self.assertLess(_sigmoid(-10.28), 0.001)      # irrelevant logit
        self.assertTrue(0.0 <= _sigmoid(50.0) <= 1.0)
        self.assertTrue(0.0 <= _sigmoid(-50.0) <= 1.0)

    def test_build_rerank_payload_includes_query_and_documents(self):
        from rag_server.reranker import build_rerank_payload

        chunks = [
            {"chunk_id": "a", "text": "противодымная вентиляция дымоудаление"},
            {"chunk_id": "b", "text": "класс бетона по прочности"},
        ]
        payload = build_rerank_payload("дымоудаление", chunks, model="bge-reranker-v2-m3-GGUF")

        self.assertEqual(payload["model"], "bge-reranker-v2-m3-GGUF")
        self.assertEqual(payload["query"], "дымоудаление")
        self.assertEqual(payload["documents"], [
            "противодымная вентиляция дымоудаление",
            "класс бетона по прочности",
        ])

    def test_apply_rerank_results_orders_by_relevance_and_attaches_score(self):
        from rag_server.reranker import apply_rerank_results

        chunks = [
            {"chunk_id": "a", "text": "x", "score": 0.40},
            {"chunk_id": "b", "text": "y", "score": 0.90},
        ]
        # API says chunk index 0 is much more relevant than index 1
        results = [
            {"index": 0, "relevance_score": 5.0},
            {"index": 1, "relevance_score": -8.0},
        ]
        ranked = apply_rerank_results(chunks, results, top_k=2)

        self.assertEqual([c["chunk_id"] for c in ranked], ["a", "b"])
        self.assertGreater(ranked[0]["rerank_score"], ranked[1]["rerank_score"])
        self.assertGreater(ranked[0]["rerank_score"], 0.99)

    def test_apply_rerank_results_returns_top_k(self):
        from rag_server.reranker import apply_rerank_results

        chunks = [{"chunk_id": str(i), "text": "t"} for i in range(5)]
        results = [{"index": i, "relevance_score": float(i)} for i in range(5)]
        ranked = apply_rerank_results(chunks, results, top_k=2)

        self.assertEqual(len(ranked), 2)
        # highest relevance (index 4, then 3) first
        self.assertEqual([c["chunk_id"] for c in ranked], ["4", "3"])

    def test_apply_rerank_results_handles_missing_indices(self):
        from rag_server.reranker import apply_rerank_results

        chunks = [{"chunk_id": "a", "text": "x"}, {"chunk_id": "b", "text": "y"}]
        results = [{"index": 0, "relevance_score": 2.0}]  # b has no result
        ranked = apply_rerank_results(chunks, results, top_k=2)

        self.assertEqual(ranked[0]["chunk_id"], "a")
        self.assertEqual(len(ranked), 2)
        self.assertIn("rerank_score", ranked[1])

    def test_rerank_sync_short_circuits_when_pool_not_larger_than_top_k(self):
        # Must not touch the network when there is nothing to re-order.
        from rag_server.reranker import rerank_sync

        chunks = [{"chunk_id": "a", "text": "x", "score": 0.5}]
        out = rerank_sync("q", chunks, top_k=5)
        self.assertEqual(out, chunks)


if __name__ == "__main__":
    unittest.main()
