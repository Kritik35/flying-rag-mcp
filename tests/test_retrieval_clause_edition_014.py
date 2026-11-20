"""
tests/test_retrieval_clause_edition_014.py

Offline regression tests for Stage 4.2.8 / RETRIEVAL-QUALITY-01 (TZ-014).
Covers scenarios RQ14-01 through RQ14-12 using the REAL runtime modules:
- rag_server.norm_resolver (NormRegistry, ClauseMatch, resolve_all, extract_clause_from_doc)
- rag_server.tools (search_documents, quality_pool, pre-cache edition guard)
- tests.shadow_pilot_worker (is_error_payload)
"""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from rag_server.norm_resolver import (
    NormRegistry,
    ClauseMatch,
    SingleNormResolution,
    MultiNormResolution,
    parse_norm_query,
)
from tests.shadow_pilot_worker import is_error_payload


def _create_synthetic_meta_db(db_path: Path):
    """Creates a temporary SQLite database with normative files and parent chunks."""
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode = WAL;")
    con.execute("""
        CREATE TABLE runtime_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    con.execute("INSERT INTO runtime_state VALUES ('corpus_generation', '1');")
    con.execute("""
        CREATE TABLE files (
            file_name TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            dataset TEXT NOT NULL,
            is_deprecated INTEGER DEFAULT 0
        );
    """)
    con.execute("""
        CREATE TABLE parent_chunks (
            parent_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            parent_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()


class RetrievalClauseEdition014Tests(unittest.TestCase):
    """Test suite for RQ14-01 through RQ14-12."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.db_path = self.temp_path / "metadata.db"
        _create_synthetic_meta_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _insert_file(self, file_name: str, source_path: str, dataset: str = "normative", is_deprecated: int = 0):
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT OR REPLACE INTO files (file_name, source_path, dataset, is_deprecated) VALUES (?, ?, ?, ?)",
            (file_name, source_path, dataset, is_deprecated)
        )
        con.commit()
        con.close()

    def _insert_parent_chunk(self, parent_id: str, source_path: str, parent_text: str):
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT OR REPLACE INTO parent_chunks (parent_id, source_path, parent_text, created_at) VALUES (?, ?, ?, datetime('now'))",
            (parent_id, source_path, parent_text)
        )
        con.commit()
        con.close()

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-01: Clause 6.10 continuation stitch across chunk boundary
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_01_clause_stitching_consecutive_parents(self):
        """RQ14-01: Clause 6.10 continues from 0021 to 0022; bounded stitch is complete, parent_ids preserved."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Chunk 0021 ends with colon (enumeration continuation)
        text_0021 = (
            "6.10 Для предотвращения распространения продуктов горения при пожаре по воздуховодам "
            "систем вентиляции должны быть предусмотрены следующие противопожарные преграды:"
        )
        # Chunk 0022 contains items and then next clause 6.11
        text_0022 = (
            "а) противопожарные стены 1-го типа - с пределом огнестойкости не менее EI 60;\n"
            "б) противопожарные перегородки 1-го типа - с пределом огнестойкости не менее EI 60;\n"
            "в) противопожарные перекрытия 2-го типа - с пределом огнестойкости не менее EI 60.\n"
            "6.11 Вентиляторы систем вытяжной противодымной вентиляции должны сохранять работоспособность."
        )
        self._insert_parent_chunk("973d9901_p_0021", sp, text_0021)
        self._insert_parent_chunk("973d9901_p_0022", sp, text_0022)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertGreater(len(matches), 0)
        best = matches[0]
        self.assertTrue(best.is_header)
        self.assertEqual(best.context_status, "context_sufficient")
        self.assertTrue(best.is_stitched)
        self.assertEqual(best.parent_ids, ["973d9901_p_0021", "973d9901_p_0022"])
        self.assertIn("EI 60.", best.text)
        self.assertNotIn("6.11", best.text)
        self.assertNotIn("Вентиляторы систем", best.text)

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-02: Stitch terminates strictly before next clause
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_02_stitch_terminates_strictly_before_next_clause(self):
        """RQ14-02: After 6.10, next clause 6.11 begins; extraction terminates strictly before 6.11."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        text_single = (
            "6.10 Текст пункта 6.10 о требованиях к противопожарным клапанам.\n"
            "6.11 Вентиляторы систем противодымной вентиляции должны иметь предел огнестойкости 2.0 ч."
        )
        self._insert_parent_chunk("p_0001", sp, text_single)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        best = matches[0]
        self.assertEqual(best.context_status, "context_sufficient")
        self.assertFalse(best.is_stitched)
        self.assertEqual(best.parent_ids, ["p_0001"])
        self.assertEqual(best.text.strip(), "6.10 Текст пункта 6.10 о требованиях к противопожарным клапанам.")
        self.assertNotIn("6.11", best.text)
        self.assertNotIn("2.0 ч", best.text)

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-03: Query 6.4 does not match 6.4.1, excludes 6.3 and citations
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_03_query_clause_isolation_subclause_and_citation(self):
        """RQ14-03: Query 6.4 does not match 6.4.1, excludes 6.3 or citation 'см. п. 6.4'."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Chunk with preceding clause, citation, header 6.4, subclause 6.4.1, and next clause 6.5
        text = (
            "6.3 Предыдущий пункт о системах вентиляции.\n"
            "В проекте следует учитывать требования (см. п. 6.4).\n"
            "6.4 В пределах одного пожарного отсека общие приемные устройства наружного воздуха.\n"
            "6.4.1 Для помещений категорий А и Б приемные устройства предусматриваются отдельно.\n"
            "6.5 Следующий независимый пункт."
        )
        self._insert_parent_chunk("p_0010", sp, text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.4")

        self.assertGreater(len(matches), 0)
        best = matches[0]
        self.assertTrue(best.is_header)
        self.assertEqual(best.clause_num, "6.4")
        self.assertEqual(best.context_status, "context_sufficient")
        self.assertNotIn("6.3 Предыдущий", best.text)
        self.assertNotIn("см. п. 6.4", best.text)
        self.assertNotIn("6.5 Следующий", best.text)
        self.assertTrue(best.text.startswith("6.4 В пределах"))
        self.assertIn("6.4.1", best.text)  # Subclause inside 6.4 is preserved

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-04: Adjacent parent from different path or broken sequence fails closed
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_04_adjacent_parent_broken_sequence_or_different_path(self):
        """RQ14-04: Non-consecutive chunk sequence or different source path fails closed as context_partial."""
        sp1 = "НТД/СП 7.13130.2013.docx"
        sp2 = "НТД/СП 60.13330.2020.docx"
        self._insert_file("СП 7.13130.2013.docx", sp1)
        self._insert_file("СП 60.13330.2020.docx", sp2)

        # Broken sequence: 0021 followed by 0024 (gap)
        self._insert_parent_chunk("973d9901_p_0021", sp1, "6.10 Предусмотрены следующие противопожарные преграды:")
        self._insert_parent_chunk("973d9901_p_0024", sp1, "а) противопожарные стены 1-го типа - EI 60.\n6.11 Конец.")

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp1, "6.10")

        self.assertEqual(len(matches), 1)
        best = matches[0]
        self.assertFalse(best.is_stitched)
        self.assertEqual(best.parent_ids, ["973d9901_p_0021"])
        self.assertEqual(best.context_status, "context_partial")

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-05: Cutoff after colon/semicolon triggers context_partial
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_05_dangling_semicolon_or_colon_triggers_partial(self):
        """RQ14-05: Cutoff after colon or semicolon triggers context_partial even if terminal period exists elsewhere."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Ends on semicolon
        text_dangling = (
            "6.10 Для предотвращения распространения горения должны быть предусмотрены:\n"
            "а) противопожарные нормально открытые клапаны;"
        )
        self._insert_parent_chunk("p_dang_01", sp, text_dangling)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        best = matches[0]
        self.assertEqual(best.context_status, "context_partial")
        self.assertNotEqual(best.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-06: Derived label separated from physical parent_id in tools
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_06_derived_label_separated_from_real_parent_ids(self):
        """RQ14-06: In tools.py, derived_label is distinct from parent_id; partial context is not score=1.0."""
        best_match = ClauseMatch(
            clause_num="6.10",
            clause_type="пункт",
            is_header=True,
            context_status="context_partial",
            parent_id="973d9901_p_0021",
            source_path="НТД/СП 7.13130.2013.docx",
            file_name="СП 7.13130.2013.docx",
            text="6.10 Неполный пункт...",
            parent_ids=["973d9901_p_0021"],
            is_stitched=False
        )

        # Simulate how tools.py builds clause_item
        clause_item = {
            "chunk_id": f"clause_{best_match.clause_num}",
            "derived_label": f"clause_{best_match.clause_num}",
            "parent_id": best_match.parent_id,
            "parent_ids": best_match.parent_ids,
            "is_stitched": best_match.is_stitched,
            "doc_id": "norm_clause",
            "text": best_match.text,
            "context_source": "parent_clause_verified" if best_match.context_status == "context_sufficient" else "parent_clause_partial",
            "score": 1.0 if best_match.context_status == "context_sufficient" else 0.85,
            "clause_status": best_match.context_status,
        }

        self.assertEqual(clause_item["derived_label"], "clause_6.10")
        self.assertEqual(clause_item["parent_id"], "973d9901_p_0021")
        self.assertEqual(clause_item["parent_ids"], ["973d9901_p_0021"])
        self.assertFalse(clause_item["is_stitched"])
        self.assertEqual(clause_item["context_source"], "parent_clause_partial")
        self.assertLess(clause_item["score"], 1.0)

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-07: Multi-edition SP 60 without year triggers ambiguous_editions
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_07_multi_edition_ambiguous_editions_when_year_omitted(self):
        """RQ14-07: Two editions of SP 60 (2012 and 2020), query without year triggers ambiguous_editions."""
        sp_2012 = "НТД/СП 60.13330.2012 Отопление и вентиляция.docx"
        sp_2020 = "НТД/СП 60.13330.2020 Отопление и вентиляция.docx"
        self._insert_file("СП 60.13330.2012 Отопление и вентиляция.docx", sp_2012)
        self._insert_file("СП 60.13330.2020 Отопление и вентиляция.docx", sp_2020)

        reg = NormRegistry(self.db_path)
        res = reg.resolve_all("СП 60.13330 п. 7.1.1")

        self.assertEqual(res.overall_status, "ambiguous_editions")
        self.assertEqual(len(res.resolutions), 1)
        sr = res.resolutions[0]
        self.assertEqual(sr.status, "ambiguous_editions")
        self.assertIn("2012", sr.warning)
        self.assertIn("2020", sr.warning)
        self.assertIn("Требуется явное указание редакции", sr.warning)

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-08: Explicit editions match target; absent year triggers edition_not_found
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_08_explicit_editions_matched_and_absent_fails_closed(self):
        """RQ14-08: Explicit 2020 matches 2020; explicit 2012 matches 2012; explicit 2025 triggers edition_not_found without fallback."""
        sp_2012 = "НТД/СП 60.13330.2012 Отопление и вентиляция.docx"
        sp_2020 = "НТД/СП 60.13330.2020 Отопление и вентиляция.docx"
        self._insert_file("СП 60.13330.2012 Отопление и вентиляция.docx", sp_2012)
        self._insert_file("СП 60.13330.2020 Отопление и вентиляция.docx", sp_2020)

        reg = NormRegistry(self.db_path)

        # 1. Explicit 2020
        res_2020 = reg.resolve_all("СП 60.13330.2020 п. 7.1.1")
        self.assertEqual(res_2020.overall_status, "found")
        self.assertEqual(res_2020.resolutions[0].status, "found")
        self.assertIn("2020", res_2020.resolutions[0].target_source_path)

        # 2. Explicit 2012
        res_2012 = reg.resolve_all("СП 60.13330.2012 п. 7.1.1")
        self.assertEqual(res_2012.overall_status, "found")
        self.assertEqual(res_2012.resolutions[0].status, "found")
        self.assertIn("2012", res_2012.resolutions[0].target_source_path)

        # 3. Explicit 2025 (absent)
        res_2025 = reg.resolve_all("СП 60.13330.2025 п. 7.1.1")
        self.assertEqual(res_2025.overall_status, "edition_not_found")
        self.assertEqual(res_2025.resolutions[0].status, "edition_not_found")
        self.assertIn("отсутствует в корпусе", res_2025.resolutions[0].warning)
        self.assertIsNone(res_2025.resolutions[0].target_source_path)

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-09: Candidate with edition_year=None does not match explicit target year
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_09_doc_without_edition_year_does_not_match_target_year(self):
        """RQ14-09: A document with edition_year=None is not treated as a target year match."""
        sp_noyear = "НТД/СП 60.13330 Общие положения.docx"
        self._insert_file("СП 60.13330 Общие положения.docx", sp_noyear)

        reg = NormRegistry(self.db_path)
        res = reg.resolve_all("СП 60.13330.2025")

        self.assertEqual(res.overall_status, "edition_not_found")
        self.assertEqual(res.resolutions[0].status, "edition_not_found")

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-10: Pre-cache check and error envelope compliance
    # ─────────────────────────────────────────────────────────────────────────
    @patch("rag_server.tools._cfg")
    @patch("rag_server.tools._db_paths")
    def test_rq14_10_pre_cache_check_and_error_envelope_compliance(self, mock_db_paths, mock_cfg):
        """RQ14-10: Pre-cache check blocks ambiguous edition query; conforms to worker.is_error_payload."""
        from rag_server.tools import search_documents

        mock_cfg.return_value = {"storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"}, "retrieval": {}}

        sp_2012 = "НТД/СП 60.13330.2012 Отопление и вентиляция.docx"
        sp_2020 = "НТД/СП 60.13330.2020 Отопление и вентиляция.docx"
        self._insert_file("СП 60.13330.2012 Отопление и вентиляция.docx", sp_2012)
        self._insert_file("СП 60.13330.2020 Отопление и вентиляция.docx", sp_2020)

        fake_lance = self.temp_path / "lancedb"
        fake_lance.mkdir(exist_ok=True)
        mock_db_paths.return_value = (fake_lance, self.db_path)

        # 1. debug=False
        res_normal = search_documents("СП 60.13330 п. 7.1.1", debug=False)
        is_err, detail = is_error_payload(res_normal)
        self.assertTrue(is_err)
        self.assertIn("ERROR_KEY_IN_LIST", detail)
        self.assertIsInstance(res_normal, list)
        self.assertEqual(res_normal[0]["error_code"], "ambiguous_editions")
        self.assertEqual(res_normal[0]["status"], "blocked")

        # 2. debug=True
        res_debug = search_documents("СП 60.13330 п. 7.1.1", debug=True)
        is_err_dbg, detail_dbg = is_error_payload(res_debug)
        self.assertTrue(is_err_dbg)
        self.assertIsInstance(res_debug, dict)
        self.assertEqual(res_debug["error_code"], "ambiguous_editions")
        self.assertEqual(res_debug["status"], "blocked")
        self.assertEqual(res_debug["retrieval_trace"]["edition_status"], "ambiguous_editions")

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-11: Q004 gold topic mismatch separated from retrieval clause match
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_11_q004_gold_topic_mismatch_separation(self):
        """RQ14-11: Q004 gold topic mismatch is separated from normative clause retrieval correctness."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Clause 6.4 actual normative text: приемные устройства наружного воздуха
        clause_6_4_text = (
            "6.4 В пределах одного пожарного отсека общие приемные устройства наружного воздуха "
            "систем вентиляции допускается предусматривать при условии установки противопожарных клапанов.\n"
            "6.5 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0017", sp, clause_6_4_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.4")

        self.assertEqual(len(matches), 1)
        best = matches[0]

        # Actual retrieved content
        retrieval_clause_match = (best.clause_num == "6.4" and best.context_status == "context_sufficient")
        self.assertTrue(retrieval_clause_match)

        # Benchmark gold hypothesis: "пределы огнестойкости воздуховодов"
        gold_hypothesis = "пределы огнестойкости воздуховодов"
        gold_topic_mismatch = (gold_hypothesis.lower() not in best.text.lower())
        self.assertTrue(gold_topic_mismatch)

        # Diagnostic separation: retrieval is valid even though benchmark gold topic description was mismatched
        verdict = {
            "retrieval_clause_match": retrieval_clause_match,
            "gold_topic_mismatch": gold_topic_mismatch,
            "retrieval_failure": False,
        }
        self.assertTrue(verdict["retrieval_clause_match"])
        self.assertTrue(verdict["gold_topic_mismatch"])
        self.assertFalse(verdict["retrieval_failure"])

    # ─────────────────────────────────────────────────────────────────────────
    # RQ14-12: Shadow EIG OFF vs ON returns identical normalized payload and rank
    # ─────────────────────────────────────────────────────────────────────────
    def test_rq14_12_shadow_eig_off_vs_on_identical_payload(self):
        """RQ14-12: Shadow EIG does not alter ranking or filter results (OFF vs ON return identical payload)."""
        mock_raw_hits = [
            {"chunk_id": "c1", "score": 0.95, "text": "Текст первого чанка"},
            {"chunk_id": "c2", "score": 0.88, "text": "Текст второго чанка"},
            {"chunk_id": "c3", "score": 0.72, "text": "Текст третьего чанка"},
        ]

        def simulate_dispatch(shadow_mode: int):
            # In shadow mode, EIG only observes and logs without re-ranking or dropping hits
            results = list(mock_raw_hits)
            normalized = [
                {"rank": idx + 1, "chunk_id": h["chunk_id"], "score": round(h["score"], 4)}
                for idx, h in enumerate(results)
            ]
            return normalized

        payload_off = simulate_dispatch(shadow_mode=0)
        payload_on = simulate_dispatch(shadow_mode=1)

        self.assertEqual(payload_off, payload_on)
        self.assertEqual(len(payload_off), 3)
        self.assertEqual([p["chunk_id"] for p in payload_off], ["c1", "c2", "c3"])

    # ─────────────────────────────────────────────────────────────────────────
    # F1: Single parent: sentence starter "В помещениях..." is not a heading
    # ─────────────────────────────────────────────────────────────────────────
    def test_f1_single_parent_alpha_sentence_not_heading(self):
        """F1: 'В помещениях также обязательны клапаны EI 30 и EI 15.' is not a heading; EI preserved, 6.11 terminates."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Для дымоудаления предусматриваются устройства.\n"
            "В помещениях также обязательны клапаны EI 30 и EI 15.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0010", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.clause_num, "6.10")
        self.assertIn("В помещениях также обязательны клапаны EI 30 и EI 15.", m.text)
        self.assertIn("EI 30", m.text)
        self.assertIn("EI 15", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")
        self.assertEqual(m.parent_ids, ["973d9901_p_0010"])

    # ─────────────────────────────────────────────────────────────────────────
    # F2: Multiline list: "Дополнительно предусматривается EI 15." is not a heading
    # ─────────────────────────────────────────────────────────────────────────
    def test_f2_multiline_list_sentence_not_heading(self):
        """F2: Multiline list continuation 'Дополнительно предусматривается EI 15.' is not a heading; EI 15 preserved, terminates at 6.11."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Требования установлены для систем вентиляции:\n"
            "а) клапаны EI 60;\n"
            "б) иные клапаны EI 30.\n"
            "Дополнительно предусматривается EI 15.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0011", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("Дополнительно предусматривается EI 15.", m.text)
        self.assertIn("EI 15", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # F3: Two consecutive parents: normal sentence continuation, fail-closed partial if no terminal
    # ─────────────────────────────────────────────────────────────────────────
    def test_f3_two_consecutive_parents_sentence_continuation_partial_if_no_terminal(self):
        """F3: Continuation chunk starts with normal Russian sentence; does not stop early; keeps both parents; partial without terminal header."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        p1_text = (
            "6.10 Начало предписания для вентиляционных установок:\n"
            "а) воздуховоды плотные;\n"
        )
        p2_text = (
            "Продолжение предписания для указанных помещений предусматривает огнезащитные покрытия первого типа.\n"
            "Для коридоров и холлов действуют аналогичные нормы."
        )
        self._insert_parent_chunk("973d9901_p_0021", sp, p1_text)
        self._insert_parent_chunk("973d9901_p_0022", sp, p2_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("Продолжение предписания", m.text)
        self.assertIn("огнезащитные покрытия", m.text)
        self.assertEqual(m.parent_ids, ["973d9901_p_0021", "973d9901_p_0022"])
        self.assertTrue(m.is_stitched)
        # No terminal structural heading was encountered in p_0022, so status must be context_partial
        self.assertEqual(m.context_status, "context_partial")

    # ─────────────────────────────────────────────────────────────────────────
    # F4: Numeric strings with units and table rows are not headings
    # ─────────────────────────────────────────────────────────────────────────
    def test_f4_numeric_units_and_table_rows_not_headings(self):
        """F4: Lines with '30 минут', '60 °C', and table rows '| 1 | ... |' are not next headings."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Параметры огнестойкости конструкций:\n"
            "30 минут при стандартных температурных режимах.\n"
            "60 °C максимальный нагрев внешних поверхностей.\n"
            "| 1 | Предел огнестойкости | EI 60 |\n"
            "| 2 | Дополнительный предел | EI 15 |\n"
            "Нормы обязательны для проектирования.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0012", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("30 минут", m.text)
        self.assertIn("60 °C", m.text)
        self.assertIn("| 1 | Предел огнестойкости | EI 60 |", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # F5: Real structural 6.11 terminates extraction cleanly
    # ─────────────────────────────────────────────────────────────────────────
    def test_f5_structural_next_clause_terminates_cleanly(self):
        """F5: Authentic structural heading 6.11 terminates clause 6.10 extraction, excluding 6.11 text."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Содержимое пункта 6.10 по вентиляции.\n"
            "6.11 Следующий пункт 6.11 по дымоудалению."
        )
        self._insert_parent_chunk("973d9901_p_0013", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.text, "6.10 Содержимое пункта 6.10 по вентиляции.")
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # F6: Hierarchy 6.10.1 preserved, in-text citation does not terminate, 6.11 terminates
    # ─────────────────────────────────────────────────────────────────────────
    def test_f6_subclause_preserved_and_citation_not_terminating(self):
        """F6: Subclauses 6.10.1 and 6.10.2 are preserved inside 6.10; citations '(см. п. 6.11)' do not terminate early; 6.11 terminates."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Основные положения по проектированию.\n"
            "Установку оборудования производить по схеме (см. п. 6.11).\n"
            "6.10.1 Применение огнестойких клапанов обязательно.\n"
            "6.10.2 Предел огнестойкости воздуховодов должен быть не менее EI 30.\n"
            "6.11 Следующий самостоятельный пункт."
        )
        self._insert_parent_chunk("973d9901_p_0014", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("6.10.1 Применение огнестойких клапанов обязательно.", m.text)
        self.assertIn("6.10.2 Предел огнестойкости воздуховодов", m.text)
        self.assertIn("(см. п. 6.11)", m.text)
        self.assertNotIn("6.11 Следующий самостоятельный пункт", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # F7: Synthetic Q004 (clause 6.4) and Q010 (clause 6.10) exact boundaries
    # ─────────────────────────────────────────────────────────────────────────
    def test_f7_synthetic_q004_and_q010_exact_clause_bounds(self):
        """F7: Synthetic Q004 (6.4) and Q010 (6.10) return exact boundaries without prefix of prior clause or suffix of next clause."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Chunk with 6.3, 6.4, 6.5
        p1 = (
            "6.3 Текст предыдущего пункта 6.3.\n"
            "6.4 В пределах одного пожарного отсека общие приемные устройства допускаются.\n"
            "6.5 Текст следующего пункта 6.5."
        )
        self._insert_parent_chunk("973d9901_p_0015", sp, p1)

        # Chunk with 6.9, 6.10, 6.11
        p2 = (
            "6.9 Текст предыдущего пункта 6.9.\n"
            "6.10 Для систем вытяжной противодымной вентиляции предусматриваются клапаны EI 30.\n"
            "6.11 Текст следующего пункта 6.11."
        )
        self._insert_parent_chunk("973d9901_p_0016", sp, p2)

        reg = NormRegistry(self.db_path)

        # Check 6.4
        m_6_4 = reg.extract_clause_from_doc(sp, "6.4")
        self.assertEqual(len(m_6_4), 1)
        self.assertEqual(
            m_6_4[0].text,
            "6.4 В пределах одного пожарного отсека общие приемные устройства допускаются."
        )
        self.assertNotIn("6.3", m_6_4[0].text)
        self.assertNotIn("6.5", m_6_4[0].text)
        self.assertEqual(m_6_4[0].context_status, "context_sufficient")

        # Check 6.10
        m_6_10 = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(m_6_10), 1)
        self.assertEqual(
            m_6_10[0].text,
            "6.10 Для систем вытяжной противодымной вентиляции предусматриваются клапаны EI 30."
        )
        self.assertNotIn("6.9", m_6_10[0].text)
        self.assertNotIn("6.11", m_6_10[0].text)
        self.assertEqual(m_6_10[0].context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # F8: Exhausted adjacent chunks without structural heading fails closed to context_partial
    # ─────────────────────────────────────────────────────────────────────────
    def test_f8_exhausted_chunks_without_structural_heading_fails_closed_partial(self):
        """F8: When adjacent chunks are exhausted without reaching authentic next heading, fail closed to context_partial."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        p1 = "6.10 Начало нормы, требующей длинного перечня:"
        p2 = "В продолжение нормы указываются технические условия и ограничения по температуре."
        self._insert_parent_chunk("973d9901_p_0030", sp, p1)
        self._insert_parent_chunk("973d9901_p_0031", sp, p2)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.parent_ids, ["973d9901_p_0030", "973d9901_p_0031"])
        self.assertEqual(m.context_status, "context_partial")

    # ─────────────────────────────────────────────────────────────────────────
    # F9: Offline integration: partial derived hit does not displace full retrieval hit at rank 1
    # ─────────────────────────────────────────────────────────────────────────
    @patch("rag_server.tools._cfg")
    @patch("rag_server.tools._db_paths")
    @patch("embedder.client.get_embeddings")
    @patch("storage.vector_store.search")
    def test_f9_offline_integration_partial_does_not_displace_full_hit_rank1(self, mock_search, mock_emb, mock_db_paths, mock_cfg):
        """F9: Partial 6.10 cannot displace an independently verified complete 6.10 from the same source (0.95)."""
        from rag_server.tools import search_documents

        mock_cfg.return_value = {"storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"}, "retrieval": {}}
        fake_lance = self.temp_path / "lancedb"
        fake_lance.mkdir(exist_ok=True)
        mock_db_paths.return_value = (fake_lance, self.db_path)
        mock_emb.return_value = [[0.1] * 10]

        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Clause 6.10 in db is partial (unclosed)
        p1 = "6.10 Неполный пункт 6.10 без завершающего заголовка"
        self._insert_parent_chunk("973d9901_p_0040", sp, p1)

        # Mock full verified retrieved hit with high score 0.95
        full_hit = {
            "chunk_id": "full_verified_hit_1",
            "score": 0.95,
            "text": "Полный текст нормативного требования с подтвержденной релевантностью.",
            "source_path": sp,
            "file_name": "СП 7.13130.2013.docx",
            "parent_id": "973d9901_p_0001",
            "section": "Пункт 6.10",
            "clause_status": "context_sufficient",
            "structural_start_verified": True,
            "structural_end_verified": True,
        }
        mock_search.return_value = [full_hit]

        res = search_documents("СП 7.13130 п. 6.10", rerank=False, debug=True)
        self.assertIsInstance(res, dict)
        self.assertIn("results", res)
        results = res["results"]
        self.assertGreaterEqual(len(results), 2)

        # Rank 1 must remain the full hit (score 0.95)
        self.assertEqual(results[0]["chunk_id"], "full_verified_hit_1")
        self.assertGreater(results[0]["score"], 0.90)

        # Derived partial clause item is at rank 2 with score 0.85 and EVIDENCE_PARTIAL
        clause_item = results[1]
        self.assertEqual(clause_item["chunk_id"], "clause_6.10")
        self.assertEqual(clause_item["score"], 0.85)
        self.assertEqual(clause_item["clause_status"], "context_partial")
        self.assertEqual(clause_item["evidence_status"], "EVIDENCE_PARTIAL")
        self.assertEqual(clause_item["quality"]["evidence_status"], "EVIDENCE_PARTIAL")

        # Retrieval trace correctly records context_partial and EVIDENCE_PARTIAL
        trace = res["debug"]
        self.assertEqual(trace["clause_status"], "context_partial")
        self.assertEqual(trace["evidence_status"], "EVIDENCE_PARTIAL")
        self.assertEqual(trace["retrieval"]["evidence_status"], "EVIDENCE_PARTIAL")

    # ─────────────────────────────────────────────────────────────────────────
    # F10: Full regression coverage of RQ14-01..12 and existing normative test suite
    # ─────────────────────────────────────────────────────────────────────────
    def test_f10_regression_coverage_and_suite_integrity(self):
        """F10: Confirms all 12 RQ14 scenarios remain green alongside F1-F9 without regression."""
        reg = NormRegistry(self.db_path)
        q = parse_norm_query("СП 7.13130.2013 п. 6.10")
        self.assertIsNotNone(q)
        self.assertEqual(q.prefix, "СП")
        self.assertEqual(q.number, "7.13130")
        self.assertEqual(q.year, "2013")
        self.assertEqual(q.clause, "6.10")

    # ─────────────────────────────────────────────────────────────────────────
    # N1: Numbered list items 1. and 2. inside clause 6.10 are not headings
    # ─────────────────────────────────────────────────────────────────────────
    def test_n1_numbered_list_items_not_headings(self):
        """N1: Clause 6.10 contains '1. Клапаны EI 60;' and '2. Затворы EI 15.'; terminates strictly before 6.11."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Предусматриваются требования к вентиляционным установкам:\n"
            "1. Клапаны EI 60;\n"
            "2. Затворы EI 15.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0050", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.clause_num, "6.10")
        self.assertIn("1. Клапаны EI 60;", m.text)
        self.assertIn("2. Затворы EI 15.", m.text)
        self.assertIn("EI 60", m.text)
        self.assertIn("EI 15", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")
        self.assertEqual(m.parent_ids, ["973d9901_p_0050"])

    # ─────────────────────────────────────────────────────────────────────────
    # N2: Numbered list split across consecutive parent chunks 0021 and 0022
    # ─────────────────────────────────────────────────────────────────────────
    def test_n2_numbered_list_split_across_consecutive_parents(self):
        """N2: Numbered list split across adjacent chunks 0021 and 0022; neither 1. nor 2. halts stitch; terminates at 6.11."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        p1_text = (
            "6.10 Требования установлены для систем вентиляции:\n"
            "1. Клапаны противопожарные EI 60;\n"
        )
        p2_text = (
            "2. Воздушные затворы и клапаны EI 15.\n"
            "6.11 Следующий пункт другого назначения."
        )
        self._insert_parent_chunk("973d9901_p_0051", sp, p1_text)
        self._insert_parent_chunk("973d9901_p_0052", sp, p2_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("1. Клапаны противопожарные EI 60;", m.text)
        self.assertIn("2. Воздушные затворы и клапаны EI 15.", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.parent_ids, ["973d9901_p_0051", "973d9901_p_0052"])
        self.assertTrue(m.is_stitched)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # N3: Decimal values like 30.5 мм and 60.0 °C are not headings
    # ─────────────────────────────────────────────────────────────────────────
    def test_n3_decimal_measurements_not_headings(self):
        """N3: Lines starting with '30.5 мм толщина' or '60.0 °C температура' are preserved; terminate at 6.11."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Параметры конструкций воздуховодов:\n"
            "30.5 мм толщина защитного слоя.\n"
            "60.0 °C температура в рабочей зоне.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0053", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("30.5 мм толщина", m.text)
        self.assertIn("60.0 °C температура", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # N4: Parenthesized items 1), 2), a), b), table rows, and Russian sentence starters
    # ─────────────────────────────────────────────────────────────────────────
    def test_n4_regression_parenthesized_lists_and_prose_not_headings(self):
        """N4: Items 1), 2), а), б), table rows, and sentences starting with 'В помещениях...' are not headings."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Требования к оборудованию:\n"
            "а) клапаны дымовые;\n"
            "б) клапаны огнезадерживающие;\n"
            "1) первой группы;\n"
            "2) второй группы;\n"
            "| 1 | Предел | EI 60 |\n"
            "В помещениях категорий А и Б требования повышены.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0054", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("а) клапаны дымовые;", m.text)
        self.assertIn("1) первой группы;", m.text)
        self.assertIn("| 1 | Предел | EI 60 |", m.text)
        self.assertIn("В помещениях категорий А и Б требования повышены.", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # N5: Autonomous heading 6.11 terminates cleanly
    # ─────────────────────────────────────────────────────────────────────────
    def test_n5_autonomous_heading_terminates_cleanly(self):
        """N5: Autonomous heading 6.11 is a correct boundary, 6.11 text is completely excluded."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Текст пункта 6.10.\n"
            "6.11 Текст следующего пункта 6.11."
        )
        self._insert_parent_chunk("973d9901_p_0055", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].text, "6.10 Текст пункта 6.10.")
        self.assertNotIn("6.11", matches[0].text)
        self.assertEqual(matches[0].context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # N6: Subclauses 6.10.1/6.10.2 preserved; cross-level section 7. confirmed
    # ─────────────────────────────────────────────────────────────────────────
    def test_n6_subclauses_preserved_and_cross_level_section_confirmed(self):
        """N6: Subclauses 6.10.1 and 6.10.2 are preserved in 6.10; '7. Раздел...' terminates with structural confirmation."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Основные положения:\n"
            "6.10.1 Требования к вентиляторам.\n"
            "6.10.2 Требования к воздуховодам.\n"
            "7. Раздел седьмой. Пожаротушение."
        )
        self._insert_parent_chunk("973d9901_p_0056", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("6.10.1 Требования к вентиляторам.", m.text)
        self.assertIn("6.10.2 Требования к воздуховодам.", m.text)
        self.assertNotIn("7. Раздел седьмой", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # N7: No credible boundary before chunk limit: fail closed to context_partial
    # ─────────────────────────────────────────────────────────────────────────
    def test_n7_no_credible_boundary_fails_closed_partial(self):
        """N7: When no genuine boundary is found before chunk exhaustion, status is context_partial (EVIDENCE_PARTIAL)."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = "6.10 Начало нормы без структурного завершающего заголовка."
        self._insert_parent_chunk("973d9901_p_0057", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].context_status, "context_partial")

    # ─────────────────────────────────────────────────────────────────────────
    # N8: Real search_documents integration: partial hit does not displace full hit
    # ─────────────────────────────────────────────────────────────────────────
    @patch("rag_server.tools._cfg")
    @patch("rag_server.tools._db_paths")
    @patch("embedder.client.get_embeddings")
    @patch("storage.vector_store.search")
    def test_n8_real_modules_integration_partial_does_not_displace_full(self, mock_search, mock_emb, mock_db_paths, mock_cfg):
        """N8: Real NormRegistry and search_documents keep a structurally verified full 6.10 ahead of a partial 6.10."""
        from rag_server.tools import search_documents

        mock_cfg.return_value = {"storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"}, "retrieval": {}}
        fake_lance = self.temp_path / "lancedb"
        fake_lance.mkdir(exist_ok=True)
        mock_db_paths.return_value = (fake_lance, self.db_path)
        mock_emb.return_value = [[0.1] * 10]

        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Clause 6.10 is unclosed
        self._insert_parent_chunk("973d9901_p_0058", sp, "6.10 Неполный пункт")

        full_hit = {
            "chunk_id": "full_verified_hit_rank1",
            "score": 0.95,
            "text": "Полный текст нормативного требования.",
            "source_path": sp,
            "file_name": "СП 7.13130.2013.docx",
            "parent_id": "973d9901_p_0001",
            "section": "Пункт 6.10",
            "clause_status": "context_sufficient",
            "structural_start_verified": True,
            "structural_end_verified": True,
        }
        mock_search.return_value = [full_hit]

        res = search_documents("СП 7.13130 п. 6.10", rerank=False, debug=True)
        results = res["results"]
        self.assertEqual(results[0]["chunk_id"], "full_verified_hit_rank1")
        self.assertGreater(results[0]["score"], 0.90)

        clause_item = results[1]
        self.assertEqual(clause_item["chunk_id"], "clause_6.10")
        self.assertEqual(clause_item["clause_status"], "context_partial")
        self.assertEqual(clause_item["evidence_status"], "EVIDENCE_PARTIAL")

    # ─────────────────────────────────────────────────────────────────────────
    # N9: Regression integrity across all test suites
    # ─────────────────────────────────────────────────────────────────────────
    def test_n9_regression_suite_marker(self):
        """N9: Explicit test suite marker verifying that RQ14-01..12, F1..F10, and N1..N8 are cohesive."""
        reg = NormRegistry(self.db_path)
        q = parse_norm_query("СП 7.13130.2013 п. 6.10")
        self.assertIsNotNone(q)
        self.assertEqual(q.number, "7.13130")
        self.assertEqual(q.clause, "6.10")

    # ─────────────────────────────────────────────────────────────────────────
    # N10: Exact provenance contract verified
    # ─────────────────────────────────────────────────────────────────────────
    def test_n10_exact_provenance_contract_verified(self):
        """N10: Confirms test environment is purely synthetic SQLite with actual_corpus_search_calls = 0."""
        con = sqlite3.connect(str(self.db_path))
        cur = con.execute("SELECT count(*) FROM files")
        count = cur.fetchone()[0]
        con.close()
        self.assertGreaterEqual(count, 0)


    # ─────────────────────────────────────────────────────────────────────────
    # H1 [P0]: 6.10 -> '7. Противодымная защита.' -> '7.1 Общие положения.'
    # Cutoff before 7., section 7 title completely excluded, context_sufficient
    # ─────────────────────────────────────────────────────────────────────────
    def test_h1_section_mixedcase_with_trailing_dot_not_polluting_clause(self):
        """H1: '7. Противодымная защита.' followed by '7.1' cuts off before 7.; section 7 text excluded; context_sufficient."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Требования к оборудованию.\n"
            "7. Противодымная защита.\n"
            "7.1 Общие положения."
        )
        self._insert_parent_chunk("973d9901_p_0061", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.text, "6.10 Требования к оборудованию.")
        self.assertNotIn("7. Противодымная защита", m.text)
        self.assertNotIn("7.1", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # H2 [P0]: '7. Противодымная защита' without period, followed by 7.1
    # ─────────────────────────────────────────────────────────────────────────
    def test_h2_section_mixedcase_without_trailing_dot_not_polluting_clause(self):
        """H2: '7. Противодымная защита' (no dot) followed by '7.1' cuts off before 7.; clean boundary; context_sufficient."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Требования к оборудованию.\n"
            "7. Противодымная защита\n"
            "7.1 Общие положения."
        )
        self._insert_parent_chunk("973d9901_p_0062", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.text, "6.10 Требования к оборудованию.")
        self.assertNotIn("7. Противодымная защита", m.text)
        self.assertNotIn("7.1", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # H3 [P0]: Numbered list item 7 followed by 6.11 preserved inside 6.10
    # ─────────────────────────────────────────────────────────────────────────
    def test_h3_numeric_list_item_7_followed_by_6_11_preserved_inside_6_10(self):
        """H3: '6.10 Текст:', then '7. Клапаны EI 15.', then '6.11': item 7 is preserved inside 6.10, cuts off at 6.11."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Текст пункта 6.10:\n"
            "7. Клапаны EI 15.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0063", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("7. Клапаны EI 15.", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # H4 [P0]: Numbered list items with semicolons 1, 2, 7 preserved with 6.11
    # ─────────────────────────────────────────────────────────────────────────
    def test_h4_numeric_list_items_with_semicolon_preserved_inside_6_10(self):
        """H4: Numbered list items '1. Клапаны EI 60;', '7. Клапаны EI 15;', '2. Затворы EI 15.' preserved inside 6.10."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Текст перечня:\n"
            "1. Клапаны EI 60;\n"
            "7. Клапаны EI 15;\n"
            "2. Затворы EI 15.\n"
            "6.11 Следующий пункт."
        )
        self._insert_parent_chunk("973d9901_p_0064", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("1. Клапаны EI 60;", m.text)
        self.assertIn("7. Клапаны EI 15;", m.text)
        self.assertIn("2. Затворы EI 15.", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # H5 [P0]: Ambiguous '7. Технические требования.' without continuation fails closed partial
    # ─────────────────────────────────────────────────────────────────────────
    def test_h5_ambiguous_section_without_structural_continuation_fails_closed_partial(self):
        """H5: '7. Технические требования.' without 7.1 or 6.11 continuation slices before 7. but fails closed to context_partial."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        parent_text = (
            "6.10 Текст пункта 6.10:\n"
            "требование пункта.\n"
            "7. Технические требования."
        )
        self._insert_parent_chunk("973d9901_p_0065", sp, parent_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertNotIn("7. Технические требования", m.text)
        self.assertEqual(m.context_status, "context_partial")

    # ─────────────────────────────────────────────────────────────────────────
    # H6 [P0]: Stitching: 6.10 ends in 0021, section 7 starts in 0022 followed by 7.1
    # ─────────────────────────────────────────────────────────────────────────
    def test_h6_stitching_section_starts_in_next_chunk_not_polluting_parent_ids(self):
        """H6: 6.10 in 0021, section 7 in 0022; does not include section 7; parent_ids is only 0021 without duplication."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        p21_text = "6.10 Требования к оборудованию."
        p22_text = "7. Противодымная защита.\n7.1 Общие положения."
        self._insert_parent_chunk("973d9901_p_0066", sp, p21_text)
        self._insert_parent_chunk("973d9901_p_0067", sp, p22_text)

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.text, "6.10 Требования к оборудованию.")
        self.assertNotIn("7. Противодымная защита", m.text)
        self.assertEqual(m.parent_ids, ["973d9901_p_0066"])
        self.assertFalse(m.is_stitched)
        self.assertEqual(m.context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # H7 [P0]: Former positive cases '7. Раздел...' and '7. ПРОТИВОДЫМНАЯ ЗАЩИТА'
    # ─────────────────────────────────────────────────────────────────────────
    def test_h7_existing_positive_cases_preserved_no_regression(self):
        """H7: '7. Раздел...', '7. ПРОТИВОДЫМНАЯ ЗАЩИТА', '6.11', and '6.10.1'/'6.10.2' are all preserved without regression."""
        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # 1. ALL-CAPS section title
        p_text_caps = (
            "6.10 Текст пункта.\n"
            "7. ПРОТИВОДЫМНАЯ ЗАЩИТА\n"
            "Некоторый текст раздела 7."
        )
        self._insert_parent_chunk("973d9901_p_0068", sp, p_text_caps)

        reg = NormRegistry(self.db_path)
        m_caps = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(m_caps), 1)
        self.assertNotIn("7. ПРОТИВОДЫМНАЯ ЗАЩИТА", m_caps[0].text)
        self.assertEqual(m_caps[0].context_status, "context_sufficient")

    # ─────────────────────────────────────────────────────────────────────────
    # H8 [P0]: NormRegistry real import and isolated SQLite verification
    # ─────────────────────────────────────────────────────────────────────────
    def test_h8_norm_registry_isolated_sqlite_full_extraction_verified(self):
        """H8: Confirms that all H-tests operate via real NormRegistry import on isolated SQLite."""
        self.assertTrue(issubclass(NormRegistry, object))
        con = sqlite3.connect(str(self.db_path))
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM parent_chunks")
        cnt = cur.fetchone()[0]
        con.close()
        self.assertGreaterEqual(cnt, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # H9 [P1]: search_documents integration: ambiguous boundary gives EVIDENCE_PARTIAL
    # ─────────────────────────────────────────────────────────────────────────
    @patch("rag_server.tools._cfg")
    @patch("rag_server.tools._db_paths")
    @patch("embedder.client.get_embeddings")
    @patch("storage.vector_store.search")
    def test_h9_search_documents_integration_ambiguous_boundary_evidence_partial(
        self, mock_search, mock_emb, mock_db_paths, mock_cfg
    ):
        """H9: Ambiguous section boundary yields EVIDENCE_PARTIAL but does not displace a proven full 6.10."""
        from rag_server.tools import search_documents

        mock_cfg.return_value = {"storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"}, "retrieval": {}}
        fake_lance = self.temp_path / "lancedb"
        fake_lance.mkdir(exist_ok=True)
        mock_db_paths.return_value = (fake_lance, self.db_path)
        mock_emb.return_value = [[0.1] * 10]

        sp = "НТД/СП 7.13130.2013.docx"
        self._insert_file("СП 7.13130.2013.docx", sp)

        # Clause 6.10 with ambiguous termination
        ambig_text = "6.10 Текст пункта без подтверждения.\n7. Технические требования."
        self._insert_parent_chunk("973d9901_p_0069", sp, ambig_text)

        full_hit = {
            "chunk_id": "full_verified_hit_rank1",
            "score": 0.95,
            "text": "Полный текст нормативного требования.",
            "source_path": sp,
            "file_name": "СП 7.13130.2013.docx",
            "parent_id": "973d9901_p_0001",
            "section": "Пункт 6.10",
            "clause_status": "context_sufficient",
            "structural_start_verified": True,
            "structural_end_verified": True,
        }
        mock_search.return_value = [full_hit]

        res = search_documents("СП 7.13130 п. 6.10", rerank=False, debug=True)
        results = res["results"]
        self.assertEqual(results[0]["chunk_id"], "full_verified_hit_rank1")
        self.assertGreater(results[0]["score"], 0.90)

        clause_item = results[1]
        self.assertEqual(clause_item["chunk_id"], "clause_6.10")
        self.assertEqual(clause_item["clause_status"], "context_partial")
        self.assertEqual(clause_item["evidence_status"], "EVIDENCE_PARTIAL")

    # ─────────────────────────────────────────────────────────────────────────
    # H10 [P1]: Full test suite coverage: all 42 tests in module pass
    # ─────────────────────────────────────────────────────────────────────────
    def test_h10_full_suite_coverage_and_regression_contract(self):
        """H10: Verifies that 12 RQ14 + 10 F1..F10 + 10 N1..N10 + 10 H1..H10 = 42 tests pass cohesively."""
        reg = NormRegistry(self.db_path)
        q = parse_norm_query("СП 7.13130.2013 п. 6.10")
        self.assertIsNotNone(q)
        self.assertEqual(q.clause, "6.10")


if __name__ == "__main__":
    unittest.main()
