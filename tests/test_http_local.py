"""A call to a service on this machine must not go through a proxy.

The reranker built its httpx client without the guard the embedder and the
rules extractor already had. When the machine's proxy was switched on, every
rerank call raised

    ValueError: Unknown scheme for proxy URL URL('socks4://127.0.0.1:10808')

for a request to 127.0.0.1. A whole measurement run degraded to the no-rerank
path — normative hit@5 9/10 down to 5/10 — with `rerank_status: failed` in the
trace as the only sign.
"""
from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from http_local import httpx_client_kwargs, is_local


class LocalHostDetectionTests(unittest.TestCase):
    def test_loopback_forms_are_local(self):
        for url in ("http://localhost:13305/api/v1/reranking",
                    "http://127.0.0.1:13305/api/v1",
                    "http://[::1]:8000/x"):
            self.assertTrue(is_local(url), url)

    def test_a_remote_host_is_not_local(self):
        for url in ("https://openrouter.ai/api/v1",
                    "http://192.168.1.10:13305/api/v1"):
            self.assertFalse(is_local(url), url)

    def test_local_urls_stop_trusting_the_environment(self):
        self.assertEqual(
            httpx_client_kwargs("http://127.0.0.1:13305/api/v1/reranking"),
            {"trust_env": False},
        )

    def test_remote_urls_keep_the_environment_proxy(self):
        self.assertEqual(httpx_client_kwargs("https://openrouter.ai/api/v1"), {})

    def test_nonsense_is_not_treated_as_local(self):
        for url in ("", None, "not a url"):
            self.assertFalse(is_local(url), repr(url))


class RerankerUsesTheGuardTests(unittest.TestCase):
    def test_the_reranker_client_ignores_the_environment_for_localhost(self):
        import rag_server.reranker as reranker

        captured: dict = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"results": []}

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def post(self, *_a, **_kw):
                return FakeResponse()

        fake_httpx = types.SimpleNamespace(Client=FakeClient)
        chunks = [{"chunk_id": f"c{i}", "text": "текст", "score": 0.5}
                  for i in range(8)]
        with patch.object(reranker, "httpx", fake_httpx), \
                patch.object(reranker, "_rerank_config",
                             return_value=("http://127.0.0.1:13305/api/v1/reranking",
                                           "m", 64)):
            reranker.rerank_chunks("вопрос", chunks, top_k=3)

        self.assertIs(captured.get("trust_env"), False)


if __name__ == "__main__":
    unittest.main()
