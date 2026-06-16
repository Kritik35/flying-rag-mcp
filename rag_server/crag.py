"""Corrective-RAG (CRAG) retrieval evaluator — deterministic, no LLM, no reindex.

Grades a finished retrieval as correct / ambiguous / incorrect and tells the
caller whether a corrective action (deterministic query augmentation / scope
widening) is warranted. This unifies and replaces the ad-hoc "weak retry"
heuristic in tools.py.

Design notes:
- Grades on the retrieval *score* and route expectations, NOT on raw result
  count. Source-concentration legitimately returns <top_k results, so a count
  test fired a needless corrective retry on almost every query (latency x2).
- The cross-encoder reranker remains the precision layer; CRAG is the recall
  safety-net that decides when to try harder.
"""
from __future__ import annotations

from dataclasses import dataclass

CORRECT_MIN = 0.55
AMBIGUOUS_MIN = 0.35
_PROJECT_FOLDER_MARKERS = {"ОВ2", "ЭОМ", "ВК"}


@dataclass(frozen=True)
class CragVerdict:
    label: str            # "correct" | "ambiguous" | "incorrect"
    confidence: float     # top result score (0..1)
    reason: str
    needs_correction: bool


def grade_retrieval(
    query: str,
    results: list[dict],
    route,
    top_k: int,
    correct_min: float = CORRECT_MIN,
    ambiguous_min: float = AMBIGUOUS_MIN,
) -> CragVerdict:
    if not results:
        return CragVerdict("incorrect", 0.0, "empty", True)

    top = float(results[0].get("score") or 0.0)

    # Discipline check: a project route that expects a folder marker but whose
    # results don't mention it has retrieved the wrong discipline.
    marker = getattr(route, "folder_filter", None) or getattr(route, "inferred_folder_filter", None)
    route_name = getattr(route, "route", "") or ""
    if route_name.startswith("project") and marker in _PROJECT_FOLDER_MARKERS:
        blob = " ".join(
            f"{r.get('file_name','')} {r.get('source_path','')}" for r in results
        ).casefold()
        if marker.casefold() not in blob:
            return CragVerdict("incorrect", top, "project_folder_marker_absent", True)

    if top >= correct_min:
        return CragVerdict("correct", top, "strong_top_score", False)
    if top >= ambiguous_min:
        return CragVerdict("ambiguous", top, "moderate_top_score", True)
    return CragVerdict("incorrect", top, "weak_top_score", True)
