"""get_table names its tables, pages through long ones, and says where a row is.

A reviewer could not continue past the first 200 rows, could not ask for the
second table of a file, and could not check a value against the source: rows
came without the table or line they were read from.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from openpyxl import Workbook

from rag_server import table_query


class GetTablePagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "Спецификация.xlsx")
        wb = Workbook()
        spec = wb.active
        spec.title = "Спец"
        spec.append(["Поз.", "Наименование", "Ед. изм.", "Кол-во"])
        for i in range(1, 26):
            spec.append([str(i), f"Воздуховод {i}", "м", i])
        rooms = wb.create_sheet("Помещения")
        rooms.append(["Номер", "Наименование помещения", "Площадь"])
        for i in range(1, 4):
            rooms.append([f"1.{i}", f"Помещение {i}", 10 * i])
        wb.save(self.path)
        self._orig_resolve = table_query._resolve_files
        self._orig_rows = table_query._rows_for_file
        table_query._resolve_files = lambda *a, **k: ([self.path], [])
        # Parse straight from the file: the parquet cache is not under test.
        table_query._rows_for_file = lambda fp: table_query._extract_rows(table_query.Path(fp))

    def tearDown(self):
        table_query._resolve_files = self._orig_resolve
        table_query._rows_for_file = self._orig_rows

    def test_pages_cover_the_table_without_gaps_or_repeats(self):
        first = table_query.get_table("Спецификация", max_rows=10)
        self.assertEqual(first["total_rows"], 25)
        self.assertTrue(first["truncated"])
        seen = [r["name"] for r in first["rows"]]
        offset = first["next_offset"]
        while True:
            page = table_query.get_table("Спецификация", max_rows=10, offset=offset)
            seen += [r["name"] for r in page["rows"]]
            if not page["truncated"]:
                self.assertNotIn("next_offset", page)
                break
            offset = page["next_offset"]
        self.assertEqual(seen, [f"Воздуховод {i}" for i in range(1, 26)])

    def test_tables_are_listed_and_can_be_chosen(self):
        first = table_query.get_table("Спецификация")
        self.assertEqual(first["table_id"], "Спецификация.xlsx#1")
        self.assertEqual([t["rows"] for t in first["tables"]], [25, 3])

        second = table_query.get_table("Спецификация", table=2)
        self.assertEqual(second["total_rows"], 3)
        self.assertEqual(second["table_id"], "Спецификация.xlsx#2")

        missing = table_query.get_table("Спецификация", table=3)
        self.assertFalse(missing["matched"])

    def test_each_row_says_where_it_came_from(self):
        rows = table_query.get_table("Спецификация", max_rows=3)["rows"]
        self.assertEqual([(r["_table"], r["_line"]) for r in rows], [(1, 2), (1, 3), (1, 4)])
        rooms = table_query.get_table("Спецификация", table=2)["rows"]
        self.assertEqual(rooms[0]["_table"], 2)


if __name__ == "__main__":
    unittest.main()
