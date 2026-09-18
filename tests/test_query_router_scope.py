from __future__ import annotations

import unittest

from rag_server.query_router import route_query, suggest_structured_label


class QueryRouterScopeTests(unittest.TestCase):
    def test_project_ov2_smoke_query_routes_to_project_ov2(self):
        d = route_query("противодымная вентиляция ОВ2")
        self.assertEqual(d.route, "project_ov2")
        self.assertEqual(d.dataset, "project")
        self.assertEqual(d.folder_filter, "ОВ2")
        self.assertFalse(d.ambiguous)

    def test_normative_fire_query_routes_to_normative(self):
        d = route_query("Где нужна противодымная вентиляция по СП 7.13130")
        self.assertEqual(d.route, "normative_fire")
        self.assertEqual(d.dataset, "normative")

    def test_hvac_query_routes_to_normative_hvac(self):
        d = route_query("роторный рекуператор утилизация теплоты СП 60")
        self.assertEqual(d.route, "normative_hvac")
        self.assertEqual(d.dataset, "normative")

    def test_structured_query_sets_structured_flag_and_project_scope(self):
        d = route_query("параметр настройки систем ОВ2")
        self.assertTrue(d.structured)
        self.assertEqual(d.dataset, "project")
        self.assertEqual(d.folder_filter, "ОВ2")
        self.assertEqual(d.structured_label, "Параметр настройки")

    def test_plain_words_for_smoke_control_reach_the_fire_domain(self):
        """An engineer asks for "удаление дыма", not for "противодымная".

        The vocabulary only held the technical stems, so the two most basic
        smoke-control questions in the golden set scored zero, fell to the
        default route, and were searched without a dataset and without query
        expansion.
        """
        for query in (
            "в каких случаях нужно предусматривать удаление дыма из коридоров",
            "когда можно не делать систему удаления продуктов горения",
        ):
            d = route_query(query)
            self.assertEqual(d.route, "normative_fire", query)
            self.assertEqual(d.inferred_dataset, "normative", query)

    def test_fire_alarm_query_routes_to_its_own_domain(self):
        d = route_query("где обязательно ставить извещатели и оповещение о пожаре")
        self.assertEqual(d.route, "normative_fire_alarm")
        self.assertEqual(d.inferred_dataset, "normative")

    def test_accessibility_query_is_routed_at_all(self):
        d = route_query("требования к перемещению людей с ограниченной подвижностью в здании")
        self.assertEqual(d.route, "normative_accessibility")
        self.assertEqual(d.inferred_dataset, "normative")

    def test_a_structured_hint_does_not_decide_where_to_look(self):
        """"Расход" is a table word, not a project word.

        structured_table exists to suggest extract_structured_values. It also
        carried dataset: project, so "как определяется расход приточного воздуха
        в помещении" — a question about a norm — was searched inside the project
        dataset only.
        """
        d = route_query("как определяется расход приточного воздуха в помещении")
        self.assertTrue(d.structured)
        self.assertNotEqual(d.inferred_dataset, "project")

    def test_our_object_is_a_project_question(self):
        """The possessive is the whole signal: the answer is in the project."""
        d = route_query("расчёт воздухообмена по нашему объекту")
        self.assertEqual(d.inferred_dataset, "project")

    def test_a_scopeless_domain_still_reports_its_hint(self):
        d = route_query("параметр настройки")
        self.assertTrue(d.structured)
        self.assertEqual(d.structured_label, "Параметр настройки")

    def test_saying_in_the_norms_scopes_the_search(self):
        """«В проекте» was wired and «в нормативах» was not.

        Asking for scope in words is the cheapest correct answer available: no
        reindexing, no guessing from vocabulary that lives in both halves of the
        corpus. Measured on the live index, «завеса воздушная водяная
        количество спецификация» returns no project documents at all, and the
        same query prefixed with «в проекте» returns four of five.
        """
        for query in (
            "найди в нормативах требования к воздушным завесам",
            "по нормативам какая должна быть завеса",
            "что говорят нормы про воздушные завесы",
        ):
            decision = route_query(query)
            self.assertEqual(decision.inferred_dataset, "normative", query)

    def test_saying_in_the_project_still_scopes_the_other_way(self):
        for query in ("посмотри в проекте Приморск завеса воздушная количество",
                      "в проекте резервирование вентиляции"):
            decision = route_query(query)
            self.assertEqual(decision.inferred_dataset, "project", query)

    def test_an_asked_for_scope_beats_the_subject_vocabulary(self):
        """«Вентиляция» pulls towards the norms; the asked-for scope must win."""
        decision = route_query("в проекте вентиляция кратность воздухообмена")
        self.assertEqual(decision.inferred_dataset, "project")

    def test_explicit_dataset_is_not_overridden(self):
        d = route_query("противодымная вентиляция ОВ2", explicit_dataset="normative")
        self.assertEqual(d.dataset, "normative")

    def test_explicit_folder_filter_is_not_overridden(self):
        d = route_query("СП 7.13130 противодымная вентиляция", explicit_folder_filter="ОВ2")
        self.assertEqual(d.folder_filter, "ОВ2")

    def test_cross_dataset_conflict_is_ambiguous_and_does_not_force_a_side(self):
        d = route_query("ОВ2 СП 7.13130 противодымная вентиляция")
        self.assertTrue(d.ambiguous)
        # neither side is forced: no aggressive folder filter, dataset not biased
        self.assertIsNone(d.folder_filter)
        self.assertIsNone(d.dataset)

    def test_no_match_returns_default(self):
        d = route_query("случайный запрос без доменных терминов")
        self.assertEqual(d.route, "default")
        self.assertIsNone(d.dataset)
        self.assertIsNone(d.folder_filter)
        self.assertFalse(d.ambiguous)

    def test_yo_and_case_normalization(self):
        # 'ё' normalized to 'е', case-insensitive
        d = route_query("УТИЛИЗАЦИЯ ТЕПЛОТЫ рекуператёр СП 60")
        self.assertEqual(d.dataset, "normative")

    def test_short_token_does_not_match_inside_a_word(self):
        # Regression: 'вк' must NOT match inside 'установки' and mis-route to project_vk
        # (this emptied results for "теплоутилизатор приточной установки").
        d = route_query("теплоутилизатор приточной установки", explicit_dataset="normative")
        self.assertNotEqual(d.route, "project_vk")
        self.assertIsNone(d.folder_filter)

    def test_vk_still_matches_as_whole_token(self):
        d = route_query("водоснабжение и канализация ВК")
        self.assertEqual(d.route, "project_vk")
        self.assertEqual(d.folder_filter, "ВК")

    def test_pa_unit_does_not_match_inside_word(self):
        # 'па' (structured unit) must not trigger on 'папка'/'аппарат'
        d = route_query("монтаж аппарата без таблиц")
        self.assertFalse(d.structured)

    def test_suggest_structured_label(self):
        self.assertEqual(suggest_structured_label("параметр настройки ОВ2"), "Параметр настройки")
        self.assertEqual(suggest_structured_label("потеря давления в системе"), "Потеря давления")
        self.assertEqual(suggest_structured_label("падение давления"), "Падение давления")
        self.assertIsNone(suggest_structured_label("просто текст"))


if __name__ == "__main__":
    unittest.main()
