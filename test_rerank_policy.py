from __future__ import annotations

import unittest

from rag_server.query_planner import QueryPlan
from rag_server.rerank_policy import decide_rerank


class RerankPolicyTests(unittest.TestCase):
    def test_explicit_true_forces_rerank(self):
        plan = QueryPlan(route="default", reason="", queries=["q"], broad=False)

        decision = decide_rerank(
            explicit_rerank=True,
            auto_enabled=False,
            plan=plan,
            quality_pool=[{"score": 0.9}],
            top_k=5,
        )

        self.assertTrue(decision.apply)
        self.assertEqual(decision.reason, "forced")

    def test_explicit_false_disables_rerank(self):
        plan = QueryPlan(route="fire_smoke", reason="", queries=["q"] * 4, broad=True)

        decision = decide_rerank(
            explicit_rerank=False,
            auto_enabled=True,
            plan=plan,
            quality_pool=[{"score": 0.2}] * 10,
            top_k=5,
        )

        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason, "disabled")

    def test_auto_rerank_applies_to_broad_normative_routes(self):
        plan = QueryPlan(route="fire_smoke", reason="", queries=["q"] * 5, broad=True)

        decision = decide_rerank(
            explicit_rerank=None,
            auto_enabled=True,
            plan=plan,
            quality_pool=[{"score": 0.8}] * 12,
            top_k=5,
        )

        self.assertTrue(decision.apply)
        self.assertEqual(decision.reason, "complex_route")

    def test_auto_rerank_applies_when_top_scores_are_weak(self):
        plan = QueryPlan(route="default", reason="", queries=["q"], broad=False)

        decision = decide_rerank(
            explicit_rerank=None,
            auto_enabled=True,
            plan=plan,
            quality_pool=[{"score": 0.35}, {"score": 0.31}, {"score": 0.2}],
            top_k=2,
        )

        self.assertTrue(decision.apply)
        self.assertEqual(decision.reason, "weak_scores")

    def test_auto_rerank_skips_simple_confident_queries(self):
        plan = QueryPlan(route="default", reason="", queries=["q"], broad=False)

        decision = decide_rerank(
            explicit_rerank=None,
            auto_enabled=True,
            plan=plan,
            quality_pool=[{"score": 0.9}, {"score": 0.85}, {"score": 0.8}],
            top_k=2,
        )

        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason, "not_needed")

    def test_auto_rerank_respects_global_switch(self):
        plan = QueryPlan(route="fire_smoke", reason="", queries=["q"] * 5, broad=True)

        decision = decide_rerank(
            explicit_rerank=None,
            auto_enabled=False,
            plan=plan,
            quality_pool=[{"score": 0.2}] * 12,
            top_k=5,
        )

        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason, "auto_disabled")


if __name__ == "__main__":
    unittest.main()
