"""Offline regression for explicit clause identity over unrelated high scores.

No actual document text, no real model, corpus, network or production search.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_server.exact_clause_priority import preserve_requested_clause
from storage.source_focus import concentrate_sources
from rag_server.tools import fill_to_top_k
from tests.test_retrieval_clause_edition_014 import _create_synthetic_meta_db


SOURCE = "НТД/СП 7.13130.2013.docx"
DERIVED = {
    "chunk_id": "clause_6.10",
    "derived_clause_id": "clause_6.10",
    "derived_label": "clause_6.10",
    "retrieval_origin": "ENR_DERIVED_CLAUSE",
    "source_path": SOURCE,
    "file_name": "СП 7.13130.2013.docx",
    "doc_id": "norm_clause",
    "section": "Пункт 6.10",
    "parent_ids": ["973d9901_p_0021", "973d9901_p_0022"],
    "physical_parent_ids": ["973d9901_p_0021", "973d9901_p_0022"],
    "physical_child_chunk_ids": ["UNKNOWN"],
    "score": 0.85,
    "score_kind": "enr_deterministic_priority",
    "clause_status": "context_partial",
    "evidence_status": "EVIDENCE_PARTIAL",
    "structural_start_verified": True,
    "structural_end_verified": False,
    "continuity_verified": True,
    "text": "6.10 Synthetic requirement EI 30 and EI 15, final boundary unverified.",
}


def noise_hits() -> list[dict]:
    return [
        {"chunk_id": "cover_1", "doc_id": "doc_A", "source_path": SOURCE,
         "score": 1.0, "section": "Предисловие", "text": "Приказ об утверждении СП 7"},
        {"chunk_id": "cover_2", "doc_id": "doc_A", "source_path": SOURCE,
         "score": 0.945, "section": "Приказ", "text": "Отмена предыдущего приказа"},
        {"chunk_id": "reference_1", "doc_id": "doc_B", "source_path": "НТД/СП 514.1311500.docx",
         "score": 1.0, "text": "Ссылка на СП 7 в другом документе"},
        {"chunk_id": "reference_2", "doc_id": "doc_C", "source_path": "НТД/Приказ-116.docx",
         "score": 1.0, "text": "Ссылка на СП 7 в приложении"},
        {"chunk_id": "reference_3", "doc_id": "doc_B", "source_path": "НТД/СП 514.1311500.docx",
         "score": 1.0, "text": "Еще одно косвенное упоминание"},
    ]


class ExplicitClausePriorityTests(unittest.TestCase):
    def _prioritize(self, visible, derived=None, **kwargs):
        return preserve_requested_clause(
            visible, DERIVED if derived is None else derived,
            target_clause=kwargs.get("target_clause", "6.10"),
            target_sources=kwargs.get("target_sources", [SOURCE]),
            top_k=kwargs.get("top_k", 5),
            folder_filter=kwargs.get("folder_filter"),
        )

    def test_q010_reproduction_source_concentration_drops_partial_without_fix(self):
        noise = noise_hits()
        pool = noise + [dict(DERIVED)]
        focused = concentrate_sources(pool, max_docs=3, min_score=0.3)
        self.assertNotIn("clause_6.10", [x["chunk_id"] for x in focused])
        previous = fill_to_top_k(focused, pool, 5)
        self.assertEqual(len(previous), 5)
        self.assertNotIn("clause_6.10", [x["chunk_id"] for x in previous])

        fixed, reason = self._prioritize(previous)
        self.assertEqual(reason, "partial_requested_clause_pinned")
        self.assertEqual([x["chunk_id"] for x in fixed],
                         ["clause_6.10"] + [x["chunk_id"] for x in previous[:4]])
        self.assertEqual(fixed[0]["score"], 0.85)
        self.assertEqual(fixed[0]["score_kind"], "enr_deterministic_priority")
        self.assertEqual(fixed[0]["evidence_status"], "EVIDENCE_PARTIAL")
        self.assertFalse(fixed[0]["structural_end_verified"])
        self.assertEqual(fixed[0]["rank_policy"], "explicit_target_clause_identity")
        self.assertEqual(fixed[0]["evidence_warning"], "PARTIAL_CLAUSE_STRUCTURAL_END_UNVERIFIED")
        self.assertEqual(DERIVED["score"], 0.85)  # no mutating existing evidence

    def test_verified_full_target_clauses_not_displaced_by_partial(self):
        same_clause_full = {
            **noise_hits()[0],
            "chunk_id": "verified_6_10",
            "section": "Пункт 6.10",
            "clause_status": "context_sufficient",
            "structural_start_verified": True,
            "structural_end_verified": True,
            "score": 0.95,
        }
        fixed, why = self._prioritize([same_clause_full] + noise_hits()[1:])
        self.assertEqual(fixed[0]["chunk_id"], "verified_6_10")
        self.assertEqual(why, "verified_target_already_visible")

    def test_verified_full_target_promoted_even_from_later_rank(self):
        full = {
            **noise_hits()[0],
            "chunk_id": "verified_target",
            "section": "Пункт 6.10",
            "clause_status": "context_sufficient",
            "structural_start_verified": True,
            "structural_end_verified": True,
        }
        results = noise_hits()[:2] + [full] + noise_hits()[2:4]
        fixed, why = self._prioritize(results)
        self.assertEqual(why, "verified_target_promoted")
        self.assertEqual(fixed[0]["chunk_id"], "verified_target")
        self.assertEqual(len(fixed), 5)

    def test_mismatched_source_or_explicit_folder_cannot_force_norm(self):
        results = noise_hits()
        wrong = {**DERIVED, "source_path": "НТД/ДРУГОЙ_СП_7.docx"}
        self.assertEqual(self._prioritize(results, wrong)[1], "source_mismatch")
        self.assertEqual(self._prioritize(results, folder_filter="Проект/ОВ2")[1], "scope_mismatch")
        self.assertEqual(results[0]["chunk_id"], "cover_1")

    def test_no_verified_heading_or_parent_never_pinned(self):
        results = noise_hits()
        bad_start = {**DERIVED, "structural_start_verified": False}
        no_parent = {**DERIVED, "physical_parent_ids": ["UNKNOWN"]}
        wrong_status = {**DERIVED, "evidence_status": "USABLE_FOR_ANSWER"}
        self.assertEqual(self._prioritize(results, bad_start)[1], "unverified_derived_clause")
        self.assertEqual(self._prioritize(results, no_parent)[1], "unverified_derived_clause")
        self.assertEqual(self._prioritize(results, wrong_status)[1], "inconsistent_partial_clause")

    def test_generic_or_other_clause_requests_are_not_changed(self):
        original = noise_hits()
        fixed, reason = self._prioritize(original, target_clause="6.4")
        self.assertEqual(reason, "unverified_derived_clause")
        self.assertEqual(fixed, original)
        fixed, reason = preserve_requested_clause(original, DERIVED,
            target_clause=None, target_sources=[SOURCE], top_k=5)
        self.assertEqual(reason, "not_applicable")
        self.assertEqual(fixed, original)

    @patch("rag_server.tools._cfg")
    @patch("rag_server.tools._db_paths")
    @patch("embedder.client.get_embeddings")
    @patch("storage.vector_store.search")
    def test_real_search_documents_pipeline_preserves_partial_before_cover(
        self, mock_search, mock_embeddings, mock_paths, mock_cfg
    ):
        """Real NormRegistry+search_documents; only storage and embedding are mocked."""
        from rag_server.tools import search_documents
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "fixture.db"
            _create_synthetic_meta_db(db)
            # sqlite3.Connection's with-block does NOT close the Windows file handle.
            with closing(sqlite3.connect(db)) as conn:
                conn.execute(
                    "INSERT INTO files (file_name, source_path, dataset) VALUES (?, ?, ?)",
                    ("СП 7.13130.2013.docx", SOURCE, "normative"),
                )
                conn.execute(
                    "INSERT INTO parent_chunks (parent_id, source_path, parent_text, created_at)"
                    " VALUES (?, ?, ?, datetime('now'))",
                    ("973d9901_p_0021", SOURCE,
                     "6.10 Синтетический пункт об условиях EI 30, без окончания."),
                )
                conn.execute(
                    "INSERT INTO parent_chunks (parent_id, source_path, parent_text, created_at)"
                    " VALUES (?, ?, ?, datetime('now'))",
                    ("973d9901_p_0022", SOURCE,
                     "а) Элемент EI 15 продолжается, конец пункта не доказан."),
                )
                conn.commit()
            lance_path = root / "lancedb"
            lance_path.mkdir()
            mock_paths.return_value = (lance_path, db)
            mock_cfg.return_value = {
                "storage": {"lancedb_path": "lancedb", "metadata_db": "fixture.db"},
                "retrieval": {"auto_rerank": False},
            }
            mock_embeddings.return_value = [[0.1] * 10]
            mock_search.return_value = noise_hits()
            response = search_documents(
                "СП 7.13130 пункт 6.10", debug=True, use_cache=False, rerank=False
            )
        self.assertIsInstance(response, dict)
        hits = response["results"]
        self.assertEqual(hits[0]["chunk_id"], "clause_6.10")
        self.assertEqual(hits[0]["clause_status"], "context_partial")
        self.assertEqual(hits[0]["evidence_status"], "EVIDENCE_PARTIAL")
        self.assertFalse(hits[0]["structural_end_verified"])
        self.assertEqual(hits[0]["score_kind"], "enr_deterministic_priority")
        self.assertLessEqual(len(hits), 5)
        self.assertEqual(response["debug"]["retrieval"]["explicit_clause_visibility"],
                         "partial_requested_clause_pinned")


if __name__ == "__main__":
    unittest.main()
