"""Кэш отдавал число, которого в файле уже нет, — и называл его проверенным.

Воспроизведение, с которого началась правка: записали спецификацию с
количеством 10, спросили сумму, получили 10 и кэш. Изменили исходник на 999,
переиндексации не делали, спросили снова — снова 10, статус `VERIFIED`.

`has_parquet` сверял только `PARSER_VERSION`: он отвечает на вопрос «тем ли
кодом разобрано», но не на вопрос «то ли это содержимое». Рядом с версией
теперь пишется отпечаток источника — размер и время изменения, — и кэш чужого
отпечатка считается отсутствующим, ровно как кэш чужой версии.

Отпечаток намеренно дешёвый. sha256 пришлось бы считать на каждый запрос, а в
корпусе есть PDF по 78 МБ; размер и mtime читаются из каталога файловой
системы. Цена известна: правка, не изменившая ни размера, ни времени, останется
незамеченной. Это заметно лучше нынешнего положения, когда незамеченной
остаётся любая.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from rag_server import table_parquet, table_query


def _strip_fingerprint(parquet_file: Path) -> None:
    """Сделать из кэша такой, каким его писала прежняя версия — без отпечатка."""
    import pyarrow.parquet as pq

    table = pq.read_table(parquet_file)
    meta = {k: v for k, v in (table.schema.metadata or {}).items()
            if k != b"source_fingerprint"}
    pq.write_table(table.replace_schema_metadata(meta), parquet_file)


def _spec(path: str, qty) -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(["Поз.", "Наименование", "Ед. изм.", "Кол-во"])
    ws.append(["1", "Воздуховод 300x400", "м", qty])
    wb.save(path)
    return path


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Path(self.tmp) / "parquet"
        self.store.mkdir()
        self._orig_store = table_parquet._store_dir
        table_parquet._store_dir = lambda: self.store
        self.file = _spec(os.path.join(self.tmp, "спец.xlsx"), 10)

    def tearDown(self):
        table_parquet._store_dir = self._orig_store

    def test_a_fresh_cache_is_usable(self):
        table_parquet.write_parquet(self.file)

        self.assertTrue(table_parquet.has_parquet(self.file))

    def test_a_changed_source_makes_the_cache_unusable(self):
        table_parquet.write_parquet(self.file)
        _spec(self.file, 999)

        self.assertFalse(table_parquet.has_parquet(self.file))

    def test_a_source_that_only_grew_is_noticed(self):
        """Размер меняется даже когда время не сдвинулось заметно."""
        table_parquet.write_parquet(self.file)
        before = table_parquet.source_fingerprint(self.file)
        _spec(self.file, 12345678)
        after = table_parquet.source_fingerprint(self.file)

        self.assertNotEqual(before, after)

    def test_a_missing_source_has_no_fingerprint(self):
        self.assertIsNone(table_parquet.source_fingerprint(
            os.path.join(self.tmp, "нет-такого.xlsx")))

    def test_an_unreachable_source_leaves_the_cache_usable(self):
        """Нормативы лежат на съёмном H:. Отключить кэш, когда диск не
        подключён, — значит потерять весь нормативный корпус ради проверки,
        которую всё равно нечем сделать. Сверять не с чем — берём что есть."""
        table_parquet.write_parquet(self.file)
        os.remove(self.file)

        self.assertTrue(table_parquet.has_parquet(self.file))

    def test_a_cache_written_before_fingerprints_is_re_parsed(self):
        """Старый кэш без отпечатка: исходник на месте, подтвердить нечем."""
        table_parquet.write_parquet(self.file)
        _strip_fingerprint(table_parquet.parquet_path(self.file))

        self.assertFalse(table_parquet.has_parquet(self.file))


class AnswerIsRecomputedTests(unittest.TestCase):
    """Тот самый опыт, целиком, через инструмент."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Path(self.tmp) / "parquet"
        self.store.mkdir()
        self._orig_store = table_parquet._store_dir
        table_parquet._store_dir = lambda: self.store
        self.file = _spec(os.path.join(self.tmp, "спец.xlsx"), 10)
        self._orig_resolve = table_query._resolve_files
        table_query._resolve_files = lambda *a, **k: ([self.file], [])

    def tearDown(self):
        table_parquet._store_dir = self._orig_store
        table_query._resolve_files = self._orig_resolve

    def test_the_total_follows_the_source(self):
        first = table_query.sum_table_values(subject="воздуховод")
        self.assertEqual(first.get("total"), 10.0)

        _spec(self.file, 999)
        second = table_query.sum_table_values(subject="воздуховод")

        self.assertEqual(second.get("total"), 999.0)

    def test_the_stale_answer_is_not_called_verified(self):
        table_query.sum_table_values(subject="воздуховод")
        _spec(self.file, 999)

        second = table_query.sum_table_values(subject="воздуховод")

        self.assertNotEqual(second.get("total"), 10.0)


if __name__ == "__main__":
    unittest.main()
