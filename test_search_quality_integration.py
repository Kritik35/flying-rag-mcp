from __future__ import annotations

import os
import unittest


RUN_INTEGRATION = os.environ.get("FLYING_RAG_RUN_INTEGRATION") == "1"


# Golden line: each case asserts >=3 results and that at least one expected
# token appears across returned file names + text. Tokens were verified against
# the live indexed corpus (probe 2026-06-14) so the bar reflects real retrieval,
# not aspiration. Loose OR-of-tokens keeps cases robust to ranking jitter.
GOLDEN_CASES = [
    # tag, query, dataset, expected_any (casefold tokens)
    ("egress_width", "ширина эвакуационных путей и выходов", "normative",
     ["1.13130", "эвакуац", "выход"]),
    ("smoke_parking", "дымоудаление из подземной автостоянки", "normative",
     ["7.13130", "дымоудал", "автостоянк", "вентиляц"]),
    ("smoke_pressurization", "подпор воздуха в лестничную клетку при пожаре", "normative",
     ["подпор", "противодым", "123-фз", "258.1311500", "лестнич"]),
    ("hvac_air_exchange", "кратность воздухообмена в помещениях", "normative",
     ["воздухообмен", "кратност", "вентиляц"]),
    ("hvac_heat_carrier", "температура теплоносителя в системе отопления", "normative",
     ["теплоносител", "отоплен", "температур"]),
    ("accessibility_mgn", "доступность зданий для маломобильных групп населения", "normative",
     ["59.13330", "маломобильн", "доступност"]),
    ("fire_alarm", "автоматическая пожарная сигнализация и оповещение", "normative",
     ["пожарн", "сигнализац", "оповещен"]),
    ("concrete_class", "класс бетона по прочности на сжатие", "normative",
     ["бетон", "63.13330", "41.13330", "прочност"]),
]


@unittest.skipUnless(RUN_INTEGRATION, "set FLYING_RAG_RUN_INTEGRATION=1 to run live RAG quality tests")
class GoldenLineTests(unittest.TestCase):
    def test_golden_cases_return_expected_sources(self):
        from rag_server.tools import search_documents

        for tag, query, dataset, expected_any in GOLDEN_CASES:
            with self.subTest(case=tag):
                results = search_documents(query, top_k=8, dataset=dataset, alpha=0.7, use_cache=False)
                self.assertGreaterEqual(
                    len(results), 3, f"{tag}: expected >=3 results, got {len(results)}"
                )
                blob = " ".join(
                    f"{r.get('file_name', '')} {r.get('text', '')}" for r in results
                ).casefold()
                self.assertTrue(
                    any(tok in blob for tok in expected_any),
                    f"{tag}: none of {expected_any} found in results",
                )
                self.assertTrue(
                    all(r.get("context_source") in {"parent", "parent_truncated", "child", "child_truncated"} for r in results[:3]),
                    f"{tag}: missing context_source in top-3",
                )


@unittest.skipUnless(RUN_INTEGRATION, "set FLYING_RAG_RUN_INTEGRATION=1 to run live RAG quality tests")
class SearchQualityIntegrationTests(unittest.TestCase):
    def test_normative_fire_smoke_query_returns_fire_sources(self):
        from rag_server.tools import search_documents

        results = search_documents(
            "Где нужна противодымная вентиляция?",
            top_k=8,
            dataset="normative",
            alpha=0.7,
            use_cache=False,
        )

        joined_sources = " ".join(str(r.get("file_name", "")) for r in results).casefold()
        joined_text = " ".join(str(r.get("text", "")) for r in results).casefold()
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue(
            "7.13130" in joined_sources
            or "мчс" in joined_sources
            or "противодым" in joined_sources
            or "противодым" in joined_text
        )

    def test_project_smoke_query_prefers_ov_or_pv_sources(self):
        from rag_server.tools import search_documents

        results = search_documents(
            "противодымная вентиляция ОВ2",
            top_k=6,
            dataset="project",
            alpha=0.7,
            use_cache=False,
        )

        top_sources = " ".join(
            f"{r.get('file_name', '')} {r.get('source_path', '')}" for r in results[:4]
        ).casefold()
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue("ов2" in top_sources or "пв" in top_sources)
        self.assertNotIn("эом", top_sources)

    def test_hvac_query_returns_sp60_or_hvac_terms(self):
        from rag_server.tools import search_documents

        results = search_documents(
            "Как определить расход воздуха для вентиляции?",
            top_k=8,
            dataset="normative",
            alpha=0.7,
            use_cache=False,
        )

        joined = " ".join(
            f"{r.get('file_name', '')} {r.get('text', '')}" for r in results
        ).casefold()
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue("60.13330" in joined or "воздухообмен" in joined or "расход воздуха" in joined)


@unittest.skipUnless(RUN_INTEGRATION, "set FLYING_RAG_RUN_INTEGRATION=1 to run live RAG quality tests")
class RoutingIntegrationTests(unittest.TestCase):
    def test_project_ov2_query_without_folder_filter_stays_in_ov2(self):
        # The original bug: a project ОВ2 query with no folder_filter leaked
        # into normative/ЭОМ. Auto-routing must keep top sources in ОВ2.
        from rag_server.tools import search_documents

        results = search_documents(
            "противодымная вентиляция ОВ2", top_k=5, use_cache=False
        )
        self.assertGreaterEqual(len(results), 1)
        top_blob = " ".join(
            f"{r.get('file_name','')} {r.get('source_path','')}" for r in results[:3]
        ).casefold()
        self.assertTrue(
            "ов2" in top_blob,
            f"expected ОВ2 sources, got: {top_blob[:200]}",
        )
        self.assertNotIn("эом", top_blob)

    def test_normative_fire_query_returns_fire_sources(self):
        from rag_server.tools import search_documents

        results = search_documents(
            "Где нужна противодымная вентиляция?", dataset="normative",
            top_k=8, use_cache=False,
        )
        blob = " ".join(
            f"{r.get('file_name','')} {r.get('text','')}" for r in results
        ).casefold()
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue("7.13130" in blob or "противодым" in blob)

    def test_debug_trace_returns_routing_and_structured_hint(self):
        from rag_server.tools import search_documents

        out = search_documents(
            "параметр настройки систем ОВ2", top_k=5, use_cache=False, debug=True
        )
        self.assertIsInstance(out, dict)
        self.assertIn("debug", out)
        self.assertIn("results", out)
        dbg = out["debug"]
        self.assertEqual(dbg["route"], "project_ov2")
        self.assertEqual(dbg["applied_dataset"], "project")
        self.assertIn("structured_hint", dbg)
        self.assertEqual(dbg["structured_hint"]["suggested_label"], "Параметр настройки")

    def test_debug_false_keeps_list_return_shape(self):
        from rag_server.tools import search_documents

        out = search_documents("противодымная вентиляция ОВ2", top_k=3, use_cache=False)
        self.assertIsInstance(out, list)


@unittest.skipUnless(RUN_INTEGRATION, "set FLYING_RAG_RUN_INTEGRATION=1 to run live RAG quality tests")
class RerankerIntegrationTests(unittest.TestCase):
    def test_cross_encoder_promotes_relevant_chunk_over_high_vector_score(self):
        # Native Lemonade cross-encoder must override a misleading vector score:
        # the irrelevant high-score chunk should drop out of top-2.
        from rag_server.reranker import rerank_chunks

        chunks = [
            {"chunk_id": "irrelevant", "score": 0.95,
             "text": "Класс бетона по прочности на сжатие B25 для фундаментов"},
            {"chunk_id": "relevant", "score": 0.50,
             "text": "Систему дымоудаления допускается не предусматривать из помещений "
                     "площадью менее 200 кв.м"},
            {"chunk_id": "mid", "score": 0.70,
             "text": "Вентиляция общественных зданий, кратность воздухообмена"},
        ]
        ranked = rerank_chunks("в каких случаях не нужно дымоудаление", chunks, top_k=2)

        self.assertEqual(ranked[0]["chunk_id"], "relevant")
        self.assertGreater(ranked[0]["rerank_score"], ranked[1]["rerank_score"])
        self.assertNotIn("irrelevant", [c["chunk_id"] for c in ranked])


if __name__ == "__main__":
    unittest.main()
