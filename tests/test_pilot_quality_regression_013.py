"""
tests/test_pilot_quality_regression_013.py

Offline regression fixtures for Stage 4.2.8 / POST-PILOT-QUALITY-01 (TZ-013).
Addresses the two key retrieval quality failure modes uncovered by the 6-query pilot:
1. CLAUSE_TABLE_COMPLETENESS: Detecting chunk boundary truncation of normative clauses
   and tables (e.g. SP 7.13130 clause 6.10) to return EVIDENCE_PARTIAL instead of false certainty.
2. EDITION_DISAMBIGUATION: Explicit detection of multi-edition collision (e.g. SP 60.13330
   2012 vs 2020) when query lacks edition year, avoiding uncertified edition selection.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict, List

from rag_server.norm_resolver import parse_norm_query, NormRef


def evaluate_clause_boundary_completeness(text: str, clause_num: str) -> Dict[str, Any]:
    """
    Evaluates whether a retrieved clause text is structurally complete
    or truncated at a chunk boundary (e.g. unclosed enumeration, dangling conjunction, missing table).
    """
    text_clean = text.strip()
    if not text_clean:
        return {"status": "NOT_FOUND", "is_complete": False}

    # Check for unclosed enumeration or trailing punctuation indicating truncation
    dangling_endings = (";", ",", "...", "а также", "в том числе", "следующие:", "подпунктам")
    ends_dangling = any(text_clean.rstrip().endswith(d) for d in dangling_endings)
    has_terminal_period = text_clean.rstrip().endswith(".") or text_clean.rstrip().endswith(")")

    # Check for balanced parentheses
    balanced_parens = text_clean.count("(") == text_clean.count(")")

    # Check if clause header exists
    has_header = f"{clause_num}" in text_clean

    if not has_header:
        return {"status": "HEADER_MISSING", "is_complete": False}

    if ends_dangling or not has_terminal_period or not balanced_parens:
        return {
            "status": "TRUNCATED",
            "is_complete": False,
            "evidence_status": "EVIDENCE_PARTIAL",
            "reason": "Clause ends on open enumeration or dangling punctuation across chunk boundary"
        }

    return {
        "status": "COMPLETE",
        "is_complete": True,
        "evidence_status": "USABLE_FOR_ANSWER",
        "reason": "Clause has complete terminal boundary"
    }


def disambiguate_editions(
    query_text: str,
    available_documents: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Disambiguates document editions when multiple revisions exist in corpus.
    If query lacks year: flags AMBIGUOUS_EDITIONS / REFUSAL_REQUIRED.
    If query specifies year: strictly filters candidates to target edition.
    """
    norm_ref = parse_norm_query(query_text)
    if not norm_ref:
        return {"status": "NO_NORM", "matched_editions": []}

    target_year = norm_ref.year

    # Extract distinct edition years from candidate documents
    candidate_editions = set()
    for doc in available_documents:
        fn = doc.get("file_name", "")
        for y in ("2012", "2016", "2020", "2021", "2024", "2025"):
            if y in fn:
                candidate_editions.add(y)

    sorted_editions = sorted(list(candidate_editions))

    if not target_year:
        if len(sorted_editions) > 1:
            return {
                "status": "AMBIGUOUS_EDITIONS",
                "refusal_required": True,
                "detected_editions": sorted_editions,
                "resolved_edition": None,
                "reason": f"Query specifies '{norm_ref.raw_match}' without year, but corpus contains editions: {sorted_editions}"
            }
        elif len(sorted_editions) == 1:
            return {
                "status": "SINGLE_EDITION_INFERRED",
                "refusal_required": False,
                "detected_editions": sorted_editions,
                "resolved_edition": sorted_editions[0],
                "reason": "Single edition in corpus"
            }
        else:
            return {
                "status": "EDITION_UNSPECIFIED",
                "refusal_required": False,
                "detected_editions": [],
                "resolved_edition": None
            }
    else:
        # Year explicitly provided
        if target_year in sorted_editions:
            filtered_docs = [d for d in available_documents if target_year in d.get("file_name", "")]
            return {
                "status": "EXPLICIT_EDITION_MATCHED",
                "refusal_required": False,
                "target_year": target_year,
                "detected_editions": sorted_editions,
                "resolved_edition": target_year,
                "filtered_docs_count": len(filtered_docs)
            }
        else:
            return {
                "status": "REQUESTED_EDITION_NOT_FOUND",
                "refusal_required": True,
                "target_year": target_year,
                "detected_editions": sorted_editions,
                "reason": f"Requested edition {target_year} not found in available corpus editions {sorted_editions}"
            }


class PilotQualityRegressionTests(unittest.TestCase):
    """Synthetic offline regression tests for quality failure modes identified in TZ-013."""

    def test_clause_truncation_detection_sp7_6_10(self):
        """Simulates real chunk 973d9901_p_0021 from SP 7.13130 clause 6.10 ending on open list."""
        # Realistic snippet ending abruptly at chunk boundary
        truncated_chunk = (
            "6.10 Для предотвращения распространения продуктов горения при пожаре по воздуховодам "
            "систем вентиляции должны быть предусмотрены следующие устройства: "
            "а) противопожарные нормально открытые клапаны - на поэтажных сборных воздуховодах, "
            "а также на воздухоприемных устройствах и устройствах подачи воздуха;"
        )
        res = evaluate_clause_boundary_completeness(truncated_chunk, "6.10")
        self.assertEqual(res["status"], "TRUNCATED")
        self.assertFalse(res["is_complete"])
        self.assertEqual(res["evidence_status"], "EVIDENCE_PARTIAL")

    def test_clause_complete_boundary_sp7_6_4(self):
        """Simulates a fully closed clause boundary with terminal period and amendment note."""
        complete_chunk = (
            "6.4 В пределах одного пожарного отсека общие приемные устройства наружного воздуха "
            "не следует предусматривать для систем приточной противодымной вентиляции и для систем "
            "приточной общеобменной вентиляции.\n"
            "(п. 6.4 в ред. Изменения N 3, утв. Приказом МЧС России от 27.03.2025 N 251)."
        )
        res = evaluate_clause_boundary_completeness(complete_chunk, "6.4")
        self.assertEqual(res["status"], "COMPLETE")
        self.assertTrue(res["is_complete"])
        self.assertEqual(res["evidence_status"], "USABLE_FOR_ANSWER")

    def test_edition_disambiguation_unspecified_year_collision(self):
        """Query 'СП 60.13330 пункт 7.1.1' without year must trigger AMBIGUOUS_EDITIONS."""
        available_docs = [
            {"file_name": "СП 60.13330.2012. Свод правил.pdf", "path": "/corpus/2012.pdf"},
            {"file_name": "СП 60.13330.2020. Свод правил.docx", "path": "/corpus/2020.docx"},
        ]
        res = disambiguate_editions("СП 60.13330 пункт 7.1.1", available_docs)
        self.assertEqual(res["status"], "AMBIGUOUS_EDITIONS")
        self.assertTrue(res["refusal_required"])
        self.assertEqual(res["detected_editions"], ["2012", "2020"])
        self.assertIsNone(res["resolved_edition"])

    def test_edition_disambiguation_explicit_year_matched(self):
        """Query 'СП 60.13330.2020 пункт 7.1.1' with year must resolve to 2020."""
        available_docs = [
            {"file_name": "СП 60.13330.2012. Свод правил.pdf", "path": "/corpus/2012.pdf"},
            {"file_name": "СП 60.13330.2020. Свод правил.docx", "path": "/corpus/2020.docx"},
        ]
        res = disambiguate_editions("СП 60.13330.2020 пункт 7.1.1", available_docs)
        self.assertEqual(res["status"], "EXPLICIT_EDITION_MATCHED")
        self.assertFalse(res["refusal_required"])
        self.assertEqual(res["resolved_edition"], "2020")
        self.assertEqual(res["filtered_docs_count"], 1)

    def test_edition_disambiguation_missing_edition_refusal(self):
        """Query 'СП 60.13330.2025 пункт 7.1.1' for nonexistent year must refuse."""
        available_docs = [
            {"file_name": "СП 60.13330.2012. Свод правил.pdf", "path": "/corpus/2012.pdf"},
            {"file_name": "СП 60.13330.2020. Свод правил.docx", "path": "/corpus/2020.docx"},
        ]
        res = disambiguate_editions("СП 60.13330.2025 пункт 7.1.1", available_docs)
        self.assertEqual(res["status"], "REQUESTED_EDITION_NOT_FOUND")
        self.assertTrue(res["refusal_required"])


if __name__ == "__main__":
    unittest.main()
