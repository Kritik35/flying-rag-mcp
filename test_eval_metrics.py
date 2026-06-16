from __future__ import annotations

import unittest


class EvalMetricsTests(unittest.TestCase):
    def _results(self, names):
        return [{"file_name": n, "source_path": "", "text": ""} for n in names]

    def test_is_relevant_matches_any_expected_substring_casefold(self):
        from evaluation.metrics import is_relevant

        r = {"file_name": "СП 60.13330.2020.docx", "source_path": "", "text": ""}
        self.assertTrue(is_relevant(r, ["60.13330"]))
        self.assertTrue(is_relevant(r, ["сп 60"]))  # casefold
        self.assertFalse(is_relevant(r, ["7.13130"]))

    def test_first_relevant_rank_is_one_based(self):
        from evaluation.metrics import first_relevant_rank

        results = self._results(["ГОСТ бетон.docx", "СП 60.13330.docx", "x.docx"])
        self.assertEqual(first_relevant_rank(results, ["60.13330"]), 2)
        self.assertIsNone(first_relevant_rank(results, ["нет такого"]))

    def test_hit_at_k(self):
        from evaluation.metrics import hit_at_k

        results = self._results(["a.docx", "СП 60.13330.docx", "c.docx"])
        self.assertTrue(hit_at_k(results, ["60.13330"], k=2))
        self.assertFalse(hit_at_k(results, ["60.13330"], k=1))

    def test_reciprocal_rank(self):
        from evaluation.metrics import reciprocal_rank

        results = self._results(["a", "b", "СП 60.13330"])
        self.assertAlmostEqual(reciprocal_rank(results, ["60.13330"]), 1 / 3)
        self.assertEqual(reciprocal_rank(results, ["none"]), 0.0)

    def test_precision_at_k(self):
        from evaluation.metrics import precision_at_k

        results = self._results(["СП 60.13330 a", "СП 60.13330 b", "бетон"])
        self.assertAlmostEqual(precision_at_k(results, ["60.13330"], k=3), 2 / 3)

    def test_aggregate_over_cases(self):
        from evaluation.metrics import aggregate

        per_case = [
            {"hit@5": True, "rr": 1.0, "precision@5": 0.4},
            {"hit@5": False, "rr": 0.0, "precision@5": 0.0},
        ]
        agg = aggregate(per_case, k=5)
        self.assertAlmostEqual(agg["hit_rate@5"], 0.5)
        self.assertAlmostEqual(agg["mrr"], 0.5)
        self.assertAlmostEqual(agg["mean_precision@5"], 0.2)
        self.assertEqual(agg["n"], 2)


if __name__ == "__main__":
    unittest.main()
