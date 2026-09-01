"""A scoped hybrid search must search inside the scope, not filter after it.

The hybrid branch applied its ``where`` with ``prefilter=False``: candidates
were taken globally first and the scope was applied to what came back. On the
live index that left almost nothing — measured on 1.25M chunks with a limit of
48 candidates:

    source_path LIKE '%СП 484.1311500%'   post-filter  1 row    prefilter 48
    source_path LIKE '%ОВ2%'              post-filter  5 rows   prefilter 48

Silent, too: a handful of rows is still "rows", so the trace reported a healthy
hybrid rather than a degraded search. The dense fallback right below it already
used ``prefilter=True``.
"""
from __future__ import annotations

import hashlib
import math
import tempfile
import unittest
from pathlib import Path

DIM = 32
NOISE_DOCS = 40
NOISE_CHUNKS = 6
SCOPED_CHUNKS = 8


def _vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in str(text or "").casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vec[int.from_bytes(digest[:4], "big") % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class ScopedHybridSearchTests(unittest.TestCase):
    """The scoped document is deliberately unlike the query.

    It therefore never enters the global candidate window, which is exactly the
    case a post-filter cannot serve: it can only discard, so it discards
    everything the scope asked for.
    """

    @classmethod
    def setUpClass(cls):
        from chunker.semantic import Chunk
        from embedder.batcher import EmbeddingResult
        from storage.vector_store import ensure_fts_index, upsert_chunks

        cls.tmp = tempfile.TemporaryDirectory()
        cls.lance_path = Path(cls.tmp.name) / "lancedb"

        chunks, embeddings = [], []

        def add(doc_id: str, source: str, index: int, text: str) -> None:
            chunk_id = f"{doc_id}_c{index:03d}"
            chunks.append(Chunk(
                doc_id=doc_id, chunk_id=chunk_id, text=text,
                metadata={"source_path": source, "file_name": Path(source).name,
                          "namespace": "normative", "format": "docx"},
            ))
            embeddings.append(EmbeddingResult(chunk_id=chunk_id,
                                              embedding=_vector(text)))

        for d in range(NOISE_DOCS):
            for i in range(NOISE_CHUNKS):
                add(f"noise{d:02d}", rf"C:\corpus\СП {100 + d}.13330.docx", i,
                    f"извещатели пожарной сигнализации размещение {d} {i}")
        for i in range(SCOPED_CHUNKS):
            add("scoped", r"C:\corpus\СП 484.1311500.2020.docx", i,
                f"водоотведение канализация насосная станция раздел {i}")

        upsert_chunks(cls.lance_path, chunks, embeddings, dim=DIM)
        ensure_fts_index(cls.lance_path, dim=DIM)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _search(self, folder_filter):
        from storage.vector_store import search

        trace: dict = {}
        rows = search(
            self.lance_path, _vector("извещатели пожарной сигнализации"),
            top_k=5, folder_filter=folder_filter,
            query_text="извещатели пожарной сигнализации",
            hybrid=True, trace=trace,
        )
        return rows, trace

    def test_a_scoped_search_returns_the_scoped_document(self):
        rows, _trace = self._search("СП 484.1311500")

        self.assertTrue(rows, "the scope returned nothing at all")
        self.assertTrue(
            all("484.1311500" in r["source_path"] for r in rows),
            "results leaked outside the requested scope",
        )

    def test_a_scoped_search_is_not_silently_reduced_to_a_handful(self):
        scoped, _ = self._search("СП 484.1311500")
        unscoped, _ = self._search(None)

        self.assertGreaterEqual(len(scoped), min(len(unscoped), 3))

    def test_a_scoped_hybrid_search_stays_hybrid(self):
        _rows, trace = self._search("СП 484.1311500")

        self.assertIn("fts", trace["channels"])
        self.assertFalse(trace["degraded"], trace.get("degraded_reason"))


if __name__ == "__main__":
    unittest.main()
