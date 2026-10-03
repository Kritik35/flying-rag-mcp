"""The named-norm read follows the caller's words, not the planner's guesses.

The planner adds "СП 7.13130 противодымная вентиляция …" to fire-safety
questions that name no norm. Reading the designations from every subquery
restricted an extra read to that guess and pushed the right document out of
`smoke-exceptions` (rr 1.0 → 0). On the 11 real queries that do name a norm,
the read puts it in the top five 7 times against 5 without it.
"""
from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _run(query: str, subqueries: list[str]) -> list:
    import rag_server.tools as tools
    from rag_server.query_planner import QueryPlan

    filters: list = []

    def fake_search(*_a, **kw):
        filters.append(kw.get("folder_filter"))
        return [{"chunk_id": "c1", "doc_id": "d1", "text": "t", "source_path": "a.pdf",
                 "score": 0.9}]

    class FakeProvider:
        def get_model_name(self):
            return "fake-model"

    route = SimpleNamespace(route="normative_fire", dataset=None, folder_filter=None,
                            inferred_dataset=None, inferred_folder_filter=None, reason="test",
                            confidence=0.0, matched_terms=[], ambiguous=False, structured=False,
                            structured_label=None)
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        for target, kwargs in [
            ((tools, "_db_paths"), {"return_value": (Path(tmp) / "lancedb", Path(tmp) / "m.db")}),
            ((tools, "_cfg"), {"return_value": {"retrieval": {"auto_rerank": False,
                                                               "named_norm_guard": True}}}),
        ]:
            stack.enter_context(patch.object(*target, **kwargs))
        for name, kwargs in [
            ("embedder.client._DEFAULT_PROVIDER", {"new": FakeProvider()}),
            ("embedder.client.get_embeddings",
             {"side_effect": lambda texts, is_query=False: [[1.0, 0.0] for _ in texts]}),
            ("rag_server.query_router.route_query", {"return_value": route}),
            ("rag_server.query_planner.plan_query",
             {"return_value": QueryPlan("normative_fire", "test", subqueries, False)}),
            ("storage.vector_store.search", {"side_effect": fake_search}),
            ("storage.vector_store.search_exact", {"return_value": []}),
            ("rag_server.retrieval_quality.apply_retrieval_quality",
             {"side_effect": lambda _q, results, **_kw: results}),
            ("rag_server.rerank_policy.decide_rerank",
             {"return_value": SimpleNamespace(apply=False, reason="not_needed")}),
            ("storage.source_focus.concentrate_sources",
             {"side_effect": lambda results, **_kw: results}),
            ("rag_server.crag.grade_retrieval",
             {"return_value": SimpleNamespace(needs_correction=False, label="correct",
                                              confidence=1.0, reason="test")}),
        ]:
            stack.enter_context(patch(name, **kwargs))
        tools.search_documents(query, top_k=1, use_cache=False)
    return filters


class NamedNormGuardTests(unittest.TestCase):
    def test_a_norm_only_the_planner_mentions_is_not_read(self):
        filters = _run("когда можно не делать систему удаления продуктов горения",
                       ["когда можно не делать систему удаления продуктов горения",
                        "СП 7.13130 противодымная вентиляция дымоудаление требования"])
        self.assertNotIn("СП 7.13130", filters)

    def test_a_norm_the_caller_names_is_read(self):
        filters = _run("кратность воздухообмена электрощитовой СП 60.13330",
                       ["кратность воздухообмена электрощитовой СП 60.13330"])
        self.assertIn("СП 60.13330", filters)


if __name__ == "__main__":
    unittest.main()
