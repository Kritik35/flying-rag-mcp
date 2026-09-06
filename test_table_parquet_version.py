"""Кэш разобранных таблиц не помнил, чем он разобран.

`sum_table_values` читает строки из parquet, если он есть, и только иначе
разбирает исходник. Версии у кэша не было, поэтому любая правка разбора
оставалась невидимой: на живом корпусе 2192 parquet-файла, и лист
`АТ-РД-ОВ3-С-00-10.02-02.pdf` отдавал 87 строк штампа, разобранных прежним
кодом, — исправленный разбор к нему просто не вызывался.

Это тот же дефект, что уже находился сегодня в других местах: сохранённое
состояние, которое выглядит здоровым и молча отменяет правку. Кэш с версией
переразбирает файл сам, по одному, когда до него дойдёт запрос.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rag_server.table_parquet as tp

ROWS = [
    {"pos": "У-02.8.1", "name": "Завеса", "unit": "шт.", "qty": 1.0,
     "section": "Воздушно-тепловые завесы", "raw_row": {"Кол.": "1"}},
    {"pos": "У-01.2.5", "name": "Завеса", "unit": "шт.", "qty": 1.0,
     "section": "Воздушно-тепловые завесы", "raw_row": {"Кол.": "1"}},
]


class ParquetVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store"
        self.source = str(Path(self.tmp.name) / "лист.pdf")
        self._patch = patch.object(tp, "_store_dir", return_value=self.store)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_a_freshly_written_cache_is_usable(self):
        tp.write_parquet(self.source, ROWS)

        self.assertTrue(tp.has_parquet(self.source))
        self.assertEqual(len(tp.read_parquet_rows(self.source)), 2)

    def test_the_writer_stamps_the_parser_version(self):
        tp.write_parquet(self.source, ROWS)

        self.assertEqual(tp.parquet_version(self.source), tp.PARSER_VERSION)

    def test_a_cache_from_another_parser_counts_as_absent(self):
        """Так правка разбора доходит до данных сама, без массовой перестройки."""
        tp.write_parquet(self.source, ROWS)
        with patch.object(tp, "PARSER_VERSION", tp.PARSER_VERSION + 1):
            self.assertFalse(tp.has_parquet(self.source))

    def test_a_stale_cache_is_not_read_either(self):
        tp.write_parquet(self.source, ROWS)
        with patch.object(tp, "PARSER_VERSION", tp.PARSER_VERSION + 1):
            self.assertEqual(tp.read_parquet_rows(self.source), [])

    def test_a_cache_without_a_version_is_stale(self):
        """Все 2192 существующих файла записаны без версии — их надо перечитать."""
        tp.write_parquet(self.source, ROWS)
        with patch.object(tp, "_read_version", return_value=None):
            self.assertFalse(tp.has_parquet(self.source))

    def test_rows_survive_the_round_trip(self):
        tp.write_parquet(self.source, ROWS)
        back = tp.read_parquet_rows(self.source)

        self.assertEqual(back[0]["pos"], "У-02.8.1")
        self.assertEqual(back[0]["qty"], 1.0)
        self.assertEqual(back[0]["section"], "Воздушно-тепловые завесы")


if __name__ == "__main__":
    unittest.main()
