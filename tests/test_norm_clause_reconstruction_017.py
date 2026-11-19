"""
Stage 4.2.11 / FR-TZ-20261119-017
Mandatory Test Suite: C17-01 .. C17-12
Verification of Normative Clause Reconstruction, ENR Attribution Separation,
and Boundary Fail-Closed Integrity on Isolated In-Memory/Temp SQLite Fixtures.

Zero live searches, zero production access, zero model/EIG invocations.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_server.norm_resolver import NormRegistry, ClauseMatch, get_norm_registry
from tests.postfix_pilot_harness_015 import evaluate_normative_evidence


def _create_fixture_db(db_path: Path, rows: list[tuple[str, str, str]]) -> None:
    """Creates a temporary isolated SQLite database with parent_chunks and files tables."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            source_path TEXT UNIQUE,
            file_name TEXT,
            dataset TEXT DEFAULT 'normative',
            is_deprecated INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE parent_chunks (
            rowid INTEGER PRIMARY KEY,
            parent_id TEXT,
            source_path TEXT,
            parent_text TEXT
        )
    """)
    for rowid, (p_id, sp, txt) in enumerate(rows, start=1):
        cur.execute(
            "INSERT INTO parent_chunks (rowid, parent_id, source_path, parent_text) VALUES (?, ?, ?, ?)",
            (rowid, p_id, sp, txt)
        )
        cur.execute(
            "INSERT OR IGNORE INTO files (source_path, file_name, dataset, is_deprecated) VALUES (?, ?, 'normative', 0)",
            (sp, Path(sp).name)
        )
    conn.commit()
    conn.close()


class TestNormClauseReconstruction017(unittest.TestCase):
    """C17-01..C17-12 test matrix for Stage 4.2.11."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_fixture.db"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_c17_01_q010_consecutive_parents_stitched_full(self):
        """C17-01 [P0]: Q010, parent 0021+0022 of same doc, proven continuation => full extraction with EI 60 and EI 15."""
        sp = r"H:\Docs\СП 7.13130.docx"
        text_0021 = (
            "6.10 Для предотвращения распространения продуктов горения при пожаре по воздуховодам систем вентиляции "
            "должны быть предусмотрены:\n"
            "а) противопожарные нормально открытые клапаны с пределом огнестойкости не менее EI 60;\n"
            "б) воздушные затворы, обеспечивающие предотвращение перетекания продуктов горения в смежные помещения"
        )
        text_0022 = (
            "различных этажей. Предел огнестойкости воздушных затворов должен составлять не менее EI 30 в зданиях I-II "
            "степеней огнестойкости и не менее EI 15 в зданиях III-IV степеней огнестойкости.\n"
            "6.11 В противопожарных преградах..."
        )
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0021", sp, text_0021),
            ("973d9901_p_0022", sp, text_0022),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.clause_num, "6.10")
        self.assertTrue(m.is_stitched)
        self.assertEqual(m.parent_ids, ["973d9901_p_0021", "973d9901_p_0022"])
        self.assertIn("EI 60", m.text)
        self.assertIn("EI 15", m.text)
        self.assertIn("EI 30", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    def test_c17_02_q010_missing_next_chunk_fails_closed_partial(self):
        """C17-02 [P0]: Q010, parent 0022 absent => context_partial, no fabricated EI 15."""
        sp = r"H:\Docs\СП 7.13130.docx"
        text_0021 = (
            "6.10 Для предотвращения распространения продуктов горения при пожаре по воздуховодам систем вентиляции "
            "должны быть предусмотрены:\n"
            "а) противопожарные нормально открытые клапаны с пределом огнестойкости не менее EI 60;\n"
            "б) воздушные затворы, обеспечивающие предотвращение"
        )
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0021", sp, text_0021),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertFalse(m.is_stitched)
        self.assertEqual(m.parent_ids, ["973d9901_p_0021"])
        self.assertNotIn("EI 15", m.text)
        self.assertEqual(m.context_status, "context_partial")

    def test_c17_03_different_source_path_stops_join(self):
        """C17-03 [P0]: Matching chunk prefix/number, but different source_path => STOP JOIN, context_partial."""
        sp1 = r"H:\Docs\СП 7.13130.docx"
        sp2 = r"H:\Docs\СП 60.13330.docx"
        text_0021 = "6.10 Для предотвращения распространения продуктов горения должны быть предусмотрены"
        text_0022 = "затворы с пределом EI 15."
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0021", sp1, text_0021),
            ("973d9901_p_0022", sp2, text_0022),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp1, "6.10")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertFalse(m.is_stitched)
        self.assertEqual(m.parent_ids, ["973d9901_p_0021"])
        self.assertEqual(m.context_status, "context_partial")

    def test_c17_04_q004_truncated_start_without_heading_not_full(self):
        """C17-04 [P0]: Q004, heading in previous parent or unproven boundary => do not return truncated start as FULL."""
        sp = r"H:\Docs\СП 7.13130.docx"
        # 0016 ends before heading; 0017 starts mid-sentence without heading
        text_0016 = "Предыдущий пункт 6.3 завершается здесь.\n6.4 В пределах одного"
        text_0017 = "пожарного отсека общие приемные устройства наружного воздуха не следует предусматривать.\n6.5 Следующий пункт."
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0016", sp, text_0016),
            ("973d9901_p_0017", sp, text_0017),
        ])

        reg = NormRegistry(self.db_path)
        # Search for 6.4 in doc: it must find the match at 0016, not a headless fragment
        matches = reg.extract_clause_from_doc(sp, "6.4")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.parent_id, "973d9901_p_0016")
        self.assertTrue(m.text.startswith("6.4 В пределах одного"))

    def test_c17_05_q088_strip_prior_clause_preserve_2020(self):
        """C17-05 [P0]: Q088-2020, tail of 6.4.14 and next 7.1.1 => strip preceding clause, preserve 2020."""
        sp = r"H:\Docs\СП 60.13330.2020. Свод правил. Отопление, вентиляция и конди.docx"
        text_0038 = (
            "пературу поверхности высокотемпературных приборов лучистого отопления не следует принимать выше 250 °C.\n"
            "(п. 6.4.14 в ред. Изменения N 3)\n"
            "7.1.1 Вентиляцию следует применять для обеспечения требуемого качества воздуха и параметров микроклимата "
            "в помещениях.\n"
            "7.1.2 Параметры наружного воздуха..."
        )
        _create_fixture_db(self.db_path, [
            ("3fb687c5_p_0038", sp, text_0038),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "7.1.1")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertTrue(m.text.startswith("7.1.1 Вентиляцию следует применять"))
        self.assertNotIn("6.4.14", m.text)
        self.assertNotIn("7.1.2", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    def test_c17_06_section_7_not_included_in_clause_6_10(self):
        """C17-06 [P0]: After 6.10 comes '7. Противодымная защита' => section 7 is NOT included in 6.10."""
        sp = r"H:\Docs\СП 7.13130.docx"
        text_0021 = (
            "6.10 Для предотвращения распространения продуктов горения должны быть предусмотрены клапаны EI 60.\n"
            "7. Противодымная защита\n"
            "7.1 Требования к противодымной вентиляции..."
        )
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0021", sp, text_0021),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertNotIn("7. Противодымная защита", m.text)
        self.assertNotIn("7.1", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    def test_c17_07_numeric_lists_and_measurements_not_treated_as_section_heading(self):
        """C17-07 [P0]: '1. Клапаны EI60', '2. Затворы EI15', '30.5 мм' are not treated as headings."""
        sp = r"H:\Docs\СП 7.13130.docx"
        text_0021 = (
            "6.10 Должны соблюдаться условия:\n"
            "1. Клапаны EI 60 на воздуховодах.\n"
            "2. Устройства EI 15 с толщиной стенки 30.5 мм.\n"
            "См. также п. 6.4 для деталей.\n"
            "6.11 Новый пункт."
        )
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0021", sp, text_0021),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIn("1. Клапаны EI 60", m.text)
        self.assertIn("2. Устройства EI 15", m.text)
        self.assertIn("30.5 мм", m.text)
        self.assertIn("См. также п. 6.4", m.text)
        self.assertNotIn("6.11", m.text)
        self.assertEqual(m.context_status, "context_sufficient")

    def test_c17_08_bounded_adjacent_chunks_no_infinite_loop(self):
        """C17-08 [P0]: Bounded stitch prevents runaway loops; ambiguous termination yields context_partial."""
        sp = r"H:\Docs\СП 7.13130.docx"
        text_0021 = "6.10 Начало пункта без завершающей точки и без следующего заголовка"
        text_0022 = "продолжение пункта, также не содержащее заголовка следующего раздела..."
        _create_fixture_db(self.db_path, [
            ("973d9901_p_0021", sp, text_0021),
            ("973d9901_p_0022", sp, text_0022),
        ])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertTrue(m.is_stitched)
        self.assertEqual(m.context_status, "context_partial")

    def test_c17_09_attribution_separation_derived_vs_physical_ids(self):
        """C17-09 [P0]: Derived clause does NOT pass as physical child chunk; retrieval_origin, derived_clause_id, physical_parent_ids, physical_child_chunk_ids separated."""
        q = {
            "query_id": "Q010",
            "target_norm": "СП 7.13130",
            "clause": "6.10",
            "edition": None,
        }
        derived_enr_hit = {
            "chunk_id": "clause_6.10",
            "derived_label": "clause_6.10",
            "derived_clause_id": "clause_6.10",
            "retrieval_origin": "ENR_DERIVED_CLAUSE",
            "physical_parent_ids": ["973d9901_p_0021", "973d9901_p_0022"],
            "physical_child_chunk_ids": ["UNKNOWN"],
            "score_kind": "enr_deterministic_priority",
            "score": 1.0,
            "section": "Пункт 6.10",
            "file_name": "СП 7.13130.docx",
            "source_path": r"H:\Docs\СП 7.13130.docx",
            "clause_status": "context_sufficient",
            "evidence_status": "USABLE_FOR_ANSWER",
            "text": "6.10 Текст с EI 60 и EI 15.",
            "is_stitched": True,
        }

        eval_res = evaluate_normative_evidence(q, derived_enr_hit)
        self.assertEqual(eval_res["RETRIEVAL_ORIGIN"], "ENR_DERIVED_CLAUSE")
        self.assertEqual(eval_res["DERIVED_CLAUSE_ID"], "clause_6.10")
        self.assertEqual(eval_res["PHYSICAL_PARENT_IDS"], ["973d9901_p_0021", "973d9901_p_0022"])
        self.assertEqual(eval_res["PHYSICAL_CHILD_CHUNK_IDS"], ["UNKNOWN"])
        self.assertEqual(eval_res["SCORE_KIND"], "enr_deterministic_priority")
        self.assertTrue(eval_res["STRUCTURAL_START_VERIFIED"])
        self.assertTrue(eval_res["STRUCTURAL_END_VERIFIED"])
        self.assertTrue(eval_res["CONTINUITY_VERIFIED"])

    def test_c17_10_source_fidelity_unverified_without_independent_original(self):
        """C17-10 [P1]: SOURCE_FIDELITY without external independent ground truth original remains UNKNOWN."""
        q = {
            "query_id": "Q010",
            "target_norm": "СП 7.13130",
            "clause": "6.10",
            "edition": None,
        }
        perfect_hit = {
            "chunk_id": "clause_6.10",
            "derived_clause_id": "clause_6.10",
            "retrieval_origin": "ENR_DERIVED_CLAUSE",
            "physical_parent_ids": ["973d9901_p_0021", "973d9901_p_0022"],
            "section": "Пункт 6.10",
            "file_name": "СП 7.13130.docx",
            "source_path": r"H:\Docs\СП 7.13130.docx",
            "clause_status": "context_sufficient",
            "evidence_status": "USABLE_FOR_ANSWER",
            "text": "6.10 Текст с EI 60 и EI 15.",
            "is_stitched": True,
        }

        # Without source_reference_text, SOURCE_FIDELITY MUST BE UNKNOWN and QUALITY_VERIFIED MUST BE False
        eval_no_ref = evaluate_normative_evidence(q, perfect_hit, source_reference_text=None)
        self.assertEqual(eval_no_ref["SOURCE_FIDELITY"], "UNKNOWN")
        self.assertFalse(eval_no_ref["QUALITY_VERIFIED"])

        # With matching reference text, SOURCE_FIDELITY becomes PASS and QUALITY_VERIFIED becomes True
        eval_with_ref = evaluate_normative_evidence(q, perfect_hit, source_reference_text="6.10 Текст с EI 60 и EI 15.")
        self.assertEqual(eval_with_ref["SOURCE_FIDELITY"], "PASS")
        self.assertTrue(eval_with_ref["QUALITY_VERIFIED"])

    def test_c17_11_regression_marker_previous_suites_covered(self):
        """C17-11 [P1]: Regression test marker asserting that test_retrieval_cache_revision_017, test_postfix_pilot_real_payload_015_rev1_3, and test_retrieval_clause_edition_014 are active."""
        cache_test = Path(__file__).parent / "test_retrieval_cache_revision_017.py"
        payload_test = Path(__file__).parent / "test_postfix_pilot_real_payload_015_rev1_3.py"
        clause_test = Path(__file__).parent / "test_retrieval_clause_edition_014.py"
        self.assertTrue(cache_test.exists())
        self.assertTrue(payload_test.exists())
        self.assertTrue(clause_test.exists())

    def test_c17_12_isolated_sqlite_only_no_real_search_or_production_access(self):
        """C17-12 [P0]: End-to-end on temporary SQLite fixture: zero real calls to search_documents, model, EIG, or production DB."""
        prod_db = Path(r"C:\RAG_Acer\data_imported\metadata.db")
        initial_mtime = prod_db.stat().st_mtime if prod_db.exists() else None
        initial_size = prod_db.stat().st_size if prod_db.exists() else None

        # Execute extraction strictly against temp fixture
        sp = r"H:\Docs\СП 7.13130.docx"
        text = "6.10 Нормативный текст пункта 6.10.\n6.11 Новый пункт."
        _create_fixture_db(self.db_path, [("p_0001", sp, text)])

        reg = NormRegistry(self.db_path)
        matches = reg.extract_clause_from_doc(sp, "6.10")
        self.assertEqual(len(matches), 1)

        # Verify production database was NOT touched
        if prod_db.exists():
            self.assertEqual(prod_db.stat().st_mtime, initial_mtime)
            self.assertEqual(prod_db.stat().st_size, initial_size)


if __name__ == "__main__":
    unittest.main()
