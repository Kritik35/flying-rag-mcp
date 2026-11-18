"""
tests/test_postfix_pilot_real_payload_015_rev1_3.py

Contract verification suite for Stage 4.2.9 / ТЗ-015 Rev 1.3 (E15-01 .. E15-08).
Enforces:
- P0-E1: Real native MCP payload compatibility (file_name, source_path, section, derived_label,
  parent_ids, chunk_id) alongside legacy fields (norm, doc_name, clause_num, edition).
- P0-E2: Strict completeness and source fidelity (no false PASS on missing EI 15 or without source reference).
- P1-E3: Telemetry invariants and clean separation of mechanical success from normative quality.
"""

from __future__ import annotations
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.postfix_pilot_harness_015 import (
    evaluate_normative_evidence,
    run_postfix_pilot,
    compare_ranks,
    extract_canonical_id,
    TARGET_QUERIES
)


class TestPostfixPilotRealPayload015Rev13(unittest.TestCase):
    def setUp(self):
        self.q004 = {
            "id": "Q004",
            "query": "СП 7.13130 пункт 6.4",
            "target_norm": "СП 7.13130",
            "clause": "6.4",
            "topic": "приёмные устройства наружного воздуха"
        }
        self.q010 = {
            "id": "Q010",
            "query": "СП 7.13130 пункт 6.10",
            "target_norm": "СП 7.13130",
            "clause": "6.10",
            "topic": "оборудование систем вентиляции и клапаны EI"
        }
        self.q088 = {
            "id": "Q088-2020",
            "query": "СП 60.13330.2020 пункт 7.1.1",
            "target_norm": "СП 60.13330",
            "edition": "2020",
            "clause": "7.1.1",
            "topic": "параметры воздуха и вентиляции (редакция 2020 года)"
        }

    def test_e15_01_native_derived_hit_q004_compatibility(self):
        """
        E15-01 [P0]: Native derived hit Q004 without 'norm' field:
        file_name='СП 7.13130.docx', source_path='НТД/...', section='Пункт 6.4',
        derived_label='clause_6.4', chunk_id='clause_6.4', parent_ids=['973d9901_p_0017'],
        clause_status='context_sufficient', evidence_status='USABLE_FOR_ANSWER'.
        - TARGET_DOC_MATCH = PASS (doc_provenance='FILENAME_INFERRED')
        - TARGET_CLAUSE_MATCH = PASS (clause_provenance='SECTION_METADATA')
        - HAS_PAGE_OR_VALID_LOCATOR = PASS (physical parent binding)
        - SOURCE_FIDELITY = UNKNOWN (without independent source verification)
        - QUALITY_VERIFIED = False
        """
        hit = {
            "file_name": "СП 7.13130.docx",
            "source_path": "НТД/СП 7.13130.docx",
            "section": "Пункт 6.4",
            "derived_label": "clause_6.4",
            "chunk_id": "clause_6.4",
            "parent_ids": ["973d9901_p_0017"],
            "clause_status": "context_sufficient",
            "evidence_status": "USABLE_FOR_ANSWER",
            "text": "6.4 Приёмные устройства наружного воздуха следует размещать..."
        }
        eval_res = evaluate_normative_evidence(self.q004, hit)
        self.assertEqual(eval_res["TARGET_DOC_MATCH"], "PASS")
        self.assertEqual(eval_res["doc_provenance"], "FILENAME_INFERRED")
        self.assertEqual(eval_res["TARGET_CLAUSE_MATCH"], "PASS")
        self.assertEqual(eval_res["HAS_PAGE_OR_VALID_LOCATOR"], "PASS")
        self.assertEqual(eval_res["PARSER_BOUNDARY_STATUS"], "PASS")
        self.assertEqual(eval_res["FULL_CLAUSE_EVIDENCE"], "PASS")
        self.assertEqual(eval_res["SOURCE_FIDELITY"], "UNKNOWN")
        self.assertFalse(eval_res["QUALITY_VERIFIED"])

    def test_e15_02_native_q010_missing_ei15_fails_full_clause(self):
        """
        E15-02 [P0]: Native derived hit Q010 with evidence_status='EVIDENCE_PARTIAL':
        valid file_name/section/parent_ids, text='6.10 ... EI 60.' without EI 15 and WITHOUT '...'.
        - FULL_CLAUSE_EVIDENCE = FAIL
        - QUALITY_VERIFIED = False
        """
        hit = {
            "file_name": "СП 7.13130.docx",
            "source_path": "НТД/СП 7.13130.docx",
            "section": "Пункт 6.10",
            "derived_label": "clause_6.10",
            "chunk_id": "clause_6.10",
            "parent_ids": ["973d9901_p_0021"],
            "evidence_status": "EVIDENCE_PARTIAL",
            "clause_status": "context_partial",
            "text": "6.10 Клапаны противопожарные должны иметь предел огнестойкости не менее EI 60."
        }
        eval_res = evaluate_normative_evidence(self.q010, hit)
        self.assertEqual(eval_res["PARSER_BOUNDARY_STATUS"], "FAIL_PARTIAL")
        self.assertEqual(eval_res["FULL_CLAUSE_EVIDENCE"], "FAIL")
        self.assertFalse(eval_res["QUALITY_VERIFIED"])

    def test_e15_03_q010_stitched_boundary_without_independent_source_not_certified(self):
        """
        E15-03 [P0]: Q010 with stitched parent_ids 0021+0022 and both EI 60 and EI 15:
        clause_status='context_sufficient', section 7 outside returned text.
        - PARSER_BOUNDARY_STATUS = PASS
        - FULL_CLAUSE_EVIDENCE = PASS
        - SOURCE_FIDELITY = UNKNOWN (without independent source comparison)
        - QUALITY_VERIFIED = False
        """
        hit = {
            "file_name": "СП 7.13130.docx",
            "source_path": "НТД/СП 7.13130.docx",
            "section": "Пункт 6.10",
            "derived_label": "clause_6.10",
            "chunk_id": "clause_6.10",
            "parent_ids": ["973d9901_p_0021", "973d9901_p_0022"],
            "clause_status": "context_sufficient",
            "evidence_status": "USABLE_FOR_ANSWER",
            "text": "6.10 Требования к оборудованию: 1. Клапаны EI 60; 2. Затворы EI 15."
        }
        eval_res = evaluate_normative_evidence(self.q010, hit)
        self.assertEqual(eval_res["PARSER_BOUNDARY_STATUS"], "PASS")
        self.assertEqual(eval_res["FULL_CLAUSE_EVIDENCE"], "PASS")
        self.assertEqual(eval_res["SOURCE_FIDELITY"], "UNKNOWN")
        self.assertFalse(eval_res["QUALITY_VERIFIED"])

    def test_e15_04_native_q088_2020_filename_inferred_vs_body_text_only(self):
        """
        E15-04 [P0]: Native Q088-2020:
        - file_name='СП 60.13330.2020.docx' -> TARGET_EDITION_MATCH = PASS (FILENAME_INFERRED)
        - file_name='СП 60.13330.2012.docx' -> TARGET_EDITION_MATCH = FAIL (WRONG_EDITION)
        - file_name='СП 60.13330.docx' with '2020' only in text body -> TARGET_EDITION_MATCH = UNKNOWN (NOT PASS)
        """
        # 1. Valid 2020 in filename
        hit_2020 = {
            "file_name": "СП 60.13330.2020 Отопление и вентиляция.docx",
            "source_path": "НТД/СП 60.13330.2020 Отопление и вентиляция.docx",
            "section": "Пункт 7.1.1",
            "parent_ids": ["p_001"],
            "clause_status": "context_sufficient",
            "text": "7.1.1 Параметры микроклимата..."
        }
        res_2020 = evaluate_normative_evidence(self.q088, hit_2020)
        self.assertEqual(res_2020["TARGET_EDITION_MATCH"], "PASS")
        self.assertEqual(res_2020["edition_provenance"], "FILENAME_INFERRED")

        # 2. Wrong 2012 in filename
        hit_2012 = {
            "file_name": "СП 60.13330.2012 Отопление и вентиляция.docx",
            "source_path": "НТД/СП 60.13330.2012 Отопление и вентиляция.docx",
            "section": "Пункт 7.1.1",
            "parent_ids": ["p_001"],
            "clause_status": "context_sufficient",
            "text": "7.1.1 Параметры микроклимата..."
        }
        res_2012 = evaluate_normative_evidence(self.q088, hit_2012)
        self.assertEqual(res_2012["TARGET_EDITION_MATCH"], "FAIL")

        # 3. Year 2020 only in text body (no edition in filename)
        hit_body_only = {
            "file_name": "СП 60.13330.docx",
            "source_path": "НТД/СП 60.13330.docx",
            "section": "Пункт 7.1.1",
            "parent_ids": ["p_001"],
            "clause_status": "context_sufficient",
            "text": "7.1.1 Требования по состоянию на 2020 год к системам вентиляции..."
        }
        res_body_only = evaluate_normative_evidence(self.q088, hit_body_only)
        self.assertNotEqual(res_body_only["TARGET_EDITION_MATCH"], "PASS")
        self.assertEqual(res_body_only["TARGET_EDITION_MATCH"], "UNKNOWN")
        self.assertEqual(res_body_only["edition_provenance"], "TEXT_ONLY_UNVERIFIED")

    def test_e15_05_clause_6_100_and_incidental_citations_rejected(self):
        """
        E15-05 [P0]: Clause '6.100' and citation '(см. п. 6.10)' in foreign context:
        - section='Пункт 6.100' -> TARGET_CLAUSE_MATCH = FAIL (exact number check)
        - citation '(см. п. 6.10)' in text without section 6.10 -> TARGET_CLAUSE_MATCH != PASS
        """
        # Case 1: 6.100 is not 6.10
        hit_6_100 = {
            "file_name": "СП 7.13130.docx",
            "section": "Пункт 6.100",
            "parent_ids": ["p_100"],
            "text": "6.100 Требования пункта 6.100..."
        }
        res_6_100 = evaluate_normative_evidence(self.q010, hit_6_100)
        self.assertEqual(res_6_100["TARGET_CLAUSE_MATCH"], "FAIL")

        # Case 2: Incidental citation in unrelated text
        hit_citation = {
            "file_name": "СП 7.13130.docx",
            "parent_ids": ["p_050"],
            "text": "В помещениях категории В следует соблюдать меры безопасности (см. п. 6.10)."
        }
        res_citation = evaluate_normative_evidence(self.q010, hit_citation)
        self.assertNotEqual(res_citation["TARGET_CLAUSE_MATCH"], "PASS")

    def test_e15_06_native_vector_hit_without_section_has_locator_but_clause_unknown(self):
        """
        E15-06 [P0]: Native vector hit with chunk_id and parent_id, without section/derived_label/year:
        - HAS_PAGE_OR_VALID_LOCATOR = PASS (physical binding verified)
        - TARGET_CLAUSE_MATCH = UNKNOWN
        - QUALITY_VERIFIED = False
        """
        hit = {
            "chunk_id": "chunk_vec_001",
            "parent_id": "parent_vec_001",
            "source_path": "НТД/СП 7.13130.docx",
            "text": "Общие требования пожарной безопасности при проектировании..."
        }
        res = evaluate_normative_evidence(self.q004, hit)
        self.assertEqual(res["HAS_PAGE_OR_VALID_LOCATOR"], "PASS")
        self.assertEqual(res["TARGET_CLAUSE_MATCH"], "UNKNOWN")
        self.assertFalse(res["QUALITY_VERIFIED"])

    def test_e15_07_legacy_synthetic_fixture_compatibility(self):
        """
        E15-07 [P1]: Legacy synthetic fixture with 'norm', 'clause_num', 'edition' continues
        to be recognized properly without regression.
        """
        hit_legacy = {
            "chunk_id": "chunk_Q004_001",
            "norm": "СП 7.13130",
            "clause_num": "6.4",
            "text": "6.4 Текст нормативного требования по теме: приёмные устройства наружного воздуха.",
            "parent_ids": ["parent_Q004_0010"],
            "context_sufficient": True,
            "score": 0.95
        }
        res = evaluate_normative_evidence(self.q004, hit_legacy)
        self.assertEqual(res["TARGET_DOC_MATCH"], "PASS")
        self.assertEqual(res["doc_provenance"], "SOURCE_METADATA")
        self.assertEqual(res["TARGET_CLAUSE_MATCH"], "PASS")
        self.assertEqual(res["FULL_CLAUSE_EVIDENCE"], "PASS")
        self.assertEqual(res["PARSER_BOUNDARY_STATUS"], "PASS")

    def test_e15_08_mechanical_pair_ok_independent_from_quality_verified(self):
        """
        E15-08 [P1]: Mechanical pair OFF/ON with identical normalized output, but insufficient
        normative evidence (SOURCE_FIDELITY=UNKNOWN):
        - MECHANICAL_PAIR_OK = True
        - SOURCE_FIDELITY = UNKNOWN
        - QUALITY_VERIFIED = False
        - PILOT_QUALITY = UNVERIFIED
        - Pilot completes normally without automatic error halt.
        """
        pilot = run_postfix_pilot(synthetic_test=True)
        self.assertEqual(pilot["overall_status"], "SYNTHETIC_MACHINERY_VERIFIED")
        self.assertEqual(pilot["PILOT_QUALITY"], "UNVERIFIED")
        self.assertEqual(len(pilot["comparisons"]), 3)
        for comp in pilot["comparisons"]:
            self.assertTrue(comp["MECHANICAL_PAIR_OK"])
            self.assertEqual(comp["pair_verdict"], "PASS")
            self.assertEqual(comp["evidence_evaluation"]["SOURCE_FIDELITY"], "UNKNOWN")
            self.assertFalse(comp["evidence_evaluation"]["QUALITY_VERIFIED"])


if __name__ == "__main__":
    unittest.main()
