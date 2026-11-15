"""
tests/test_stitcher_provenance.py

Unit tests for Stage 4.1 safe sequential stitcher & structural provenance:
1. Single chunk self-contained boundary extraction.
2. Contiguous multi-chunk stitching with overlap confirmation.
3. Rejection of non-adjacent chunk sets.
4. Rejection of zero-overlap chunks (no silent newline join).
5. Accurate detection of dropped mathematical formula expressions (OMML loss).
6. Generation of distinct physical source_spans with offsets and sha256.
"""
from __future__ import annotations
import unittest
from evidence_gate.stitcher import (
    stitch_sequential_chunks,
    compute_overlap,
    check_formula_integrity,
    match_structural_element
)


class StitcherProvenanceTests(unittest.TestCase):
    def test_single_chunk_sufficiency(self):
        text = "Вводный текст.\n6.4 В пределах одного отсека устройства наружного воздуха.\n6.5 Общие устройства..."
        chunks = [{"parent_id": "doc1_p_0001", "source_path": "doc.docx", "text": text}]
        res = stitch_sequential_chunks(chunks, "6.4")

        self.assertEqual(res.boundary_integrity, "EXACT_BOUNDARIES")
        self.assertEqual(res.text_integrity, "COMPLETE")
        self.assertEqual(res.parent_ids, ["doc1_p_0001"])
        self.assertEqual(len(res.source_spans), 1)
        self.assertIn("6.4 В пределах", res.certified_text)
        self.assertNotIn("6.5 Общие", res.certified_text)

    def test_multi_chunk_sequential_stitching_with_overlap(self):
        text_a = "Раздел 6.\n6.4 Начало сложного нормативного пункта, который переходит через границу чанка в следующий кусок документа."
        # Overlap of 30 characters: "в следующий кусок документа."
        overlap_str = "в следующий кусок документа."
        text_b = overlap_str + " Продолжение пункта 6.4 с детальными требованиями.\n6.5 Следующий пункт..."

        chunks = [
            {"parent_id": "doc1_p_0017", "source_path": "doc.docx", "text": text_a},
            {"parent_id": "doc1_p_0018", "source_path": "doc.docx", "text": text_b}
        ]

        res = stitch_sequential_chunks(chunks, "6.4")
        self.assertEqual(res.boundary_integrity, "EXACT_BOUNDARIES")
        self.assertEqual(res.text_integrity, "COMPLETE")
        self.assertEqual(res.parent_ids, ["doc1_p_0017", "doc1_p_0018"])
        self.assertEqual(len(res.source_spans), 2)
        # Check no duplicated overlap string in certified text
        self.assertEqual(res.certified_text.count(overlap_str), 1)
        self.assertIn("Продолжение пункта 6.4", res.certified_text)

    def test_non_adjacent_chunk_rejection(self):
        chunks = [
            {"parent_id": "doc1_p_0017", "source_path": "doc.docx", "text": "6.4 Начало..."},
            {"parent_id": "doc1_p_0051", "source_path": "doc.docx", "text": "Случайный кусок с ссылкой на 6.4..."}
        ]
        res = stitch_sequential_chunks(chunks, "6.4")
        self.assertEqual(res.boundary_integrity, "NOT_FOUND")
        self.assertEqual(res.certified_text, "")
        self.assertIn("Non-adjacent parent chunks cannot be stitched", res.error)

    def test_zero_overlap_broken_chain_rejection(self):
        chunks = [
            {"parent_id": "doc1_p_0001", "source_path": "doc.docx", "text": "6.4 Текст первой половины без общего суффикса."},
            {"parent_id": "doc1_p_0002", "source_path": "doc.docx", "text": "Совершенно другой фрагмент текста."}
        ]
        res = stitch_sequential_chunks(chunks, "6.4")
        self.assertEqual(res.text_integrity, "BROKEN_CHAIN_NO_OVERLAP")
        self.assertIn("Silent concatenation prohibited", res.error)

    def test_missing_formula_detection(self):
        text_with_missing_formula = (
            "А.3 Расход тепла определяется по формуле\n"
            " (А.5) \n"
            "где Ln - требуемый расход;\n"
            " (А.6) \n"
            "где плотность воздуха."
        )
        status, missing = check_formula_integrity(text_with_missing_formula)
        self.assertEqual(status, "FORMULA_MISSING")
        self.assertIn("(А.5)", missing)
        self.assertIn("(А.6)", missing)

    def test_valid_formula_verification(self):
        text_with_valid_math = (
            "Расход определяется по формуле\n"
            " (1) \n"
            "Q = m * c * (t2 - t1)\n"
            "где Q - количество теплоты."
        )
        status, missing = check_formula_integrity(text_with_valid_math)
        self.assertEqual(status, "FORMULAS_VERIFIED")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
