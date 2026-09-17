from __future__ import annotations

import math
import types
import unittest
from unittest.mock import patch


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



class RerankDocumentBudgetTests(unittest.TestCase):
    """The cross-encoder runs behind a fixed physical batch (512 tokens here).

    A character budget is not a token budget: 2000 characters of Russian prose
    fit, the same 2000 characters of a dense technical table do not. Once parent
    context hydration started working, `text` became the ~1000-token parent
    instead of the ~150-token child, every request exceeded the batch, and the
    reranker fell back to retrieval order on every single query.
    """

    def _tokens(self, text: str) -> int:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))

    def test_long_document_is_cut_to_the_token_budget(self):
        from rag_server.reranker import DOC_TOKEN_LIMIT, build_rerank_payload

        long_text = "Системы вытяжной противодымной вентиляции коридоров. " * 200
        payload = build_rerank_payload("дымоудаление", [{"text": long_text}], "m")

        self.assertLessEqual(self._tokens(payload["documents"][0]), DOC_TOKEN_LIMIT)
        self.assertGreater(len(payload["documents"][0]), 0)

    def test_a_dense_document_is_cut_harder_than_prose_for_the_same_budget(self):
        """The whole point of counting tokens: equal character counts differ."""
        from rag_server.reranker import DOC_TOKEN_LIMIT, build_rerank_payload

        prose = "Противодымная вентиляция защищает коридоры здания. " * 200
        dense = "6.2.4 t=+18,5 C; L=1250 m3/h; dP=147 Pa; K=1,15; SP7.13130-2013. " * 200
        docs = build_rerank_payload("q", [{"text": prose}, {"text": dense}], "m")["documents"]

        for doc in docs:
            self.assertLessEqual(self._tokens(doc), DOC_TOKEN_LIMIT)
        self.assertLess(len(docs[1]), len(docs[0]))

    def test_short_documents_are_passed_through_untouched(self):
        from rag_server.reranker import build_rerank_payload

        payload = build_rerank_payload("q", [{"text": "короткий чанк"}], "m")
        self.assertEqual(payload["documents"], ["короткий чанк"])

    def test_budget_falls_back_to_characters_when_tiktoken_is_unavailable(self):
        import rag_server.reranker as reranker

        long_text = "Противодымная вентиляция коридоров. " * 200
        with patch.object(reranker, "_encoding", return_value=None):
            payload = reranker.build_rerank_payload("q", [{"text": long_text}], "m")

        self.assertLessEqual(len(payload["documents"][0]), reranker.DOC_CHAR_FALLBACK)

    def test_the_budget_is_read_from_config(self):
        import rag_server.reranker as reranker

        long_text = "Противодымная вентиляция коридоров. " * 200
        with patch.object(reranker, "_doc_token_limit", return_value=32):
            payload = reranker.build_rerank_payload("q", [{"text": long_text}], "m")

        self.assertLessEqual(self._tokens(payload["documents"][0]), 32)



class RerankPunctuationRunTests(unittest.TestCase):
    """cl100k is not a safe proxy for the server's tokeniser on dot leaders.

    A contents line — "Гидравлический расчёт . . . . . . . . . 20" — is cheap in
    cl100k, which merges the run, and expensive in the server's XLM-R, which
    does not. One project document budgeted at 400 cl100k tokens arrived as 685
    on the server and failed the whole request, so `project-expansion-vessel`
    lost its rerank on every single run.

    The runs carry nothing a relevance model can use, so they are collapsed
    before the budget is counted.
    """

    def test_a_dot_leader_run_is_collapsed(self):
        from rag_server.reranker import normalise_for_scoring

        text = "Гидравлический расчёт " + ". " * 200 + "20"
        out = normalise_for_scoring(text)

        self.assertLess(len(out), len(text) / 4)
        self.assertIn("Гидравлический расчёт", out)
        self.assertIn("20", out)

    def test_runs_of_dashes_and_underscores_go_too(self):
        from rag_server.reranker import normalise_for_scoring

        self.assertLess(len(normalise_for_scoring("Лист " + "_" * 120 + " 5")), 40)
        self.assertLess(len(normalise_for_scoring("Поз " + "-" * 120 + " 7")), 40)

    def test_ordinary_text_survives_intact(self):
        from rag_server.reranker import normalise_for_scoring

        text = "Системы вытяжной противодымной вентиляции коридоров, п. 7.2."
        self.assertEqual(normalise_for_scoring(text), text)

    def test_the_budget_is_counted_after_collapsing(self):
        import tiktoken
        from rag_server.reranker import DOC_TOKEN_LIMIT, build_rerank_payload

        enc = tiktoken.get_encoding("cl100k_base")
        text = "Гидравлический расчёт " + ". " * 400 + "раздел 20 " * 40
        doc = build_rerank_payload("q", [{"text": text}], "m")["documents"][0]

        self.assertLessEqual(len(enc.encode(doc)), DOC_TOKEN_LIMIT)
        # The words survived the collapse instead of being cut off by the dots.
        self.assertIn("раздел", doc)


class RerankOversizeRetryTests(unittest.TestCase):
    """No token count we can compute is the server's own.

    Collapsing punctuation removes the case we found; it cannot promise there
    is no other. When the server says the input is too large, one retry at half
    the budget turns a silent loss of reranking into a slower call.
    """

    def _stub(self, statuses):
        """httpx stub that fails with a size complaint for the first N calls."""
        calls = {"n": 0, "sizes": []}

        class SizeError(Exception):
            pass

        class Response:
            def __init__(self, ok):
                self.ok = ok

            def raise_for_status(self):
                if not self.ok:
                    raise SizeError(
                        "Server error '500 Internal Server Error': input "
                        "(685 tokens) is too large to process"
                    )

            def json(self):
                return {"results": [{"index": 0, "relevance_score": 3.0}]}

        class Client:
            def __init__(self, *_a, **_kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def post(self, _url, json=None, **_kw):
                i = calls["n"]
                calls["n"] += 1
                calls["sizes"].append(len(json["documents"][0]))
                return Response(statuses[i] if i < len(statuses) else True)

        return types.SimpleNamespace(Client=Client), calls

    def test_an_oversize_failure_is_retried_smaller(self):
        import rag_server.reranker as reranker

        fake, calls = self._stub([False, True])
        chunks = [{"chunk_id": f"c{i}", "text": "слово " * 500, "score": 0.5}
                  for i in range(8)]
        trace: dict = {}
        with patch.object(reranker, "httpx", fake):
            reranker.rerank_chunks("вопрос", chunks, top_k=3, trace=trace)

        self.assertEqual(calls["n"], 2)
        self.assertLess(calls["sizes"][1], calls["sizes"][0])
        self.assertEqual(trace["status"], "applied")
        self.assertTrue(trace.get("retried_smaller"))

    def test_it_retries_only_once(self):
        import rag_server.reranker as reranker

        fake, calls = self._stub([False, False, False])
        chunks = [{"chunk_id": f"c{i}", "text": "слово " * 500, "score": 0.5}
                  for i in range(8)]
        trace: dict = {}
        with patch.object(reranker, "httpx", fake):
            reranker.rerank_chunks("вопрос", chunks, top_k=3, trace=trace)

        self.assertEqual(calls["n"], 2)
        self.assertEqual(trace["status"], "failed")

    def test_an_unrelated_failure_is_not_retried(self):
        import rag_server.reranker as reranker

        calls = {"n": 0}

        class Client:
            def __init__(self, *_a, **_kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def post(self, *_a, **_kw):
                calls["n"] += 1
                raise ConnectionError("connection refused")

        chunks = [{"chunk_id": f"c{i}", "text": "текст", "score": 0.5}
                  for i in range(8)]
        trace: dict = {}
        with patch.object(reranker, "httpx", types.SimpleNamespace(Client=Client)):
            reranker.rerank_chunks("вопрос", chunks, top_k=3, trace=trace)

        self.assertEqual(calls["n"], 1)
        self.assertEqual(trace["status"], "failed")


if __name__ == "__main__":
    unittest.main()
