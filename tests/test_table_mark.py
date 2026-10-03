"""`mark` is a model or grade, not whatever sits under a header containing «тип».

On the live table cache, numeric marks came from «электродвигатель тип, В»
(230 — the supply voltage), «Ln,t,r,0 для перекрытий типов N 1 …, дБ» (a noise
level) and «Типоразмер». Matching «тип» as a substring put them there.
"""
from __future__ import annotations

import unittest

from rag_server import table_query as tq


class MarkHeaderTests(unittest.TestCase):
    def _field(self, header):
        return tq._map_columns([header])[0]

    def test_real_mark_columns(self):
        for header in ("Марка", "Тип", "Тип, марка, обозначение документа, опросного листа",
                       "Тип корпуса", "Тип\nустановки", "Модель", "Марка камня"):
            self.assertEqual(self._field(header), "mark", header)

    def test_columns_that_only_mention_a_type(self):
        for header in ("электродвигатель тип, В", "Типоразмер",
                       "Ln,t,r,0 для перекрытий типов N 1 и N 2 по ГОСТ Р ИСО 10140-5-2012, дБ",
                       "Мощность (тип), кВт"):
            self.assertNotEqual(self._field(header), "mark", header)

    def test_a_cached_mark_from_a_wrong_column_is_dropped(self):
        row = {"name": "Вентилятор", "mark": "230",
               "raw_row": {"Наименование": "Вентилятор", "электродвигатель тип, в": "230"}}
        self.assertNotIn("mark", tq._repair_mark(row))

    def test_a_cached_mark_from_a_mark_column_is_kept(self):
        row = {"name": "Вентилятор", "mark": "ВКР-5",
               "raw_row": {"Наименование": "Вентилятор",
                           "Тип, марка, обозначение документа, опросного листа": "ВКР-5"}}
        self.assertEqual(tq._repair_mark(row)["mark"], "ВКР-5")


if __name__ == "__main__":
    unittest.main()
