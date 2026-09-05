"""Gates of the source-verified eval harness.

The point of these gates is that a number the harness prints must be a
measurement. An unverified golden set, a degraded contour, or a term matched in
a file name instead of the text all produce a plausible-looking score that means
nothing, so each of those must fail loudly.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

import rag_eval  # noqa: E402
from evaluation.metrics import content_contains, source_is_relevant  # noqa: E402

GATES_STRICT = {"require_trace_ok": True, "require_parent_context": True}
GATES_OFF = {"require_trace_ok": False, "require_parent_context": False}


def _result(name: str, text: str, score: float = 0.8, context: str = "parent") -> dict:
    return {
        "file_name": name,
        "source_path": f"/corpus/{name}",
        "text": text,
        "child_text": text,
        "score": score,
        "context_source": context,
    }


def _trace(status: str = "ok", **kwargs) -> dict:
    trace = {"status": status, "retrieval": {"degraded": False, "channels": ["dense", "fts"]}}
    trace.update(kwargs)
    return trace


def _case(**overrides) -> dict:
    base = {"query": "требования к вентиляции", "id": "c1"}
    base.update(overrides)
    return rag_eval.normalize_case(base)


class RelevanceTests(unittest.TestCase):
    """Source relevance must not be satisfiable by a word in the text."""

    def test_source_match_uses_the_file_not_the_body(self):
        hit = _result("СП 7.13130.txt", "нерелевантный текст")
        miss = _result("СП 60.13330.txt", "здесь написано 7.13130 в теле документа")

        self.assertTrue(source_is_relevant(hit, ["7.13130"]))
        self.assertFalse(source_is_relevant(miss, ["7.13130"]))

    def test_content_match_ignores_the_file_name(self):
        result = _result("дымоудаление.txt", "текст без искомого слова")
        self.assertFalse(content_contains(result, "дымоудал"))
        self.assertTrue(content_contains(_result("x.txt", "система дымоудаления"), "дымоудал"))


class CaseGateTests(unittest.TestCase):
    def test_clean_case_passes(self):
        case = _case(source_any=["7.13130"], must_find=["дымоудал"])
        results = [_result("СП 7.13130.txt", "система дымоудаления коридоров")]

        self.assertEqual(check := rag_eval.check_case(case, results, _trace(), 5, GATES_STRICT), [])
        del check

    def test_missing_source_fails(self):
        case = _case(source_any=["7.13130"])
        results = [_result("СП 60.13330.txt", "вентиляция")]

        failures = rag_eval.check_case(case, results, _trace(), 5, GATES_STRICT)
        self.assertTrue(any("source_any" in f for f in failures))

    def test_source_outside_the_top_window_fails_source_top_any(self):
        case = _case(source_top_any=["7.13130"], source_top_k=2)
        results = [
            _result("a.txt", "x"), _result("b.txt", "x"), _result("СП 7.13130.txt", "x")
        ]

        failures = rag_eval.check_case(case, results, _trace(), 5, GATES_STRICT)
        self.assertTrue(any("source_top_any" in f for f in failures))

    def test_must_find_requires_one_chunk_by_default(self):
        case = _case(source_any=["a.txt"], must_find=["подпор", "лестничн"])
        split = [_result("a.txt", "подпор воздуха"), _result("a.txt", "лестничная клетка")]

        failures = rag_eval.check_case(case, split, _trace(), 5, GATES_STRICT)
        self.assertTrue(any("same" not in f and "must_find" in f for f in failures))

    def test_must_find_can_be_allowed_across_chunks(self):
        case = _case(
            source_any=["a.txt"], must_find=["подпор", "лестничн"],
            must_find_same_chunk=False,
        )
        split = [_result("a.txt", "подпор воздуха"), _result("a.txt", "лестничная клетка")]

        self.assertEqual(rag_eval.check_case(case, split, _trace(), 5, GATES_STRICT), [])

    def test_forbidden_source_is_a_failure(self):
        case = _case(source_any=["проект"], forbid_sources=["СП "])
        results = [_result("проект ОВ.txt", "x"), _result("СП 60.13330.txt", "x")]

        failures = rag_eval.check_case(case, results, _trace(), 5, GATES_STRICT)
        self.assertTrue(any("forbidden" in f for f in failures))

    def test_blocked_contour_cannot_score(self):
        case = _case(source_any=["a.txt"])
        results = [_result("a.txt", "x")]
        trace = _trace("blocked", error_code="embedding_contract_mismatch")

        failures = rag_eval.check_case(case, results, trace, 5, GATES_STRICT)
        self.assertTrue(any("trace_status=blocked" in f for f in failures))
        self.assertTrue(any("embedding_contract_mismatch" in f for f in failures))

    def test_degraded_contour_cannot_score(self):
        case = _case(source_any=["a.txt"])
        trace = _trace("degraded")
        trace["retrieval"] = {"degraded": True, "degraded_reason": "hybrid_failed"}

        failures = rag_eval.check_case(case, [_result("a.txt", "x")], trace, 5, GATES_STRICT)
        self.assertTrue(any("trace_status=degraded" in f for f in failures))

    def test_child_only_results_fail_the_parent_gate(self):
        case = _case(source_any=["a.txt"])
        results = [_result("a.txt", "x", context="child")]

        failures = rag_eval.check_case(case, results, _trace(), 5, GATES_STRICT)
        self.assertIn("no_parent_context", failures)

    def test_gates_can_be_relaxed_explicitly(self):
        case = _case(source_any=["a.txt"])
        results = [_result("a.txt", "x", context="child")]
        trace = _trace("degraded")

        self.assertEqual(rag_eval.check_case(case, results, trace, 5, GATES_OFF), [])

    def test_empty_results_fail(self):
        failures = rag_eval.check_case(_case(source_any=["a"]), [], _trace(), 5, GATES_OFF)
        self.assertIn("no_results", failures)

    def test_min_top_score_is_enforced_when_set(self):
        case = _case(source_any=["a.txt"], min_top_score=0.6)
        results = [_result("a.txt", "x", score=0.4)]

        failures = rag_eval.check_case(case, results, _trace(), 5, GATES_STRICT)
        self.assertTrue(any("top_score" in f for f in failures))


class VerificationGateTests(unittest.TestCase):
    """An unverified golden set must refuse to produce a number."""

    def _gold_file(self, cases: list[dict]) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump({"schema": rag_eval.GOLD_SCHEMA, "cases": cases}, tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def _args(self, path: Path, require: bool = True):
        parser = rag_eval.build_parser()
        argv = ["run", "--gold", str(path)]
        if not require:
            argv.append("--allow-unverified")
        return parser.parse_args(argv)

    def test_unverified_cases_are_refused(self):
        path = self._gold_file([
            {"query": "q", "id": "c1", "verified": False, "source_any": ["a.txt"]}
        ])
        self.assertIsNone(rag_eval._prepare_cases(self._args(path)))

    def test_verified_case_without_a_source_is_refused(self):
        path = self._gold_file([{"query": "q", "id": "c1", "verified": True}])
        self.assertIsNone(rag_eval._prepare_cases(self._args(path)))

    def test_verified_case_with_a_source_is_accepted(self):
        path = self._gold_file([
            {"query": "q", "id": "c1", "verified": True, "source_any": ["a.txt"]}
        ])
        cases = rag_eval._prepare_cases(self._args(path))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["id"], "c1")

    def test_the_refusal_can_be_overridden_deliberately(self):
        path = self._gold_file([{"query": "q", "id": "c1", "verified": False}])
        cases = rag_eval._prepare_cases(self._args(path, require=False))
        self.assertEqual(len(cases), 1)


class ShippedQuestionsTests(unittest.TestCase):
    """The starter questions must not name their own answers."""

    def test_questions_file_loads(self):
        questions = rag_eval.load_questions(Path("golden/questions.json"))
        self.assertGreaterEqual(len(questions), 10)
        self.assertTrue(all(q.get("query") for q in questions))

    def test_no_question_contains_a_norm_code(self):
        # A question carrying "СП 7.13130" would make any harness that looks for
        # that string a self-fulfilling test.
        import re

        pattern = re.compile(r"\d+\.\d{4,}")
        for question in rag_eval.load_questions(Path("golden/questions.json")):
            self.assertIsNone(
                pattern.search(question["query"]),
                f"question names a norm code: {question['query']!r}",
            )



class RepeatedRunTests(unittest.TestCase):
    """One run of this harness does not measure what it looks like it measures.

    Three identical runs against the live contour gave hit@5 0.8000 every time
    and mrr 0.5458 / 0.5283 / 0.4100, with eight of twenty cases changing rank
    between them. The embedding server is not deterministic — the same string
    embedded twice comes back with cosine 0.99993, and two copies of it in one
    batch differ by 2.9e-3 — so near neighbours swap places. A single number
    hides that, and an MRR delta smaller than the spread means nothing.
    """

    def test_a_stable_metric_reports_no_spread(self):
        from rag_eval import summarise_repeats

        summary = summarise_repeats([
            {"hit_rate@5": 0.8, "mrr": 0.5, "passed": 16, "failed": 4},
            {"hit_rate@5": 0.8, "mrr": 0.5, "passed": 16, "failed": 4},
        ], k=5)

        self.assertEqual(summary["runs"], 2)
        self.assertAlmostEqual(summary["hit_rate@5"]["median"], 0.8)
        self.assertAlmostEqual(summary["hit_rate@5"]["spread"], 0.0)

    def test_the_spread_is_the_full_range(self):
        from rag_eval import summarise_repeats

        summary = summarise_repeats([
            {"hit_rate@5": 0.8, "mrr": 0.5458, "passed": 16, "failed": 4},
            {"hit_rate@5": 0.8, "mrr": 0.5283, "passed": 16, "failed": 4},
            {"hit_rate@5": 0.8, "mrr": 0.4100, "passed": 16, "failed": 4},
        ], k=5)

        self.assertAlmostEqual(summary["mrr"]["min"], 0.4100)
        self.assertAlmostEqual(summary["mrr"]["max"], 0.5458)
        self.assertAlmostEqual(summary["mrr"]["spread"], 0.1358, places=4)
        self.assertAlmostEqual(summary["mrr"]["median"], 0.5283)

    def test_a_single_run_still_summarises(self):
        from rag_eval import summarise_repeats

        summary = summarise_repeats(
            [{"hit_rate@5": 0.75, "mrr": 0.5, "passed": 15, "failed": 5}], k=5)

        self.assertEqual(summary["runs"], 1)
        self.assertAlmostEqual(summary["mrr"]["spread"], 0.0)


class UnstableCaseTests(unittest.TestCase):
    def test_cases_that_move_between_runs_are_named(self):
        from rag_eval import unstable_cases

        runs = [
            [{"id": "a", "rr": 1.0}, {"id": "b", "rr": 0.5}],
            [{"id": "a", "rr": 1.0}, {"id": "b", "rr": 0.25}],
        ]
        self.assertEqual(unstable_cases(runs), {"b": [0.5, 0.25]})

    def test_a_steady_set_reports_nothing(self):
        from rag_eval import unstable_cases

        runs = [[{"id": "a", "rr": 1.0}], [{"id": "a", "rr": 1.0}]]
        self.assertEqual(unstable_cases(runs), {})

    def test_one_run_cannot_be_unstable(self):
        from rag_eval import unstable_cases

        self.assertEqual(unstable_cases([[{"id": "a", "rr": 1.0}]]), {})


class DeltaSignificanceTests(unittest.TestCase):
    """A difference inside the spread is not a result."""

    def test_a_delta_below_the_spread_is_not_significant(self):
        from rag_eval import is_significant

        self.assertFalse(is_significant(delta=0.05, spread=0.14))

    def test_a_delta_above_the_spread_is_significant(self):
        from rag_eval import is_significant

        self.assertTrue(is_significant(delta=0.35, spread=0.14))

    def test_direction_does_not_matter(self):
        from rag_eval import is_significant

        self.assertTrue(is_significant(delta=-0.35, spread=0.14))

    def test_without_a_spread_nothing_can_be_ruled_out(self):
        from rag_eval import is_significant

        self.assertTrue(is_significant(delta=0.01, spread=0.0))

if __name__ == "__main__":
    unittest.main()
