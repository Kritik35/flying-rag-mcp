"""End-to-end contract checks against a real LanceDB store.

Runs the real chunker, the real embedding client and the real search path — the
only stand-in is the embedding/reranking server, replaced by a deterministic
local stub so the suite needs no Lemonade and no GPU.

What this proves that the unit tests cannot: the manifest is actually written
beside a real store, a swapped model on a live endpoint really does block
search, and the retrieval trace reports the channels that really ran.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

DIM = 1024


def _deterministic_vector(text: str, dim: int = DIM) -> list[float]:
    """Stable bag-of-token vector: same text → same vector, similar text → close."""
    vec = [0.0] * dim
    for token in str(text or "").casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        vec[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class _Handler(BaseHTTPRequestHandler):
    served_model = "Qwen3-Embedding-0.6B-GGUF"
    report_model = True

    def log_message(self, *_args):  # keep the test output clean
        pass

    def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if self.path.endswith("/embeddings"):
            inputs = body.get("input") or []
            payload = {
                "data": [
                    {"index": i, "embedding": _deterministic_vector(text)}
                    for i, text in enumerate(inputs)
                ]
            }
            if type(self).report_model:
                payload["model"] = type(self).served_model
        elif self.path.endswith("/reranking"):
            documents = body.get("documents") or []
            # Reverse the pool, so an applied rerank is observable.
            payload = {
                "results": [
                    {"index": i, "relevance_score": float(i)}
                    for i in range(len(documents))
                ]
            }
        else:
            self.send_response(404)
            self.end_headers()
            return

        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class StubServer:
    """A local OpenAI-compatible embeddings/reranking endpoint."""

    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    def serve_model(self, name: str, report: bool = True) -> None:
        _Handler.served_model = name
        _Handler.report_model = report

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


CORPUS = {
    "sp7_dymoudalenie.txt": (
        "# СП 7.13130 Противодымная вентиляция\n\n"
        "Системы вытяжной противодымной вентиляции следует предусматривать "
        "для удаления продуктов горения из коридоров и холлов. "
        "Подпор воздуха предусматривается в лестничных клетках и тамбур-шлюзах.\n"
    ),
    "sp60_ventilyaciya.txt": (
        "# СП 60.13330 Отопление и вентиляция\n\n"
        "Расход приточного воздуха определяется расчетом воздухообмена. "
        "Утилизация теплоты вытяжного воздуха применяется для снижения "
        "потребления тепловой энергии системами вентиляции.\n"
    ),
    "ov2_project.txt": (
        "# ОВ-2 Проектная документация\n\n"
        "Раздел ОВ-2 содержит схемы систем вентиляции объекта. "
        "Приведены расчеты воздухообмена помещений и спецификация оборудования.\n"
    ),
}


class E2EContractTests(unittest.TestCase):
    """Index a small corpus for real, then exercise the contracts on it."""

    @classmethod
    def setUpClass(cls):
        cls.server = StubServer()
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.lance_path = root / "lancedb"
        cls.meta_path = root / "metadata.db"
        cls.corpus = root / "corpus"
        cls.corpus.mkdir()
        for name, text in CORPUS.items():
            (cls.corpus / name).write_text(text, encoding="utf-8")

        from embedder.client import _DEFAULT_PROVIDER
        from storage.metadata_db import init_db

        cls.provider = _DEFAULT_PROVIDER
        cls.provider.url = f"{cls.server.base}/embeddings"
        cls.provider.model = "Qwen3-Embedding-0.6B-GGUF"
        init_db(cls.meta_path)
        cls._index_corpus()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmp.cleanup()

    @classmethod
    def _index_corpus(cls):
        """Run the real chunker + embedder + store, as the indexer would."""
        from chunker.semantic import CHUNKER_ID, chunk_document, chunk_params
        from embedder.batcher import EmbeddingResult
        from parsers.text import parse as parse_text
        from storage.index_manifest import ensure_manifest
        from storage.metadata_db import save_parent_chunk, upsert_file
        from storage.vector_store import ensure_fts_index, upsert_chunks

        manifest, code, _ = ensure_manifest(
            cls.lance_path,
            model=cls.provider.get_model_name(),
            dimension=DIM,
            chunker=CHUNKER_ID,
            chunk_params=chunk_params(),
        )
        assert not code, f"manifest blocked the first index run: {code}"
        cls.manifest = manifest

        for path in sorted(cls.corpus.iterdir()):
            doc = parse_text(path)
            chunks = chunk_document(doc)
            for chunk in chunks:
                chunk.metadata["namespace"] = "normative"
                parent_id = chunk.metadata.get("parent_id")
                parent_text = chunk.metadata.get("parent_text")
                if parent_id and parent_text:
                    save_parent_chunk(cls.meta_path, parent_id, str(path), parent_text)
            vectors = cls.provider.embed_batch([c.text for c in chunks])
            embeddings = [
                EmbeddingResult(chunk_id=c.chunk_id, embedding=v)
                for c, v in zip(chunks, vectors)
            ]
            upsert_chunks(cls.lance_path, chunks, embeddings, dim=DIM)
            upsert_file(
                cls.meta_path, str(path), path.name, doc.format, "sha",
                doc.created_at, doc.modified_at, len(chunks), dataset="normative",
            )
        ensure_fts_index(cls.lance_path, dim=DIM)

    def _search(self, query: str, **kwargs):
        from rag_server import tools

        with patch.object(
            tools, "_db_paths", return_value=(self.lance_path, self.meta_path)
        ), patch.object(tools, "_cfg", return_value={"retrieval": {"auto_rerank": False}}):
            return tools.search_documents(query, use_cache=False, **kwargs)

    # ── the store is real ────────────────────────────────────────────────

    def test_corpus_is_actually_indexed(self):
        from storage.vector_store import count_chunks

        self.assertGreater(count_chunks(self.lance_path, dim=DIM), 0)

    def test_manifest_is_written_beside_the_store(self):
        from storage.index_manifest import manifest_path

        path = manifest_path(self.lance_path)
        self.assertTrue(path.exists())
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["model"], "Qwen3-Embedding-0.6B-GGUF")
        self.assertEqual(stored["dimension"], DIM)
        self.assertEqual(stored["chunker"], "parent-child-tiktoken-v1")

    def test_search_returns_evidence_from_the_indexed_corpus(self):
        results = self._search("противодымная вентиляция дымоудаление", top_k=3)
        self.assertIsInstance(results, list)
        self.assertTrue(results, "no results from a corpus that contains the answer")
        self.assertNotIn("error", results[0])
        joined = " ".join(str(r.get("source_path", "")) for r in results)
        self.assertIn("sp7_dymoudalenie", joined)

    # ── the trace is honest ──────────────────────────────────────────────

    def test_debug_trace_reports_the_channels_that_really_ran(self):
        out = self._search("воздухообмен вентиляция", top_k=3, debug=True)
        trace = out["debug"]

        self.assertIn(trace["status"], {"ok", "degraded"})
        retrieval = trace["retrieval"]
        self.assertIn("dense", retrieval["channels"])
        self.assertIn(retrieval["fusion"], {"linear_combination", "rrf", "none"})
        self.assertIn(
            retrieval["score_kind"],
            {"linear_combination", "rrf", "dense_similarity", "rerank_logit"},
        )
        # Whatever ran, degraded and channels must agree with each other.
        if retrieval["degraded"]:
            self.assertEqual(retrieval["channels"], ["dense"])
            self.assertEqual(trace["status"], "degraded")

    def test_trace_carries_the_embedding_contract(self):
        out = self._search("вентиляция", top_k=2, debug=True)
        contract = out["debug"]["embedding_contract"]

        self.assertEqual(contract["expected_model"], "Qwen3-Embedding-0.6B-GGUF")
        self.assertEqual(contract["actual_model"], "Qwen3-Embedding-0.6B-GGUF")
        self.assertEqual(contract["status"], "ok")
        self.assertEqual(contract["manifest"], "ok")

    def test_hybrid_failure_is_reported_as_degraded_not_as_hybrid(self):
        from storage import vector_store

        real_search = vector_store.search

        def broken_fts(*args, **kwargs):
            # Simulate a missing/broken FTS index: the store falls back to dense.
            with patch.object(vector_store, "_apply_ann_params", vector_store._apply_ann_params):
                kwargs["hybrid"] = False
                trace = kwargs.get("trace")
                rows = real_search(*args, **kwargs)
                if trace is not None:
                    trace["hybrid_requested"] = True
                    trace["degraded"] = True
                    trace["degraded_reason"] = "hybrid_failed: simulated"
                return rows

        from rag_server import tools

        with patch.object(vector_store, "search", broken_fts), \
             patch.object(tools, "search", broken_fts, create=True):
            out = self._search("вентиляция", top_k=2, debug=True)

        self.assertEqual(out["debug"]["status"], "degraded")
        self.assertTrue(out["debug"]["retrieval"]["degraded"])

    # ── a swapped model blocks, on a live endpoint ───────────────────────

    def test_swapped_server_model_blocks_search_with_a_code(self):
        self.addCleanup(self.server.serve_model, "Qwen3-Embedding-0.6B-GGUF", True)
        self.server.serve_model("bge-m3")
        self.provider._contract_status = "unchecked"

        results = self._search("вентиляция", top_k=3)

        self.assertIsInstance(results, list)
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(results[0]["error_code"], "embedding_contract_mismatch")
        self.assertIn("bge-m3", results[0]["error"])
        self.assertTrue(results[0]["action"])

    def test_blocked_search_keeps_the_debug_envelope(self):
        self.addCleanup(self.server.serve_model, "Qwen3-Embedding-0.6B-GGUF", True)
        self.server.serve_model("bge-m3")
        self.provider._contract_status = "unchecked"

        out = self._search("вентиляция", top_k=3, debug=True)

        self.assertEqual(out["results"], [])
        self.assertEqual(out["debug"]["status"], "blocked")
        self.assertEqual(out["debug"]["error_code"], "embedding_contract_mismatch")

    def test_manifest_blocks_a_runtime_configured_for_another_model(self):
        from storage.index_manifest import load_manifest, verify_manifest

        status, code, detail = verify_manifest(
            load_manifest(self.lance_path), model="bge-m3", dimension=DIM
        )
        self.assertEqual(status, "mismatch")
        self.assertEqual(code, "embedding_contract_mismatch")
        self.assertIn("Qwen3-Embedding-0.6B-GGUF", detail)

    def test_indexer_refuses_to_append_under_a_second_model(self):
        from chunker.semantic import CHUNKER_ID
        from storage.index_manifest import ensure_manifest

        _manifest, code, detail = ensure_manifest(
            self.lance_path, model="bge-m3", dimension=DIM, chunker=CHUNKER_ID
        )
        self.assertEqual(code, "embedding_contract_mismatch")
        self.assertIn("bge-m3", detail)

    def test_server_that_reports_no_model_is_unverified_not_blocked(self):
        self.addCleanup(self.server.serve_model, "Qwen3-Embedding-0.6B-GGUF", True)
        self.server.serve_model("", report=False)
        self.provider._contract_status = "unchecked"

        out = self._search("вентиляция", top_k=2, debug=True)

        self.assertNotEqual(out["debug"].get("status"), "blocked")
        self.assertEqual(out["debug"]["embedding_contract"]["status"], "unverified")

    # ── parent hydration ─────────────────────────────────────────────────

    def test_results_carry_parent_context_not_child_chunks(self):
        results = self._search("противодымная вентиляция", top_k=3)
        sources = [r["context_source"] for r in results]
        self.assertTrue(
            any(s.startswith("parent") for s in sources),
            f"every result fell back to a child chunk: {sources}",
        )

    def test_parent_hydration_is_reported_in_the_trace(self):
        out = self._search("противодымная вентиляция", top_k=3, debug=True)
        hydration = out["debug"]["retrieval"]["parent_hydration"]

        self.assertGreater(hydration["hydrated"], 0)
        self.assertEqual(hydration["error"], "")

    def test_hydration_failure_is_visible_instead_of_silent(self):
        from storage import vector_store

        missing = Path(self.tmp.name) / "absent.db"
        with patch.object(vector_store, "_get_sqlite_path", return_value=missing):
            from rag_server import tools

            with patch.object(
                tools, "_db_paths", return_value=(self.lance_path, missing)
            ), patch.object(
                tools, "_cfg", return_value={"retrieval": {"auto_rerank": False}}
            ):
                out = tools.search_documents(
                    "вентиляция", top_k=2, use_cache=False, debug=True
                )

        hydration = out["debug"]["retrieval"]["parent_hydration"]
        self.assertEqual(hydration["hydrated"], 0)
        self.assertIn("not found", hydration["error"])

    # ── rerank contract on a live endpoint ───────────────────────────────

    def test_rerank_contract_is_recorded_against_a_live_reranker(self):
        from rag_server import tools

        cfg = {
            "retrieval": {
                "auto_rerank": True,
                "rerank_endpoint": f"{self.server.base}/reranking",
                "rerank_model": "stub-reranker",
                "rerank_candidate_limit": 8,
            }
        }
        with patch.object(
            tools, "_db_paths", return_value=(self.lance_path, self.meta_path)
        ), patch.object(tools, "_cfg", return_value=cfg), \
             patch("rag_server.reranker._rerank_config",
                   return_value=(f"{self.server.base}/reranking", "stub-reranker", 8)):
            out = tools.search_documents(
                "вентиляция воздухообмен", top_k=2, rerank=True,
                use_cache=False, debug=True,
            )

        rerank = out["debug"]["rerank"]
        self.assertEqual(rerank["status"], "applied")
        self.assertEqual(rerank["model"], "stub-reranker")
        self.assertEqual(rerank["candidate_limit"], 8)
        self.assertGreater(rerank["input_count"], 0)
        self.assertGreaterEqual(rerank["pool_count"], rerank["returned_count"])
        self.assertIn("head_changed", rerank)


if __name__ == "__main__":
    unittest.main()
