"""Quantities in different units are not added together.

`sum_table_values(subject="воздуховод")` on a ventilation specification
matched both duct runs in metres and branch fittings in pieces, added the
metres to the pieces and returned the result as VERIFIED. A quantity total is
an answer only within one unit; across several it is a breakdown.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from openpyxl import Workbook

from rag_server import table_query


def _spec(path: str, rows: list[tuple]) -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(["Поз.", "Наименование", "Ед. изм.", "Кол-во", "Сумма"])
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = table_query._resolve_files

    def tearDown(self):
        table_query._resolve_files = self._orig

    def _use(self, rows):
        path = _spec(os.path.join(self.tmp, f"spec{len(os.listdir(self.tmp))}.xlsx"), rows)
        table_query._resolve_files = lambda *a, **k: ([path], [])

    def test_metres_and_pieces_are_reported_separately(self):
        self._use([("1", "Воздуховод 1000x1800", "м", 61.27, 0),
                   ("2", "Воздуховод 600x1500", "м.", 37.1, 0),
                   ("3", "Врезка воздуховода 1000x1800", "шт.", 2, 0)])

        result = table_query.sum_table_values(subject="воздуховод")

        self.assertEqual(result["status"], "MIXED_UNITS")
        self.assertNotIn("total", result)
        by_unit = result["totals_by_unit"]
        self.assertAlmostEqual(by_unit["м"]["total"], 98.37, places=6)
        self.assertEqual(by_unit["м"]["count"], 2)
        self.assertEqual(by_unit["шт"]["total"], 2.0)

    def test_one_unit_spelled_several_ways_is_one_unit(self):
        self._use([("1", "Кабель ВВГ", "м", 10, 0),
                   ("2", "Кабель ВВГ", "п.м.", 5, 0),
                   ("3", "Кабель ВВГ", "М", 1, 0)])

        result = table_query.sum_table_values(subject="кабель")

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["unit"], "м")
        self.assertEqual(result["total"], 16.0)

    def test_a_row_without_a_unit_is_not_silently_merged(self):
        self._use([("1", "Кабель ВВГ", "м", 10, 0),
                   ("2", "Кабель ВВГ", "", 5, 0)])

        result = table_query.sum_table_values(subject="кабель")

        self.assertEqual(result["status"], "MIXED_UNITS")
        self.assertIn("", result["totals_by_unit"])

    def test_money_is_summed_regardless_of_the_quantity_unit(self):
        self._use([("1", "Воздуховод", "м", 3, 100),
                   ("2", "Врезка воздуховода", "шт.", 1, 50)])

        result = table_query.sum_table_values(subject="воздуховод", field="amount")

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["total"], 150.0)

    def test_normalisation(self):
        norm = table_query.normalise_unit
        self.assertEqual(norm("м²"), "м2")
        self.assertEqual(norm("кв. м"), "м2")
        self.assertEqual(norm("м3"), "м3")
        self.assertEqual(norm("куб.м"), "м3")
        self.assertEqual(norm("Шт"), "шт")
        self.assertEqual(norm("компл."), "компл")
        self.assertEqual(norm("к-т"), "компл")
        self.assertEqual(norm(" кг "), "кг")
        self.assertEqual(norm(None), "")


if __name__ == "__main__":
    unittest.main()
