"""Two query shapes reach this system, and they need opposite things.

Taken from 191 real queries in the working history:

    R.L2.15.114
    1.02.11.024 1.02.11.025 1.02.11.026
    П1-TRF-01-01 ХОВС
    завеса воздушная водяная количество спецификация
    в каких случаях нужно предусматривать удаление дыма из коридоров

A question carries meaning, so the dense channel is the good signal. A room or
system code carries none — the embedder answers it with noise, and worse, a code
like «R.L2.15.114» looks like a norm designation, so that noise is confidently
normative. Only the lexical channel can match a code, and at alpha=0.7 it loses.

Measured before writing this, «1.02.11.024 1.02.11.025»: at alpha 0.7 none of
the top five contain the code, at alpha 0.3 four of five do. For «завеса
воздушная водяная количество спецификация»: no project documents at 0.7, four
of five at 0.3.
"""
from __future__ import annotations

import unittest

from rag_server.query_shape import exact_tokens, is_exact_query, lexical_alpha


class ExactTokenTests(unittest.TestCase):
    def test_a_room_code_is_exact(self):
        self.assertEqual(exact_tokens("R.L2.15.114"), ["R.L2.15.114"])

    def test_several_room_codes_are_all_kept(self):
        self.assertEqual(
            exact_tokens("1.02.11.024 1.02.11.025 1.02.11.026"),
            ["1.02.11.024", "1.02.11.025", "1.02.11.026"],
        )

    def test_a_system_tag_is_exact(self):
        self.assertEqual(exact_tokens("П1-TRF-01-01 ХОВС"), ["П1-TRF-01-01"])

    def test_a_sheet_code_is_exact(self):
        self.assertEqual(
            exact_tokens("PR-RD-HV4-С-00-П.02-02"), ["PR-RD-HV4-С-00-П.02-02"]
        )

    def test_a_norm_designation_is_exact(self):
        self.assertIn("СП 60.13330", exact_tokens("кратность воздухообмена СП 60.13330"))

    def test_an_equipment_id_is_exact(self):
        self.assertEqual(exact_tokens("холодильная камера 116.2 O01163"),
                         ["O01163"])

    def test_a_two_part_number_is_left_alone_on_purpose(self):
        """«116.2» is a position number and «18.5» is a temperature, and the
        two are structurally identical. Claiming the first would claim the
        second, and a false identifier turns an ordinary question into a
        lexical lookup — the expensive direction to be wrong in. Three groups
        or a letter glued to digits are unambiguous; two bare groups are not.
        """
        self.assertEqual(exact_tokens("позиция 116.2 холодильная камера"), [])
        self.assertEqual(exact_tokens("температура 18.5 градуса"), [])

    def test_a_plain_question_has_none(self):
        for query in (
            "в каких случаях нужно предусматривать удаление дыма из коридоров",
            "завеса воздушная водяная количество спецификация",
            "резервирование вентиляции резервный вентилятор",
        ):
            self.assertEqual(exact_tokens(query), [], query)

    def test_a_bare_measurement_is_not_an_identifier(self):
        """Otherwise "расход 60 м3/ч" would be treated as a lookup."""
        for query in ("расход 60 м3/ч на человека", "температура 18 градусов",
                      "не менее 30 процентов"):
            self.assertEqual(exact_tokens(query), [], query)

    def test_a_year_is_not_an_identifier(self):
        self.assertEqual(exact_tokens("изменения 2026 года"), [])


class QueryShapeTests(unittest.TestCase):
    def test_a_code_query_is_recognised(self):
        self.assertTrue(is_exact_query("R.L2.15.114"))
        self.assertTrue(is_exact_query("П1-TRF-01-01 ХОВС"))

    def test_a_question_is_not(self):
        self.assertFalse(
            is_exact_query("в каких случаях нужно предусматривать удаление дыма")
        )

    def test_a_question_that_merely_cites_a_norm_is_still_a_question(self):
        """«... СП 60.13330» is a hint about scope, not a lookup by identifier.

        The dense channel still carries the question; pushing it aside because a
        norm number appears would break exactly the queries that work today.
        """
        query = ("кратность воздухообмена помещения уборочного инвентаря ПУИ "
                 "санузлы венткамеры СП 60.13330 СП 118.13330")
        self.assertFalse(is_exact_query(query))


class AlphaTests(unittest.TestCase):
    def test_a_question_keeps_the_dense_leaning_default(self):
        self.assertAlmostEqual(
            lexical_alpha("в каких случаях нужно предусматривать удаление дыма",
                          default=0.7),
            0.7,
        )

    def test_a_code_query_leans_lexical(self):
        alpha = lexical_alpha("1.02.11.024 1.02.11.025", default=0.7)
        self.assertLess(alpha, 0.4)

    def test_the_caller_can_still_override(self):
        """An explicit alpha from the caller is a decision, not a suggestion."""
        self.assertAlmostEqual(
            lexical_alpha("R.L2.15.114", default=0.9, explicit=True), 0.9
        )


if __name__ == "__main__":
    unittest.main()
