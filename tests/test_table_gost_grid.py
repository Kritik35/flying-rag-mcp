"""Ведомости по ГОСТ 21.110 не разбираются: одна шапка вместо ярусов, одна
таблица вместо секций.

Взято с живого листа `АТ-РД-ОВ3-С-00-10.02-02.pdf`. На странице три таблицы,
нужная — вторая, 62 строки. Её устройство:

    0   «Воздушно-тепловые завесы»            заголовок секции, объединённая ячейка
    1   Обозначение | Кол. | Наименование | Тип | Вентилятор | Электродвигатель …
    2                                          | Исп. по взрывозащите | L м3/ч | Тип, В | N, кВт …
    3                                                                        от | до | от | до
    4   1 | 2 | 3 | 4 | 5 | …                  нумерация колонок, требуемая ГОСТ
    5+  А-01.1.5.1 | 1 | Паркинг | Volcano VR Mini AC | …    ← агрегаты
    45+ У-02.8.1   | 1 | Разгрузочная | КЭВ-200П512W | …     ← завесы

Разбор берёт одну строку за шапку и всё ниже за данные. Отсюда на живом
корпусе: `sum_table_values(subject='КЭВ', op='count')` отвечает 17 (позиций
тринадцать) и возвращает 17 строк, в которых нет ни одного поля кроме
`_source` — и всё это со статусом VERIFIED. `subject='Volcano'` не находит
ничего, хотя агрегатов сорок.

На .xlsx-спецификациях с одной шапкой разбор работает и ломать его нельзя:
эталон в `scripts/table_baseline.py` (воздуховод sum=99803.97 по 5103 строкам).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from rag_server.table_query import _rows_from_grid

# Так выглядит шапка в .xlsx-спецификациях, которые разбираются сегодня:
# «Кол-во» распознаётся, а ГОСТовское сокращение «Кол.» — нет, и это одна из
# причин, по которым ведомость на листе не читается.
SIMPLE = [
    ["Поз.", "Наименование", "Ед. изм.", "Кол-во"],
    ["1", "Воздуховод 300x400", "м", "30,5"],
    ["2", "Отвод 90° 300x400", "шт.", "8"],
]

GOST = [
    ["Воздушно-тепловые завесы", None, None, None, None, None],
    ["Обозна-\nчение", "Кол.", "Наименование обслуживаемого помещения",
     "Тип\n(наименование)", "Вентилятор", "Воздухонагреватель"],
    [None, None, None, None, "L\nм3/ч", "Расход\nтеплоты,\nкВт"],
    ["1", "2", "3", "4", "5", "6"],
    ["У-02.8.1", "1", "Разгрузочная 2.01.16.035", "КЭВ-200П512W", "10000", "103,3"],
    ["У-01.2.5", "1", "Рампа 1.01.01.105", "КЭВ-125П5050W", "6300", "58,2"],
]

TWO_SECTIONS = [
    ["Отопительные агрегаты", None, None, None],
    ["Обозначение", "Кол.", "Тип", "Расход теплоты, кВт"],
    ["1", "2", "3", "4"],
    ["А-01.1.5.1", "1", "Volcano VR Mini AC", "27,93"],
    ["А-01.1.5.2", "1", "Volcano VR Mini AC", "27,93"],
    ["Воздушно-тепловые завесы", None, None, None],
    ["Обозначение", "Кол.", "Тип", "Расход теплоты, кВт"],
    ["1", "2", "3", "4"],
    ["У-02.8.1", "1", "КЭВ-200П512W", "103,3"],
    ["У-01.2.5", "1", "КЭВ-125П5050W", "58,2"],
]


class SingleHeaderStillWorksTests(unittest.TestCase):
    """То, что работает на xlsx, обязано продолжать работать."""

    def test_a_plain_specification_is_parsed(self):
        rows = _rows_from_grid([list(r) for r in SIMPLE])

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].get("name"), "Воздуховод 300x400")
        self.assertEqual(rows[0].get("qty"), 30.5)
        self.assertEqual(rows[1].get("qty"), 8.0)


class MultiTierHeaderTests(unittest.TestCase):
    def test_the_column_numbering_row_is_not_data(self):
        """Строка «1 | 2 | 3 | 4» — требование ГОСТ к оформлению, не позиция."""
        rows = _rows_from_grid([list(r) for r in GOST])

        names = [r.get("name") or r.get("pos") or "" for r in rows]
        self.assertNotIn("1", names)
        self.assertEqual(len(rows), 2)

    def test_the_equipment_rows_keep_their_fields(self):
        rows = _rows_from_grid([list(r) for r in GOST])

        first = rows[0]
        self.assertEqual(first.get("pos"), "У-02.8.1")
        self.assertEqual(first.get("qty"), 1.0)
        self.assertIn("КЭВ-200П512W", " ".join(str(v) for v in first.values()))

    def test_a_row_is_never_returned_empty(self):
        """17 строк без единого поля кроме `_source` — это мусор со статусом
        VERIFIED, и он опаснее честного отказа."""
        rows = _rows_from_grid([list(r) for r in GOST])

        for row in rows:
            fields = [k for k in row if k not in ("raw_row", "_source")]
            self.assertTrue(fields, row)


class SectionTests(unittest.TestCase):
    def test_rows_carry_the_section_they_belong_to(self):
        rows = _rows_from_grid([list(r) for r in TWO_SECTIONS])

        by_section = {}
        for row in rows:
            by_section.setdefault(row.get("section"), []).append(row)

        self.assertIn("Отопительные агрегаты", by_section)
        self.assertIn("Воздушно-тепловые завесы", by_section)
        self.assertEqual(len(by_section["Отопительные агрегаты"]), 2)
        self.assertEqual(len(by_section["Воздушно-тепловые завесы"]), 2)

    def test_a_section_title_is_not_itself_a_row(self):
        rows = _rows_from_grid([list(r) for r in TWO_SECTIONS])

        self.assertEqual(len(rows), 4)

    def test_the_second_section_is_parsed_with_its_own_header(self):
        rows = _rows_from_grid([list(r) for r in TWO_SECTIONS])
        curtains = [r for r in rows if r.get("section") == "Воздушно-тепловые завесы"]

        self.assertEqual({r.get("qty") for r in curtains}, {1.0})
        self.assertEqual(len(curtains), 2)


class OneFilePerDocumentTests(unittest.TestCase):
    """Спецификация лежит в корпусе и как .xlsx, и как .pdf одного документа.

    Складывая обе, инструмент удваивал ответ: по ОВ2-С-00-СО выходило
    169 214 при верных 81 511 — и удваивал молча, показывая оба файла в
    `sources`. Предпочтение у формата, где таблица хранится ячейками: разбор
    .xlsx совпал с независимым подсчётом по openpyxl до копейки (4149 строк,
    81 511.01), тот же документ в .pdf разъезжается на 4863 строки.
    """

    def test_a_document_in_two_formats_is_counted_once(self):
        from rag_server.table_query import _one_file_per_document

        kept = _one_file_per_document([
            r"C:\corpus\АТ-РД-ОВ2-С-00-СО-06.pdf",
            r"C:\corpus\АТ-РД-ОВ2-С-00-СО-06.xlsx",
        ])

        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].endswith(".xlsx"))

    def test_a_numbered_copy_is_the_same_document(self):
        from rag_server.table_query import _one_file_per_document

        kept = _one_file_per_document([
            r"C:\corpus\ведомость.xlsx",
            r"C:\corpus\ведомость (1).xlsx",
        ])

        self.assertEqual(len(kept), 1)

    def test_different_documents_are_all_kept(self):
        from rag_server.table_query import _one_file_per_document

        kept = _one_file_per_document([
            r"C:\corpus\ОВ2-СО.xlsx",
            r"C:\corpus\ОВ3-СО.xlsx",
            r"C:\corpus\ОВ4-СО.pdf",
        ])

        self.assertEqual(len(kept), 3)

    def test_the_first_seen_order_is_preserved(self):
        from rag_server.table_query import _one_file_per_document

        kept = _one_file_per_document([
            r"C:\corpus\б.xlsx", r"C:\corpus\а.xlsx",
        ])

        self.assertEqual([Path(f).stem for f in kept], ["б", "а"])


if __name__ == "__main__":
    unittest.main()
