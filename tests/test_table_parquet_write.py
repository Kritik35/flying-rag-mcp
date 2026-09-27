"""Запись табличного кэша: не оставлять обрывков и не молчать о сбое.

Две вещи из аудита, обе в `rag_server/table_parquet.py`.

1. Parquet писался прямо в итоговый файл. Сбой посреди записи — нехватка
   места, убитый процесс (а наблюдатель теперь убивает зависшие) — оставлял
   обрезанный файл на месте прежнего, годного. Теперь запись идёт во
   временный файл рядом и подменяет итоговый одним `os.replace`: либо старый
   кэш, либо новый, промежуточного состояния нет.

2. Hook индексатора `maybe_write_for_indexer` глотал любое исключение и
   возвращал 0 — ровно то же, что «в файле нет таблиц». Сломанный разбор был
   неотличим от пустого документа. Теперь сбой печатается в stderr с именем
   файла и причиной; индексацию он по-прежнему не останавливает.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from rag_server import table_parquet as tp

ROWS = [{"pos": "1", "name": "Воздуховод 300x400", "unit": "м", "qty": 10.0,
         "raw_row": {"Кол-во": "10"}}]


def _dies_mid_write(table, where, *args, **kwargs):
    """Как настоящий сбой посреди записи: обрывок в файле, потом исключение."""
    Path(where).write_bytes(b"PAR1 \xd0\xbe\xd0\xb1\xd1\x80\xd1\x8b\xd0\xb2")
    raise OSError("диск заполнен")


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = self.tmp / "store"
        self._p = patch.object(tp, "_store_dir", return_value=self.store)
        self._p.start()
        self.addCleanup(self._p.stop)
        self.source = str(self.tmp / "спец.xlsx")

    def test_a_failed_write_leaves_the_previous_cache_intact(self):
        tp.write_parquet(self.source, ROWS)
        before = tp.parquet_path(self.source).read_bytes()

        import pyarrow.parquet as pq
        with patch.object(pq, "write_table", side_effect=_dies_mid_write):
            with self.assertRaises(OSError):
                tp.write_parquet(self.source, ROWS + ROWS)

        self.assertEqual(tp.parquet_path(self.source).read_bytes(), before)

    def test_no_temporary_file_is_left_behind(self):
        import pyarrow.parquet as pq
        with patch.object(pq, "write_table", side_effect=_dies_mid_write):
            with self.assertRaises(OSError):
                tp.write_parquet(self.source, ROWS)

        self.assertEqual([p.name for p in self.store.glob("*.tmp*")], [])

    def test_a_normal_write_still_produces_a_readable_cache(self):
        tp.write_parquet(self.source, ROWS)

        self.assertEqual(len(tp.read_parquet_rows(self.source)), 1)


class HookReportsFailureTests(unittest.TestCase):
    def test_a_parse_failure_is_reported_not_swallowed(self):
        err = io.StringIO()
        with patch.object(tp, "is_enabled", return_value=True), \
                patch.object(tp, "write_parquet", side_effect=ValueError("битая шапка")), \
                redirect_stderr(err):
            n = tp.maybe_write_for_indexer(r"C:\corpus\ведомость.xlsx")

        self.assertEqual(n, 0)
        self.assertIn("ведомость.xlsx", err.getvalue())
        self.assertIn("битая шапка", err.getvalue())

    def test_a_file_without_tables_stays_silent(self):
        err = io.StringIO()
        with patch.object(tp, "is_enabled", return_value=True), \
                patch.object(tp, "write_parquet", return_value=0), \
                redirect_stderr(err):
            tp.maybe_write_for_indexer(r"C:\corpus\записка.docx")

        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
