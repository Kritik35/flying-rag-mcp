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


if __name__ == "__main__":
    unittest.main()
