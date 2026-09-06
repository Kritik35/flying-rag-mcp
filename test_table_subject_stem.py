"""Предмет запроса склоняется, а строки таблицы — нет.

`sum_table_values(subject='завеса')` не находил ничего в разделе
«Воздушно-тепловые завесы»: сравнение подстрочное, и «завеса» не входит в
«завесы». При этом «воздуховод» работал — потому что в русском окончание
дописывается справа, и корень запроса уже является началом словоформы в тексте.

Отсюда правка минимальная и намеренно односторонняя: окончание срезается
только у слова из запроса, текст строки не трогается. «Завеса» превращается в
«завес» и находит «завесы», «завесу», «завес»; «воздуховод» и «клапан» не
меняются вовсе, поэтому уже проверенные итоги остаются прежними
(`scripts/table_baseline.py`: 4149 строк, 81 511.01).
"""
from __future__ import annotations

import unittest

from rag_server.table_query import _row_matches, _subject_stem


class SubjectStemTests(unittest.TestCase):
    def test_a_feminine_ending_is_dropped(self):
        self.assertEqual(_subject_stem("завеса"), "завес")

    def test_words_that_already_work_are_left_alone(self):
        """Иначе сдвинутся итоги, которые сверены с openpyxl до копейки."""
        for word in ("воздуховод", "клапан", "отвод", "переход"):
            self.assertEqual(_subject_stem(word), word)

    def test_a_short_word_is_never_cut(self):
        for word in ("вал", "узел", "бак"):
            self.assertEqual(_subject_stem(word), word)

    def test_latin_and_codes_are_left_alone(self):
        self.assertEqual(_subject_stem("Volcano"), "volcano")
        self.assertEqual(_subject_stem("КЭВ-200П512W"), "кэв-200п512w")


class RowMatchingTests(unittest.TestCase):
    def _row(self, text: str) -> dict:
        return {"name": text, "raw_row": {}}

    def test_the_singular_finds_the_plural(self):
        self.assertTrue(_row_matches(self._row("Воздушно-тепловые завесы"),
                                     [_subject_stem("завеса")]))

    def test_the_declined_forms_are_found_too(self):
        for form in ("завесу", "завесой", "завес"):
            self.assertTrue(
                _row_matches(self._row(f"Установка {form} над проёмом"),
                             [_subject_stem("завеса")]), form)

    def test_an_unrelated_word_still_does_not_match(self):
        self.assertFalse(_row_matches(self._row("Клапан противопожарный"),
                                      [_subject_stem("завеса")]))

    def test_the_previously_working_subjects_still_match(self):
        self.assertTrue(_row_matches(
            self._row("Воздуховод из тонколистовой оцинкованной стали 300x400"),
            [_subject_stem("воздуховод")]))
        self.assertTrue(_row_matches(
            self._row("Клапан противопожарный нормально открытый"),
            [_subject_stem("клапан")]))

    def test_every_keyword_must_still_be_present(self):
        row = self._row("Воздушно-тепловые завесы")
        self.assertFalse(_row_matches(row, [_subject_stem("завеса"), "электрическая"]))


if __name__ == "__main__":
    unittest.main()
