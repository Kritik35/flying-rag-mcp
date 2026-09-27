"""Тест, который пишет в хранилище, делает это только во временном.

См. `tests/_store_guard.py`: без этой проверки общий прогон тестов засорил
боевой индекс поддельным ГОСТом.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests._store_guard import writes_allowed


class StoreGuardTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("FLYING_RAG_CONFIG")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("FLYING_RAG_CONFIG", None)
        else:
            os.environ["FLYING_RAG_CONFIG"] = self._saved

    def test_without_an_override_writing_is_refused(self):
        os.environ.pop("FLYING_RAG_CONFIG", None)

        self.assertFalse(writes_allowed())

    def test_a_scratch_config_allows_writing(self):
        scratch = Path(tempfile.mkdtemp()) / "config.yaml"
        scratch.write_text("storage: {}\n", encoding="utf-8")
        os.environ["FLYING_RAG_CONFIG"] = str(scratch)

        self.assertTrue(writes_allowed())

    def test_pointing_the_override_at_the_live_config_is_still_refused(self):
        import config_loader

        os.environ["FLYING_RAG_CONFIG"] = str(config_loader.ROOT / "config.yaml")

        self.assertFalse(writes_allowed())


if __name__ == "__main__":
    unittest.main()
