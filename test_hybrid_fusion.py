"""How the two channels are combined, and what the trace says about it.

Linear combination adds a cosine similarity to a BM25 score. The two are not on
the same scale and neither is bounded the same way, so the weight is a knob
tuned against one corpus rather than a principled blend. Reciprocal rank fusion
uses only the position a result took in each channel, which is what the ranks
actually mean.

Whichever is used, `score_kind` in the trace has to name it: the retrieval
thresholds elsewhere are read against that field, and calling an RRF score a
linear combination would have them compared to the wrong scale.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from storage.vector_store import build_fusion_reranker


class FusionSelectionTests(unittest.TestCase):
    def test_linear_is_the_documented_default(self):
        reranker, fusion, score_kind = build_fusion_reranker("linear", alpha=0.7)

        self.assertEqual(fusion, "linear_combination")
        self.assertEqual(score_kind, "linear_combination")
        self.assertEqual(type(reranker).__name__, "LinearCombinationReranker")

    def test_rrf_is_selected_by_name(self):
        reranker, fusion, score_kind = build_fusion_reranker("rrf", alpha=0.7)

        self.assertEqual(fusion, "rrf")
        self.assertEqual(score_kind, "rrf")
        self.assertEqual(type(reranker).__name__, "RRFReranker")

    def test_an_unknown_mode_falls_back_to_linear_rather_than_failing(self):
        reranker, fusion, _ = build_fusion_reranker("mystery", alpha=0.7)

        self.assertEqual(fusion, "linear_combination")
        self.assertEqual(type(reranker).__name__, "LinearCombinationReranker")

    def test_the_mode_is_case_and_space_insensitive(self):
        for value in (" RRF ", "Rrf", "rrf"):
            _r, fusion, _s = build_fusion_reranker(value, alpha=0.7)
            self.assertEqual(fusion, "rrf", value)

    def test_alpha_reaches_the_linear_reranker(self):
        reranker, _f, _s = build_fusion_reranker("linear", alpha=0.25)
        self.assertAlmostEqual(reranker.weight, 0.25)


class FusionConfigTests(unittest.TestCase):
    def test_the_mode_comes_from_config(self):
        import storage.vector_store as vs

        with patch.object(vs, "load_config",
                          return_value={"retrieval": {"fusion": "rrf"}}):
            self.assertEqual(vs.fusion_mode(), "rrf")

    def test_an_absent_setting_keeps_the_current_behaviour(self):
        import storage.vector_store as vs

        with patch.object(vs, "load_config", return_value={}):
            self.assertEqual(vs.fusion_mode(), "linear")

    def test_a_broken_config_does_not_break_search(self):
        import storage.vector_store as vs

        with patch.object(vs, "load_config", side_effect=RuntimeError("no config")):
            self.assertEqual(vs.fusion_mode(), "linear")


if __name__ == "__main__":
    unittest.main()
