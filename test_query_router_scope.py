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
        d = route_query("дорегулирование систем ОВ2")
        self.assertTrue(d.structured)
        self.assertEqual(d.dataset, "project")
        self.assertEqual(d.folder_filter, "ОВ2")
        self.assertEqual(d.structured_label, "Дорегулирование")

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
        self.assertEqual(suggest_structured_label("дорегулирование ОВ2"), "Дорегулирование")
        self.assertEqual(suggest_structured_label("потеря давления в системе"), "Потеря давления")
        self.assertEqual(suggest_structured_label("падение давления"), "Падение давления")
        self.assertIsNone(suggest_structured_label("просто текст"))


if __name__ == "__main__":
    unittest.main()
