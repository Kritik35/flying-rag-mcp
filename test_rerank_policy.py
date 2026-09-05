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

    def test_every_route_the_planner_can_emit_is_recognised(self):
        """The policy gated on a hardcoded list of planner route names.

        The planner grew new names — normative_fire, normative_hvac,
        normative_accessibility, normative_fire_alarm, project_scope,
        project_sheet — and the list was not updated, so 16 of 20 golden
        queries came back with 'not_needed' and no rerank at all. Auto mode
        scored hit@5 0.65 where a forced rerank scored 0.80, and the MCP tool
        defaults to auto.

        A list of names drifts. What the planner *did* does not.
        """
        from rag_server.query_planner import (
            PROJECT_SHEET_EXPANSIONS, ROUTE_EXPANSIONS, plan_query,
        )

        emitted = set(ROUTE_EXPANSIONS) | {"project_sheet", "fire_smoke",
                                           "fire_egress", "hvac",
                                           "project_documentation",
                                           "project_smoke"}
        for route in sorted(emitted):
            plan = QueryPlan(route=route, reason="", queries=["q", "q2", "q3"],
                             broad=True)
            decision = decide_rerank(
                explicit_rerank=None, auto_enabled=True, plan=plan,
                quality_pool=[{"score": 0.9}] * 10, top_k=5,
            )
            self.assertTrue(decision.apply, f"{route}: {decision.reason}")

    def test_an_expanded_query_is_reranked_whatever_the_route_is_called(self):
        plan = QueryPlan(route="some_route_invented_next_month", reason="",
                         queries=["q", "q2", "q3", "q4"], broad=False)

        decision = decide_rerank(
            explicit_rerank=None, auto_enabled=True, plan=plan,
            quality_pool=[{"score": 0.9}] * 10, top_k=5,
        )

        self.assertTrue(decision.apply)
        self.assertEqual(decision.reason, "expanded_query")

    def test_a_single_confident_query_is_still_left_alone(self):
        plan = QueryPlan(route="default", reason="", queries=["q"], broad=False)

        decision = decide_rerank(
            explicit_rerank=None, auto_enabled=True, plan=plan,
            quality_pool=[{"score": 0.95}, {"score": 0.90}, {"score": 0.60}],
            top_k=2,
        )

        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason, "not_needed")

    def test_an_explicit_no_still_wins_over_an_expanded_plan(self):
        plan = QueryPlan(route="normative_fire", reason="",
                         queries=["q", "q2", "q3"], broad=True)

        decision = decide_rerank(
            explicit_rerank=False, auto_enabled=True, plan=plan,
            quality_pool=[{"score": 0.9}] * 10, top_k=5,
        )

        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason, "disabled")

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
