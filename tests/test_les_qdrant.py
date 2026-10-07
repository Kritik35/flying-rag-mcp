"""The Les Qdrant collection works as a second store behind search_documents.

This file used to be a script that ran no test under unittest. The bridge it
exercised found nothing: it queried an unnamed vector and then one named
"text", and the collection has "dense" and "bm25_sparse".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from storage import qdrant_store  # noqa: E402


class LesSparseEncodingTests(unittest.TestCase):
    """Term ids must be the ones Les wrote; values computed with Les's own code
    (backend/inference/bm25_sparse.py) on 2026-10-07."""

    REFERENCE = {
        "Кратность воздухообмена в помещениях уборочного инвентаря по СП 60.13330": {
            1620471369: 1.0, 730221101: 1.0, 830842725: 1.0, 1500518915: 1.0,
            874693591: 1.0, 956665003: 1.0},
        "Огнезадерживающие клапаны EI 90 в системах противодымной вентиляции": {
            1975588349: 1.0, 2119103356: 1.0, 1991425049: 1.0, 515884570: 1.0,
            1577609637: 1.0},
        "BB_63 PE N": {1708356950: 1.0, 1396637406: 1.0, 2013832146: 1.0},
        "какие требования нормы": {},
    }

    def test_matches_les(self):
        for text, expected in self.REFERENCE.items():
            self.assertEqual(qdrant_store.encode_bm25(text), expected, text)


def _point(pid, text, role="evidence", file_name="docs/a.pdf", before="", after=""):
    return SimpleNamespace(id=pid, score=0.5, payload={
        "text": text, "node_role": role, "file_name": file_name, "doc_id": f"d{pid}",
        "parent_id": f"p{pid}", "section_heading": "4.1", "context_before": before,
        "context_after": after, "dataset_name": "ds"})


class StoreContractTests(unittest.TestCase):
    def _run(self, points, **kw):
        calls = []

        class Client:
            def query_points(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(points=points)

        with mock.patch.object(qdrant_store, "_client", return_value=Client()), \
                mock.patch.object(qdrant_store, "_vector_names", return_value=("dense", "bm25_sparse")), \
                mock.patch.object(qdrant_store, "settings",
                                  return_value={"enabled": True, "qdrant_url": "u",
                                                "collection_name": "c"}):
            trace: dict = {}
            rows = qdrant_store.search(None, [0.1] * 4, top_k=kw.pop("top_k", 5),
                                       trace=trace, **kw)
        return rows, trace, calls

    def test_hybrid_rrf_over_evidence_nodes(self):
        rows, trace, calls = self._run([_point(1, "текст", before="до", after="после")],
                                       query_text="кратность воздухообмена")
        self.assertEqual(trace["channels"], ["dense", "bm25_sparse"])
        self.assertEqual(trace["fusion"], "rrf")
        prefetch = calls[0]["prefetch"]
        self.assertEqual([p.using for p in prefetch], ["dense", "bm25_sparse"])
        roles = [c.match.value for c in prefetch[0].filter.must if c.key == "node_role"]
        self.assertEqual(roles, ["evidence"])
        self.assertEqual(rows[0]["child_text"], "текст")
        self.assertEqual(rows[0]["text"], "до\nтекст\nпосле")
        self.assertEqual(rows[0]["file_name"], "a.pdf")

    def test_a_query_without_terms_falls_back_to_dense_honestly(self):
        _rows, trace, calls = self._run([_point(1, "т")], query_text="какие требования нормы")
        self.assertEqual(trace["channels"], ["dense"])
        self.assertEqual(calls[0]["using"], "dense")
        self.assertIn("no sparse terms", trace["degraded_reason"])

    def test_folder_filter_applies_to_the_path(self):
        rows, _t, _c = self._run([_point(1, "a", file_name="ПД/РАЗДЕЛ 5/x.pdf"),
                                  _point(2, "b", file_name="НТД/y.pdf")],
                                 query_text="вентиляция", folder_filter="РАЗДЕЛ 5")
        self.assertEqual([r["file_name"] for r in rows], ["x.pdf"])


class LiveCollectionTests(unittest.TestCase):
    """Against the running Les Qdrant, when it is there."""

    @classmethod
    def setUpClass(cls):
        if not qdrant_store.is_enabled():
            raise unittest.SkipTest("les_integration is disabled")
        state = qdrant_store.health()
        if not state.get("ok"):
            raise unittest.SkipTest(f"Qdrant unreachable: {state.get('error')}")
        from embedder.client import check_connection
        if not check_connection():
            raise unittest.SkipTest("embedding server offline")

    def test_search_documents_runs_the_pipeline_on_qdrant(self):
        from rag_server.tools import search_documents

        out = search_documents("кратность воздухообмена электрощитовой", top_k=3,
                               use_cache=False, debug=True, use_les_db=True)
        trace = out["debug"]["retrieval"]
        self.assertEqual(trace["store"], "qdrant")
        self.assertIn("bm25_sparse", trace["channels"])
        self.assertTrue(out["results"])
        self.assertTrue(all(r["context_source"].startswith("les_") for r in out["results"]))


if __name__ == "__main__":
    unittest.main()
