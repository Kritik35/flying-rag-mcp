"""The search cache stays bounded.

SEMANTIC_CACHE_MAX_ROWS was declared and never used, and nothing called
clear(): on the live store the cache had grown to 764 entries and 21 MB with
entries five months old. Each store now trims the table to the row limit
(newest kept) and drops entries past their age.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from storage import semantic_cache as sc


class CacheBoundsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "metadata.db"
        from storage.metadata_db import init_db
        init_db(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def _queries(self):
        with closing(sqlite3.connect(self.db)) as con:
            return [r[0] for r in con.execute(
                "SELECT norm_query FROM search_cache ORDER BY created_at")]

    def test_the_row_limit_keeps_the_newest(self):
        cache = sc.SemanticCache(db_path=str(self.db))
        with mock.patch.object(sc, "_CACHE_MAX_ROWS", 3):
            for i in range(5):
                cache.store(f"q{i}", [1.0, 0.0], [{"r": i}])
        self.assertEqual(self._queries(), ["q2", "q3", "q4"])

    def test_entries_past_their_age_are_dropped(self):
        cache = sc.SemanticCache(db_path=str(self.db))
        cache.store("old", [1.0, 0.0], [{"r": 0}])
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE search_cache SET created_at = ?",
                        (time.time() - 30 * 86400,))
        with mock.patch.object(sc, "_CACHE_TTL_DAYS", 14.0):
            cache.store("new", [1.0, 0.0], [{"r": 1}])
        self.assertEqual(self._queries(), ["new"])


if __name__ == "__main__":
    unittest.main()
