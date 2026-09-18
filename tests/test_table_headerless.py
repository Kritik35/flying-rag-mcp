"""Двенадцать таблиц из пятидесяти пяти разбирались в ноль строк.

Флаг `PARTIAL` из предыдущей правки показал то, что было невидимо: 22%
проиндексированных xlsx не дают ни одной строки. Среди них не мелочь —
`PR-RD-HV1-С-00-СО-03.xlsx`, сводная спецификация оборудования ОВ1, и
`PR-RD-HV2-С-00-СО (ПДВ).xlsx` с 4001 непустой строкой, из которых половина
про воздуховоды. Ни одна их позиция не попадала ни в один итог.

Причин две, и обе в том, где разбор ищет шапку.

**Шапки нет вовсе.** Сводные спецификации выгружаются из подбора без строки
заголовков: с нулевой строки идут данные, колонки только позиционные —
наименование, тип, артикул, поставщик, единица, количество. Разбор требовал
шапку, не находил и возвращал пустоту. Колонки теперь определяются по
содержимому: колонка единиц узнаётся по словам «шт.», «м», «м²»; количество —
число справа от неё; наименование — самая длинная текстовая колонка. Это
вывод из данных, а не из позиции, и каждый признак проверяем.

**Нумерация колонок с пропусками.** ГОСТ требует строку «1 | 2 | 3 | …», и она
служит границей шапки. Но лист `10.05,10.06_ХОВС ПДВ` сделан из шаблона, из
которого удалили колонки, и нумерация в нём «1 2 3 4 7 9 10 11 12». Проверка
требовала строгого ряда подряд и границу не находила.
"""
from __future__ import annotations

import unittest

from rag_server.table_query import _is_numbering_row, _rows_from_grid


# Как в `PR-RD-HV1-С-00-СО-03.xlsx`: данные с нулевой строки, шапки нет.
HEADERLESS = [
    ["", "RJIP Standard кран шаровой", "RJIP Standard", "065N9626R", "Ридан", "шт.", "10", "8,4"],
    ["", "Автоматический воздухоотводчик", "Airvent-R", "065B8323R", "Ридан", "шт.", "227", None],
    ["", "Болт оцинкованный М12", "ГОСТ 7798-70", None, None, "шт.", "304", None],
    ["", "Клапан балансировочный", "MVT-R", "003Z4041R", "Ридан", "шт.", "6", "0,57"],
]

# Как в `PR-RD-HV2-С-00-СО (ПДВ).xlsx`: заголовок раздела, затем данные.
HEADERLESS_WITH_SECTIONS = [
    ["Воздухозабор ВЗ-2-3-ОВ", None, None, None, None, None, None],
    ["", "Воздуховод из тонколистовой стали", "ГОСТ 14918-80*", None, None, "м", "25,55"],
    ["", "Отвод из оцинкованной стали", "ГОСТ 14918-80*", None, None, "шт.", "2"],
    ["Воздухозабор ВЗ-3-1-ОВ", None, None, None, None, None, None],
    ["", "Воздуховод из тонколистовой стали", "ГОСТ 14918-80*", None, None, "м", "8,72"],
]

# Нумерация после удаления колонок из шаблона.
GAPPED = [
    ["Характеристика систем", None, None, None, None],
    ["Обозначение системы", "Кол. систем", "Наименование", "Тип установки", "Расход"],
    ["1", "2", "4", "7", "9"],
    ["ДВ1-PAR-1-1.1", "1", "Стоянка автомобилей", "Радиальный", "58200"],
    ["ДВ1-PAR-1-1.2", "1", "Стоянка автомобилей", "Радиальный", "58200"],
]


class NumberingRowTests(unittest.TestCase):
    def test_a_consecutive_row_is_numbering(self):
        self.assertTrue(_is_numbering_row(["1", "2", "3", "4"]))

    def test_gaps_do_not_stop_it_being_numbering(self):
        """Колонки удалили из шаблона — номера остались прежними."""
        self.assertTrue(_is_numbering_row(["1", "2", "3", "4", "7", "9", "10"]))

    def test_it_must_still_start_at_one_and_rise(self):
        self.assertFalse(_is_numbering_row(["2", "3", "4"]))
        self.assertFalse(_is_numbering_row(["1", "3", "2"]))

    def test_a_row_of_quantities_is_not_numbering(self):
        self.assertFalse(_is_numbering_row(["10", "227", "304"]))
        self.assertFalse(_is_numbering_row(["1", "1", "1"]))

    def test_text_is_never_numbering(self):
        self.assertFalse(_is_numbering_row(["1", "2", "Наименование"]))


class GappedNumberingTests(unittest.TestCase):
    def test_the_sheet_parses_now(self):
        rows = _rows_from_grid([list(r) for r in GAPPED])

        self.assertEqual(len(rows), 2)

    def test_the_numbering_row_is_not_a_position(self):
        rows = _rows_from_grid([list(r) for r in GAPPED])

        self.assertNotIn("1", [r.get("pos") for r in rows])


class HeaderlessTests(unittest.TestCase):
    def test_every_data_row_is_returned(self):
        rows = _rows_from_grid([list(r) for r in HEADERLESS])

        self.assertEqual(len(rows), 4)

    def test_the_quantity_is_the_number_beside_the_unit(self):
        rows = _rows_from_grid([list(r) for r in HEADERLESS])

        self.assertEqual([r.get("qty") for r in rows], [10.0, 227.0, 304.0, 6.0])

    def test_the_unit_is_read(self):
        rows = _rows_from_grid([list(r) for r in HEADERLESS])

        self.assertEqual({r.get("unit") for r in rows}, {"шт."})

    def test_the_name_is_the_longest_text_column(self):
        rows = _rows_from_grid([list(r) for r in HEADERLESS])

        self.assertEqual(rows[0].get("name"), "RJIP Standard кран шаровой")
        self.assertEqual(rows[2].get("name"), "Болт оцинкованный М12")

    def test_a_section_title_is_not_a_position(self):
        rows = _rows_from_grid([list(r) for r in HEADERLESS_WITH_SECTIONS])

        self.assertEqual(len(rows), 3)
        self.assertNotIn("Воздухозабор ВЗ-2-3-ОВ", [r.get("name") for r in rows])

    def test_the_decimal_comma_is_read(self):
        rows = _rows_from_grid([list(r) for r in HEADERLESS_WITH_SECTIONS])

        self.assertEqual(rows[0].get("qty"), 25.55)

    def test_one_long_stray_cell_does_not_become_the_name_column(self):
        """На живом листе ПДВ так и вышло: в col_0 одна ячейка длиной 100
        знаков дала среднюю длину выше, чем 3824 настоящих наименования в
        col_1, и наименование пропало из всех строк. Колонка наименований
        заполнена почти в каждой позиции — стрелять средним по одной ячейке
        нельзя."""
        grid = [
            ["Одна очень длинная случайная подпись под таблицей на сто знаков",
             "Воздуховод из оцинкованной стали 300x400", "ГОСТ 14918-80*", "м", "25,55"],
            [None, "Отвод из оцинкованной стали 30°", "ГОСТ 14918-80*", "шт.", "2"],
            [None, "Отвод из оцинкованной стали 45°", "ГОСТ 14918-80*", "шт.", "6"],
            [None, "Заглушка прямоугольная", "ГОСТ 14918-80*", "шт.", "1"],
        ]

        rows = _rows_from_grid([list(r) for r in grid])

        self.assertEqual(len([r for r in rows if r.get("name")]), len(rows))
        self.assertEqual(rows[1].get("name"), "Отвод из оцинкованной стали 30°")

    def test_a_row_is_never_returned_empty(self):
        for grid in (HEADERLESS, HEADERLESS_WITH_SECTIONS):
            for row in _rows_from_grid([list(r) for r in grid]):
                fields = [k for k in row if k not in ("raw_row", "_source")]
                self.assertTrue(fields, row)


if __name__ == "__main__":
    unittest.main()
