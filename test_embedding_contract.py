"""Embedding-model contract: the server's actual model must match the index.

Dimension is not identity — Qwen3-Embedding-0.6B and bge-m3 are both 1024 wide,
so a silently swapped model used to be undetectable.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from embedder.contract import (
    EmbeddingContractError,
    check_response_model,
    models_compatible,
    normalize_model_name,
)


class NormalizeModelNameTests(unittest.TestCase):
    def test_strips_repo_prefix_case_and_separators(self):
        self.assertEqual(
            normalize_model_name("Qwen/Qwen3-Embedding-0.6B"), "qwen3embedding06b"
        )
        self.assertEqual(
            normalize_model_name("qwen3_embedding_0.6b"), "qwen3embedding06b"
        )

    def test_strips_packaging_and_quantization_tails(self):
        for name in (
            "Qwen3-Embedding-0.6B-GGUF",
            "Qwen3-Embedding-0.6B.gguf",
            "Qwen3-Embedding-0.6B-q4_k_m.gguf",
            "Qwen3-Embedding-0.6B-f16",
        ):
            self.assertEqual(normalize_model_name(name), "qwen3embedding06b", name)

    def test_empty_input_is_empty(self):
        self.assertEqual(normalize_model_name(None), "")
        self.assertEqual(normalize_model_name("   "), "")


class ModelsCompatibleTests(unittest.TestCase):
    def test_same_weights_named_differently_are_compatible(self):
        self.assertTrue(
            models_compatible("Qwen3-Embedding-0.6B-GGUF", "Qwen/Qwen3-Embedding-0.6B")
        )

    def test_different_models_of_equal_width_are_not_compatible(self):
        # The exact failure this contract exists to catch: both emit 1024 floats.
        self.assertFalse(models_compatible("Qwen3-Embedding-0.6B-GGUF", "bge-m3"))

    def test_different_sizes_of_one_family_are_not_compatible(self):
        self.assertFalse(
            models_compatible("Qwen3-Embedding-0.6B", "Qwen3-Embedding-4B")
        )

    def test_missing_side_is_never_compatible(self):
        self.assertFalse(models_compatible("", "bge-m3"))
        self.assertFalse(models_compatible("bge-m3", None))


class CheckResponseModelTests(unittest.TestCase):
    def test_compatible_report_is_ok(self):
        status, detail = check_response_model(
            "Qwen3-Embedding-0.6B-GGUF", "Qwen3-Embedding-0.6B"
        )
        self.assertEqual(status, "ok")
        self.assertEqual(detail, "Qwen3-Embedding-0.6B")

    def test_mismatch_raises_with_stable_code(self):
        with self.assertRaises(EmbeddingContractError) as ctx:
            check_response_model("Qwen3-Embedding-0.6B-GGUF", "bge-m3")
        self.assertEqual(ctx.exception.code, "embedding_contract_mismatch")
        self.assertIn("bge-m3", ctx.exception.detail)

    def test_absent_report_is_unverified_by_default(self):
        status, _ = check_response_model("Qwen3-Embedding-0.6B-GGUF", None)
        self.assertEqual(status, "unverified")

    def test_absent_report_can_fail_closed(self):
        with self.assertRaises(EmbeddingContractError) as ctx:
            check_response_model("Qwen3-Embedding-0.6B-GGUF", "", require_report=True)
        self.assertEqual(ctx.exception.code, "embedding_model_unreported")


def _install_httpx_stub(response_payload: dict):
    """Minimal httpx stand-in so the client is importable without the dependency."""
    module = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.posts = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            self.posts += 1
            return Response(response_payload)

    module.HTTPError = HTTPError
    module.Client = Client
    module.Timeout = lambda *a, **k: None
    return module


class ClientContractTests(unittest.TestCase):
    """The provider must reject vectors produced by the wrong model."""

    def _embed(self, payload: dict):
        """Build a provider against a stubbed server and embed one query."""
        stub = _install_httpx_stub(payload)
        with patch.dict(sys.modules, {"httpx": stub}):
            sys.modules.pop("embedder.client", None)
            from embedder.client import LemonadeEmbeddingProvider

            provider = LemonadeEmbeddingProvider()
            provider.model = "Qwen3-Embedding-0.6B-GGUF"
            return provider, provider.embed_batch(["запрос"])

    def test_wrong_model_in_response_blocks_the_vectors(self):
        payload = {"model": "bge-m3", "data": [{"index": 0, "embedding": [0.1] * 1024}]}
        with self.assertRaises(EmbeddingContractError) as ctx:
            self._embed(payload)
        self.assertEqual(ctx.exception.code, "embedding_contract_mismatch")

    def test_matching_model_passes_and_is_recorded(self):
        provider, vectors = self._embed({
            "model": "Qwen/Qwen3-Embedding-0.6B",
            "data": [{"index": 0, "embedding": [0.1] * 1024}],
        })
        self.assertEqual(len(vectors), 1)
        state = provider.contract_state()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["actual_model"], "Qwen/Qwen3-Embedding-0.6B")

    def test_server_without_model_field_is_unverified_not_blocked(self):
        provider, vectors = self._embed(
            {"data": [{"index": 0, "embedding": [0.1] * 1024}]}
        )
        self.assertEqual(len(vectors), 1)
        self.assertEqual(provider.contract_state()["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
