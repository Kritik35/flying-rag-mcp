import unittest

from rag_server.query_planner import fuse_ranked_results, plan_query


class QueryPlannerTest(unittest.TestCase):
    def test_smoke_control_question_is_decomposed(self):
        plan = plan_query("Где нужна противодымная вентиляция?", dataset="normative")

        joined = " ".join(plan.queries).casefold()
        self.assertEqual(plan.route, "fire_smoke")
        self.assertGreaterEqual(len(plan.queries), 4)
        self.assertIn("сп 7.13130", joined)
        self.assertIn("дымоудал", joined)
        self.assertIn("исключ", joined)

    def test_hvac_question_expands_with_sp60_terms(self):
        plan = plan_query("Как определить расход воздуха для вентиляции?", dataset="normative")

        joined = " ".join(plan.queries).casefold()
        self.assertEqual(plan.route, "hvac")
        self.assertIn("сп 60.13330", joined)
        self.assertIn("воздухообмен", joined)
        self.assertIn("микроклимат", joined)

    def test_project_smoke_query_keeps_project_discipline_terms(self):
        plan = plan_query("противодымная вентиляция ОВ2", dataset="project")

        joined = " ".join(plan.queries).casefold()
        self.assertEqual(plan.route, "project_smoke")
        self.assertIn("ов2", joined)
        self.assertIn("пв", joined)
        self.assertIn("дымоудал", joined)

    def test_the_route_expands_a_query_its_own_tokens_would_miss(self):
        """Router vocabulary and planner vocabulary were two lists that drifted.

        "удаление дыма из коридоров" is a smoke-control question by any reading,
        but the planner's own tokens only knew "противодым"/"дымоудал", so the
        query went to the store as a single unexpanded string.
        """
        from rag_server.query_planner import plan_query

        plan = plan_query(
            "в каких случаях нужно предусматривать удаление дыма из коридоров",
            route="normative_fire",
        )

        self.assertGreater(len(plan.queries), 1)
        self.assertTrue(any("7.13130" in q for q in plan.queries))

    def test_the_fire_alarm_route_expands_towards_alarm_norms(self):
        from rag_server.query_planner import plan_query

        plan = plan_query(
            "где обязательно ставить извещатели и оповещение о пожаре",
            route="normative_fire_alarm",
        )

        self.assertGreater(len(plan.queries), 1)
        self.assertTrue(any("484" in q or "486" in q for q in plan.queries))

    def test_planner_tokens_still_win_over_the_route(self):
        from rag_server.query_planner import plan_query

        plan = plan_query("противодымная вентиляция ОВ2", dataset="project",
                          route="normative_fire")
        self.assertEqual(plan.route, "project_smoke")

    def test_an_unknown_route_changes_nothing(self):
        from rag_server.query_planner import plan_query

        plan = plan_query("случайный запрос", route="whatever")
        self.assertEqual(plan.route, "default")
        self.assertEqual(plan.queries, ["случайный запрос"])

    def test_a_project_question_is_not_expanded_with_norm_wording(self):
        """The planner ignored the dataset and matched on tokens alone.

        "перечень оборудования по вентиляции в проекте" contains "вентиляц", so
        it took the HVAC branch and went to the store as "СП 60.13330 отопление
        вентиляция кондиционирование требования" — norm wording searched inside
        the project's own sheets, with the dataset filter keeping norms out. All
        three expansions were spent looking for something that cannot be there.
        """
        from rag_server.query_planner import plan_query

        plan = plan_query(
            "перечень оборудования по вентиляции в проекте",
            dataset="project", route="project_scope",
        )

        joined = " ".join(plan.queries).casefold()
        self.assertNotIn("сп 60", joined)
        self.assertNotIn("13330", joined)

    def test_a_project_equipment_question_reaches_for_the_schedule(self):
        from rag_server.query_planner import plan_query

        plan = plan_query(
            "перечень оборудования по вентиляции в проекте",
            dataset="project", route="project_scope",
        )

        joined = " ".join(plan.queries).casefold()
        self.assertGreater(len(plan.queries), 1)
        self.assertIn("спецификация оборудования", joined)

    def test_a_project_change_question_reaches_for_the_change_table(self):
        from rag_server.query_planner import plan_query

        plan = plan_query(
            "какие изменения вносились в комплект и когда",
            dataset="project", route="project_scope",
        )

        joined = " ".join(plan.queries).casefold()
        self.assertIn("регистрации изменений", joined)

    def test_a_project_sheet_list_question_reaches_for_the_general_data(self):
        from rag_server.query_planner import plan_query

        plan = plan_query(
            "ведомость рабочих чертежей основного комплекта",
            dataset="project", route="project_scope",
        )

        joined = " ".join(plan.queries).casefold()
        self.assertIn("общие данные", joined)

    def test_the_project_smoke_branch_still_wins(self):
        from rag_server.query_planner import plan_query

        plan = plan_query("противодымная вентиляция ОВ2", dataset="project")
        self.assertEqual(plan.route, "project_smoke")

    def test_a_normative_hvac_question_is_unaffected(self):
        from rag_server.query_planner import plan_query

        plan = plan_query("как определяется воздухообмен помещения", dataset="normative")
        self.assertEqual(plan.route, "hvac")
        self.assertIn("60.13330", " ".join(plan.queries))

    def test_rrf_fusion_promotes_cross_query_evidence_and_merges_duplicates(self):
        first = [
            {"chunk_id": "a", "source_path": "СП 7", "score": 0.90, "text": "smoke"},
            {"chunk_id": "b", "source_path": "СП 60", "score": 0.88, "text": "hvac"},
        ]
        second = [
            {"chunk_id": "c", "source_path": "СП 1", "score": 0.91, "text": "evac"},
            {"chunk_id": "a", "source_path": "СП 7", "score": 0.70, "text": "smoke duplicate"},
        ]

        fused = fuse_ranked_results([first, second], limit=3)

        self.assertEqual([item["chunk_id"] for item in fused], ["a", "c", "b"])
        self.assertEqual(fused[0]["matched_queries"], 2)
        self.assertGreater(fused[0]["score"], fused[1]["score"])


if __name__ == "__main__":
    unittest.main()
