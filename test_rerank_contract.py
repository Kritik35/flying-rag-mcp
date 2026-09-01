"""Rerank contract: returning top_k items does not prove a reranker ran.

The trace has to carry pool size, how much was sent, how much came back, and
whether the head of the list actually moved.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


def _install_httpx_stub(results=None, fail: bool = False):
    module = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": results or []}

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            if fail:
                raise HTTPError("connection refused")
            return Response()

    module.HTTPError = HTTPError
    module.Client = Client
    module.Timeout = lambda *a, **k: None
    return module


def _load_reranker(stub):
    sys.modules.pop("rag_server.reranker", None)
    import rag_server.reranker as reranker

    return reranker


def _chunks(n: int) -> list[dict]:
    return [{"chunk_id": f"c{i}", "text": f"фрагмент {i}", "score": 0.5} for i in range(n)]


class HeadChangedTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(sys.modules, {"httpx": _install_httpx_stub()}):
            self.reranker = _load_reranker(_install_httpx_stub())

    def test_same_head_is_not_a_change(self):
        chunks = _chunks(3)
        self.assertFalse(self.reranker.head_changed(chunks, list(chunks)))

    def test_reordered_head_is_a_change(self):
        chunks = _chunks(3)
        self.assertTrue(self.reranker.head_changed(chunks, list(reversed(chunks))))

    def test_empty_sides_are_not_a_change(self):
        self.assertFalse(self.reranker.head_changed([], _chunks(2)))
        self.assertFalse(self.reranker.head_changed(_chunks(2), []))


class RerankTraceTests(unittest.TestCase):
    def _rerank(self, chunks, top_k, results=None, fail=False):
        stub = _install_httpx_stub(results=results, fail=fail)
        with patch.dict(sys.modules, {"httpx": stub}):
            reranker = _load_reranker(stub)
            trace: dict = {}
            out = reranker.rerank_chunks("вопрос", chunks, top_k=top_k, trace=trace)
        return out, trace

    def test_applied_rerank_records_the_full_contract(self):
        chunks = _chunks(10)
        # Server puts the last candidate first.
        results = [{"index": 9, "relevance_score": 5.0}] + [
            {"index": i, "relevance_score": -1.0} for i in range(9)
        ]
        out, trace = self._rerank(chunks, top_k=3, results=results)

        self.assertEqual(trace["status"], "applied")
        self.assertEqual(trace["pool_count"], 10)
        self.assertEqual(trace["input_count"], 10)
        self.assertEqual(trace["returned_count"], 3)
        self.assertTrue(trace["head_changed"])
        self.assertEqual(out[0]["chunk_id"], "c9")

    def test_no_op_ordering_is_reported_as_unchanged_head(self):
        chunks = _chunks(10)
        results = [{"index": i, "relevance_score": 10.0 - i} for i in range(10)]
        _out, trace = self._rerank(chunks, top_k=3, results=results)

        self.assertEqual(trace["status"], "applied")
        self.assertFalse(trace["head_changed"])

    def test_failure_is_recorded_instead_of_passing_for_a_rerank(self):
        chunks = _chunks(10)
        out, trace = self._rerank(chunks, top_k=3, fail=True)

        self.assertEqual(trace["status"], "failed")
        self.assertIn("connection refused", trace["reason"])
        self.assertFalse(trace["head_changed"])
        # Retrieval order survives — the failure degrades, it does not empty.
        self.assertEqual([c["chunk_id"] for c in out], ["c0", "c1", "c2"])

    def test_trace_records_the_document_token_budget(self):
        """What was cut before scoring belongs in the contract, like the pool."""
        chunks = _chunks(10)
        results = [{"index": i, "relevance_score": 1.0} for i in range(10)]
        _out, trace = self._rerank(chunks, top_k=3, results=results)

        self.assertIn("doc_token_limit", trace)
        self.assertGreater(trace["doc_token_limit"], 0)

    def test_pool_no_larger_than_top_k_is_skipped_explicitly(self):
        _out, trace = self._rerank(_chunks(3), top_k=5)
        self.assertEqual(trace["status"], "skipped")
        self.assertEqual(trace["reason"], "pool_not_larger_than_top_k")

    def test_candidate_limit_bounds_the_cross_encoder_input(self):
        stub = _install_httpx_stub(results=[])
        with patch.dict(sys.modules, {"httpx": stub}):
            reranker = _load_reranker(stub)
            with patch.object(
                reranker, "_rerank_config",
                return_value=("http://x/reranking", "m", 4),
            ):
                trace: dict = {}
                out = reranker.rerank_chunks("вопрос", _chunks(20), top_k=5, trace=trace)

        self.assertEqual(trace["pool_count"], 20)
        self.assertEqual(trace["candidate_limit"], 4)
        self.assertEqual(trace["input_count"], 4)
        # The tail below the limit keeps its retrieval order instead of vanishing.
        self.assertEqual(len(out), 5)


if __name__ == "__main__":
    unittest.main()
