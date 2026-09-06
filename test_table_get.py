"""Инструментов, отвечающих числом, было два; инструмента, показывающего саму
таблицу, не было ни одного.

В 67 записанных диалогах табличные инструменты не позвали ни разу: модель
открывала PDF через fitz и переписывала строки в Python. Ей нужна была не
сумма, а все строки листа со всеми колонками — чтобы разделить их самой.

Отсюда `get_table`: он отдаёт разобранный лист как есть. И он же снимает
вопрос с разделами, на котором споткнулся счёт по метке: на листе 10.02 один
заголовок «Воздушно-тепловые завесы» стоит над сорока агрегатами и семнадцатью
завесами. Считать по нему нельзя, а вот `group_by="тип"` даёт разбивку по
колонке «Тип (наименование)» — и это по-прежнему счёт в Python, не в модели.
"""
from __future__ import annotations

import unittest

from rag_server.table_query import _columns_signature, _group_rows_by_columns, _pick_group_column


SPEC = [
    {"pos": "1", "name": "Воздуховод 300x400", "qty": 30.5,
     "raw_row": {"поз.": "1", "наименование": "Воздуховод 300x400", "кол-во": "30,5"}},
    {"pos": "2", "name": "Отвод 90°", "qty": 8.0,
     "raw_row": {"поз.": "1", "наименование": "Отвод 90°", "кол-во": "8"}},
]

SHEET = [
    {"pos": "А-01.1.5.1", "section": "Воздушно-тепловые завесы",
     "raw_row": {"обозначение": "А-01.1.5.1", "тип (наименование )": "Voicano VR Mini AC"}},
    {"pos": "А-01.1.5.2", "section": "Воздушно-тепловые завесы",
     "raw_row": {"обозначение": "А-01.1.5.2", "тип (наименование )": "Voicano VR Mini AC"}},
    {"pos": "У-02.8.1", "section": "Воздушно-тепловые завесы",
     "raw_row": {"обозначение": "У-02.8.1", "тип (наименование )": "КЭВ-200П512W"}},
    # Строка из штампа того же листа: другая таблица, другие колонки.
    {"pos": "Заказчик: ...", "raw_row": {"№ изм.": "Заказчик: ...", "дата": None}},
]


class ColumnSignatureTests(unittest.TestCase):
    """Разные таблицы одного листа различаются набором колонок, а не догадкой."""

    def test_rows_of_one_table_share_a_signature(self):
        self.assertEqual(_columns_signature(SPEC[0]), _columns_signature(SPEC[1]))

    def test_the_title_block_is_a_different_table(self):
        self.assertNotEqual(_columns_signature(SHEET[0]), _columns_signature(SHEET[3]))

    def test_the_biggest_table_comes_first(self):
        groups = _group_rows_by_columns(SHEET)

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]["rows"]), 3)
        self.assertEqual(groups[0]["columns"], ["обозначение", "тип (наименование )"])

    def test_a_plain_specification_stays_one_table(self):
        groups = _group_rows_by_columns(SPEC)

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["rows"]), 2)


class GroupColumnTests(unittest.TestCase):
    def test_a_column_is_found_by_part_of_its_header(self):
        self.assertEqual(_pick_group_column(SHEET[:3], "тип"), "тип (наименование )")

    def test_the_search_ignores_case(self):
        self.assertEqual(_pick_group_column(SHEET[:3], "ТИП"), "тип (наименование )")

    def test_an_unknown_column_is_reported_as_missing(self):
        self.assertIsNone(_pick_group_column(SHEET[:3], "давление"))


class GetTableShapeTests(unittest.TestCase):
    """Разбивка по колонке — это то, чем счёт по метке раздела быть не может."""

    def test_grouping_counts_each_distinct_value(self):
        from rag_server.table_query import _count_by_column

        counts = _count_by_column(SHEET[:3], "тип (наименование )")

        self.assertEqual(counts, {"Voicano VR Mini AC": 2, "КЭВ-200П512W": 1})

    def test_an_empty_value_is_not_a_group(self):
        from rag_server.table_query import _count_by_column

        rows = SHEET[:3] + [{"raw_row": {"тип (наименование )": ""}}]

        self.assertEqual(sum(_count_by_column(rows, "тип (наименование )").values()), 3)


if __name__ == "__main__":
    unittest.main()
