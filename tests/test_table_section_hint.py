"""«Сколько завес» не находит ничего — и молчит о том, что раздел с таким
названием на листе есть.

Лист PR-RD-HV3-С-00-10.02 устроен так, что заголовок у двух блоков один:
«Воздушно-тепловые завесы», а под ним идут сорок отопительных агрегатов
(Voicano) и семнадцать завес (КЭВ) подряд, без второго заголовка. Считать по
метке раздела нельзя — получится 57 при семнадцати, и это уже проверено
(см. `_row_text`, метка исключена намеренно).

Но и нынешний ответ «no rows matched» неверен по смыслу: раздел есть, строки
под ним есть, и человек, спросивший про завесы, остаётся ни с чем. Число не
выдумывается: возвращается подсказка — сколько строк под таким разделом и
какие марки в них встречаются, чтобы следующий запрос был по марке.
"""
from __future__ import annotations

import unittest

from rag_server.table_query import _section_near_miss


ROWS = [
    {"pos": "А-01.1.5.1", "name": "Паркинг", "section": "Воздушно-тепловые завесы",
     "raw_row": {"тип (наименование )": "Voicano VR Mini AC", "кол.": "1"}},
    {"pos": "А-01.1.5.2", "name": "Паркинг", "section": "Воздушно-тепловые завесы",
     "raw_row": {"тип (наименование )": "Voicano VR Mini AC", "кол.": "1"}},
    {"pos": "У-02.8.1", "name": "Разгрузочная", "section": "Воздушно-тепловые завесы",
     "raw_row": {"тип (наименование )": "КЭВ-200П512W", "кол.": "1"}},
    {"pos": "1", "name": "Воздуховод 300x400", "section": "Спецификация",
     "raw_row": {"наименование": "Воздуховод 300x400"}},
]


class SectionNearMissTests(unittest.TestCase):
    def test_a_matching_section_is_reported_with_its_size(self):
        hint = _section_near_miss(ROWS, ["завес"], "лист.pdf")

        self.assertEqual(len(hint), 1)
        self.assertEqual(hint[0]["section"], "Воздушно-тепловые завесы")
        self.assertEqual(hint[0]["rows"], 3)
        self.assertEqual(hint[0]["file"], "лист.pdf")

    def test_the_marks_under_it_are_listed_so_a_follow_up_is_possible(self):
        hint = _section_near_miss(ROWS, ["завес"], "лист.pdf")

        self.assertEqual(sorted(hint[0]["marks"]),
                         ["Voicano VR Mini AC", "КЭВ-200П512W"])

    def test_no_number_is_offered_as_an_answer(self):
        """Метка раздела покрывает и агрегаты, и завесы: 3 здесь — не ответ."""
        hint = _section_near_miss(ROWS, ["завес"], "лист.pdf")

        self.assertNotIn("count", hint[0])
        self.assertNotIn("total", hint[0])

    def test_an_unrelated_subject_gets_no_hint(self):
        self.assertEqual(_section_near_miss(ROWS, ["насос"], "лист.pdf"), [])

    def test_every_keyword_must_be_in_the_section(self):
        self.assertEqual(
            _section_near_miss(ROWS, ["завес", "электрическая"], "лист.pdf"), [])

    def test_rows_without_a_section_are_ignored(self):
        rows = [{"name": "Завеса воздушная", "raw_row": {}}]
        self.assertEqual(_section_near_miss(rows, ["завес"], "лист.pdf"), [])


if __name__ == "__main__":
    unittest.main()
