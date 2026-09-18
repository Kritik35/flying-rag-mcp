"""Табличный путь читал боевой config.yaml мимо общего резолвера.

`config_loader` существует именно затем, чтобы проверочный прогон не трогал
рабочую установку: `FLYING_RAG_CONFIG` переводит весь runtime на другой файл.
Весь проект ходит через него — кроме двух мест, `table_query._meta_db` и
`table_parquet._cfg`, где стоял безусловный `open(ROOT / "config.yaml")`.

Последствие не теоретическое: `scripts/verify_local.py` поднимает временное
хранилище и считает, что работает в изоляции, а табличные инструменты в этот
момент читают боевую `metadata.db` и пишут в боевой каталог parquet.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml

from rag_server import table_parquet, table_query


class ConfigOverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / "config.yaml"
        self.cfg.write_text(yaml.safe_dump({
            "storage": {"metadata_db": "data/временная.db"},
            "tables": {"parquet_enabled": True,
                       "parquet_dir": "data/временный_parquet"},
        }, allow_unicode=True), encoding="utf-8")
        self._saved = os.environ.get("FLYING_RAG_CONFIG")
        os.environ["FLYING_RAG_CONFIG"] = str(self.cfg)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("FLYING_RAG_CONFIG", None)
        else:
            os.environ["FLYING_RAG_CONFIG"] = self._saved

    def test_the_metadata_db_follows_the_override(self):
        self.assertEqual(table_query._meta_db().name, "временная.db")

    def test_the_parquet_store_follows_the_override(self):
        self.assertEqual(table_parquet._store_dir().name, "временный_parquet")

    def test_without_an_override_the_project_config_is_used(self):
        os.environ.pop("FLYING_RAG_CONFIG", None)

        self.assertNotEqual(table_query._meta_db().name, "временная.db")
        self.assertNotEqual(table_parquet._store_dir().name, "временный_parquet")

    def test_a_config_without_a_tables_section_still_works(self):
        self.cfg.write_text(yaml.safe_dump(
            {"storage": {"metadata_db": "data/только-хранилище.db"}}),
            encoding="utf-8")

        self.assertEqual(table_query._meta_db().name, "только-хранилище.db")
        self.assertTrue(table_parquet.is_enabled())


if __name__ == "__main__":
    unittest.main()
