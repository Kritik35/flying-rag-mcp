"""Retrieval trace: a degraded contour must not look like a healthy one.

A hybrid request served by the dense channel alone is degraded. Before this,
the fallback was a stderr line and the trace was identical either way.
"""
from __future__ import annotations

import unittest

from rag_server.tools import blocked_result, merge_search_traces


def _sub(channels, fusion, score_kind, degraded=False, reason=""):
    return {
        "channels": channels,
        "fusion": fusion,
        "score_kind": score_kind,
        "hybrid_requested": True,
        "degraded": degraded,
        "degraded_reason": reason,
    }


class MergeSearchTracesTests(unittest.TestCase):
    def test_single_healthy_hybrid_subquery(self):
        merged = merge_search_traces(
            [_sub(["dense", "fts"], "linear_combination", "linear_combination")], 1
        )
        self.assertEqual(merged["channels"], ["dense", "fts"])
        self.assertEqual(merged["fusion"], "linear_combination")
        self.assertFalse(merged["degraded"])

    def test_dense_only_fallback_is_marked_degraded(self):
        merged = merge_search_traces(
            [_sub(["dense"], "none", "dense_similarity", True, "hybrid_failed: X")], 1
        )
        self.assertTrue(merged["degraded"])
        self.assertEqual(merged["channels"], ["dense"])
        self.assertIn("hybrid_failed", merged["degraded_reason"])

    def test_several_subqueries_are_fused_by_rrf(self):
        merged = merge_search_traces(
            [
                _sub(["dense", "fts"], "linear_combination", "linear_combination"),
                _sub(["dense", "fts"], "linear_combination", "linear_combination"),
            ],
            2,
        )
        self.assertEqual(merged["fusion"], "rrf")
        self.assertEqual(merged["score_kind"], "rrf")
        self.assertEqual(merged["subqueries"], 2)

    def test_one_degraded_subquery_degrades_the_whole_retrieval(self):
        merged = merge_search_traces(
            [
                _sub(["dense", "fts"], "linear_combination", "linear_combination"),
                _sub(["dense"], "none", "dense_similarity", True, "hybrid_returned_empty"),
            ],
            2,
        )
        self.assertTrue(merged["degraded"])
        self.assertEqual(merged["degraded_subqueries"], 1)
        self.assertEqual(merged["degraded_reason"], "hybrid_returned_empty")

    def test_channels_are_unioned_without_duplicates(self):
        merged = merge_search_traces(
            [
                _sub(["dense", "fts"], "linear_combination", "linear_combination"),
                _sub(["dense"], "none", "dense_similarity", True),
            ],
            2,
        )
        self.assertEqual(merged["channels"], ["dense", "fts"])

    def test_no_subqueries_reports_nothing_rather_than_guessing(self):
        merged = merge_search_traces([], 0)
        self.assertEqual(merged["channels"], [])
        self.assertEqual(merged["fusion"], "none")
        self.assertEqual(merged["score_kind"], "unknown")
        self.assertFalse(merged["degraded"])


class BlockedResultTests(unittest.TestCase):
    """A refused search states why, instead of returning zero hits."""

    def test_plain_mode_carries_code_and_action(self):
        out = blocked_result(
            "embedding_contract_mismatch", "expected X, server ran Y", "reload the model"
        )
        self.assertIsInstance(out, list)
        self.assertEqual(out[0]["error_code"], "embedding_contract_mismatch")
        self.assertEqual(out[0]["status"], "blocked")
        self.assertEqual(out[0]["action"], "reload the model")

    def test_debug_mode_keeps_the_debug_envelope(self):
        out = blocked_result("x_code", "detail", "action", debug=True)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["debug"]["status"], "blocked")
        self.assertEqual(out["debug"]["error_code"], "x_code")

    def test_blocked_is_distinguishable_from_an_empty_result_set(self):
        blocked = blocked_result("code", "detail", "action")
        self.assertNotEqual(blocked, [])
        self.assertTrue(all("error_code" in item for item in blocked))


if __name__ == "__main__":
    unittest.main()
