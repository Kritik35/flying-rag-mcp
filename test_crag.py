from __future__ import annotations

import unittest
from dataclasses import dataclass


@dataclass(frozen=True)
class _Route:
    route: str
    folder_filter: str | None = None
    inferred_folder_filter: str | None = None


class CragGradeTests(unittest.TestCase):
    def _res(self, names_scores):
        return [{"file_name": n, "source_path": "", "text": "", "score": s}
                for n, s in names_scores]

    def test_empty_results_is_incorrect_and_needs_correction(self):
        from rag_server.crag import grade_retrieval

        v = grade_retrieval("q", [], _Route("normative_hvac"), top_k=5)
        self.assertEqual(v.label, "incorrect")
        self.assertTrue(v.needs_correction)

    def test_high_top_score_is_correct_no_correction(self):
        from rag_server.crag import grade_retrieval

        results = self._res([("СП 60.docx", 0.92), ("a", 0.7)])
        v = grade_retrieval("воздухообмен", results, _Route("normative_hvac"), top_k=5)
        self.assertEqual(v.label, "correct")
        self.assertFalse(v.needs_correction)

    def test_low_top_score_needs_correction(self):
        from rag_server.crag import grade_retrieval

        results = self._res([("a.docx", 0.20), ("b", 0.1)])
        v = grade_retrieval("q", results, _Route("normative_hvac"), top_k=5)
        self.assertEqual(v.label, "incorrect")
        self.assertTrue(v.needs_correction)

    def test_fewer_than_top_k_but_good_score_does_NOT_need_correction(self):
        # Regression: source-concentration to <=3 docs must not be treated as weak
        # (this caused a needless retry on almost every query, doubling latency).
        from rag_server.crag import grade_retrieval

        results = self._res([("СП.docx", 0.88), ("b", 0.8), ("c", 0.75)])  # 3 < top_k=5
        v = grade_retrieval("q", results, _Route("normative_hvac"), top_k=5)
        self.assertFalse(v.needs_correction)

    def test_project_route_with_missing_folder_marker_needs_correction(self):
        from rag_server.crag import grade_retrieval

        # route expects ОВ2 but no result mentions it
        results = self._res([("ЭОМ раздел.pdf", 0.9), ("ВК.pdf", 0.85)])
        v = grade_retrieval("противодымная вентиляция", results,
                            _Route("project_ov2", folder_filter="ОВ2"), top_k=5)
        self.assertTrue(v.needs_correction)

    def test_project_route_with_present_marker_is_correct(self):
        from rag_server.crag import grade_retrieval

        results = self._res([("проект ОВ2 лист.pdf", 0.9)])
        v = grade_retrieval("противодымная вентиляция", results,
                            _Route("project_ov2", folder_filter="ОВ2"), top_k=5)
        self.assertFalse(v.needs_correction)


if __name__ == "__main__":
    unittest.main()
