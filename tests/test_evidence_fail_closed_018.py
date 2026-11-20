"""Offline evidence-gate regressions for the real uncached Q010 top-hit defect.

No real corpus, model, live search, production storage or raw document text.
"""
from __future__ import annotations

import unittest

from tests.postfix_pilot_harness_015 import evaluate_normative_evidence


class EvidenceFailClosed018Tests(unittest.TestCase):
    def setUp(self):
        self.q = {
            "id": "Q010",
            "target_norm": "СП 7.13130",
            "clause": "6.10",
        }

    def test_q010_document_cover_is_not_full_clause_evidence(self):
        cover = {
            "chunk_id": "973d9901_c_0007",
            "parent_id": "973d9901_p_0000",
            "file_name": "СП 7.13130.docx",
            "source_path": "НТД/СП 7.13130.docx",
            "text": "МИНИСТЕРСТВО ... ПРИКАЗ ОБ УТВЕРЖДЕНИИ СВОДА ПРАВИЛ",
            "score": 1.0,
        }
        out = evaluate_normative_evidence(self.q, cover)
        self.assertEqual(out["TARGET_DOC_MATCH"], "PASS")
        self.assertEqual(out["HAS_PAGE_OR_VALID_LOCATOR"], "PASS")
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "UNKNOWN")
        self.assertEqual(out["PARSER_BOUNDARY_STATUS"], "UNKNOWN")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "UNKNOWN")
        self.assertEqual(out["SOURCE_FIDELITY"], "UNKNOWN")
        self.assertFalse(out["QUALITY_VERIFIED"])
        self.assertFalse(out["STRUCTURAL_START_VERIFIED"])
        self.assertFalse(out["STRUCTURAL_END_VERIFIED"])
        self.assertFalse(out["CONTINUITY_VERIFIED"])
        self.assertEqual(out["PHYSICAL_CHILD_CHUNK_IDS"], ["973d9901_c_0007"])

    def test_incidental_clause_reference_not_a_verified_boundary(self):
        incidental = {
            "chunk_id": "c1",
            "parent_id": "p1",
            "file_name": "СП 7.13130.docx",
            "text": "Требования необходимо смотреть по п. 6.10 в другом месте.",
        }
        out = evaluate_normative_evidence(self.q, incidental)
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "UNKNOWN")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "UNKNOWN")
        self.assertEqual(out["PARSER_BOUNDARY_STATUS"], "UNKNOWN")

    def test_correct_heading_without_end_is_still_unknown(self):
        no_end = {
            "chunk_id": "c1",
            "parent_id": "p1",
            "file_name": "СП 7.13130.docx",
            "text": "6.10 Клапаны EI 60, затворы EI 15, но конец не доказан",
        }
        out = evaluate_normative_evidence(self.q, no_end)
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "PASS")
        self.assertEqual(out["PARSER_BOUNDARY_STATUS"], "UNKNOWN")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "UNKNOWN")

    def test_wrong_clause_number_never_passes_full_evidence(self):
        wrong = {
            "chunk_id": "c100",
            "parent_id": "p100",
            "section": "Пункт 6.100",
            "file_name": "СП 7.13130.docx",
            "text": "6.100 Требования к системе.",
        }
        out = evaluate_normative_evidence(self.q, wrong)
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "FAIL")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "FAIL")
        self.assertFalse(out["QUALITY_VERIFIED"])

    def test_stitched_partial_with_both_ei_numbers_is_still_not_complete(self):
        partial = {
            "chunk_id": "clause_6.10",
            "derived_label": "clause_6.10",
            "section": "Пункт 6.10",
            "file_name": "СП 7.13130.docx",
            "parent_ids": ["p_0021", "p_0022"],
            "clause_status": "context_partial",
            "evidence_status": "EVIDENCE_PARTIAL",
            "is_stitched": True,
            "text": "6.10 Клапаны EI 60, затворы EI 30 и EI 15.",
        }
        out = evaluate_normative_evidence(self.q, partial)
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "PASS")
        self.assertEqual(out["PARSER_BOUNDARY_STATUS"], "FAIL_PARTIAL")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "FAIL")

    def test_explicit_negative_boundary_overrides_sufficient_label(self):
        contradictory = {
            "chunk_id": "clause_6.10",
            "derived_label": "clause_6.10",
            "section": "Пункт 6.10",
            "file_name": "СП 7.13130.docx",
            "parent_ids": ["p1", "p2"],
            "clause_status": "context_sufficient",
            "structural_start_verified": False,
            "structural_end_verified": False,
            "text": "6.10 Клапаны EI 60 и затворы EI 15.",
        }
        out = evaluate_normative_evidence(self.q, contradictory)
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "PASS")
        self.assertEqual(out["PARSER_BOUNDARY_STATUS"], "UNKNOWN")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "UNKNOWN")
        self.assertFalse(out["QUALITY_VERIFIED"])

    def test_trusted_sufficient_derived_clause_remains_eligible(self):
        full = {
            "chunk_id": "clause_6.10",
            "derived_label": "clause_6.10",
            "section": "Пункт 6.10",
            "file_name": "СП 7.13130.docx",
            "parent_ids": ["p_0021", "p_0022"],
            "clause_status": "context_sufficient",
            "evidence_status": "USABLE_FOR_ANSWER",
            "structural_start_verified": True,
            "structural_end_verified": True,
            "continuity_verified": True,
            "text": "6.10 Клапаны EI 60; затворы EI 30 и EI 15.",
        }
        out = evaluate_normative_evidence(self.q, full)
        self.assertEqual(out["TARGET_CLAUSE_MATCH"], "PASS")
        self.assertEqual(out["PARSER_BOUNDARY_STATUS"], "PASS")
        self.assertEqual(out["FULL_CLAUSE_EVIDENCE"], "PASS")
        self.assertEqual(out["SOURCE_FIDELITY"], "UNKNOWN")
        self.assertFalse(out["QUALITY_VERIFIED"])


if __name__ == "__main__":
    unittest.main()
