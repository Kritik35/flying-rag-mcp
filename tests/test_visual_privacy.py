"""Отладочный флаг не должен отправлять запрос наружу.

`search_documents(debug=True)` вызывал внешний визуальный поиск (Jina) даже при
`include_visual=False`: ветка стояла под `if include_visual or debug`. Отладку
включают и `scripts/rag_eval.py`, и `scripts/verify_local.py --live`, так что
каждый прогон эталона отправлял на внешний сервис запросы с кодами помещений.
Спасал только HTTP 451 на стороне сервиса — случайность, а не контракт.

Внешний визуальный канал теперь вызывается только по явной просьбе:
`include_visual=True` или отдельный `search_drawings`.

Заодно две вещи, без которых это нельзя было проверить:
- `embedder/colpali._cfg` читал корневой config.yaml мимо `FLYING_RAG_CONFIG`,
  и проверка во временном хранилище всё равно ходила по боевым настройкам;
- `search_visual` глотал ошибку и возвращал пустой список, поэтому живая
  проверка не отличала «чертежей не нашлось» от «канал отказал» и была
  зелёной при HTTP 451. Последняя ошибка теперь видна в `LAST_ERROR`.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from embedder import colpali


class DebugDoesNotCallOutTests(unittest.TestCase):
    def test_debug_without_include_visual_never_calls_the_visual_channel(self):
        from rag_server import tools

        with patch.object(colpali, "is_enabled", return_value=True), \
                patch.object(colpali, "search_visual", return_value=[]) as visual:
            try:
                tools.search_documents("проверка", top_k=1, use_cache=False,
                                       debug=True, include_visual=False)
            except Exception:
                # Поиск может не дойти до конца без живого Lemonade; важно
                # только то, что наружу ничего не ушло.
                pass

        visual.assert_not_called()


class ConfigContractTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("FLYING_RAG_CONFIG")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("FLYING_RAG_CONFIG", None)
        else:
            os.environ["FLYING_RAG_CONFIG"] = self._saved

    def test_colpali_settings_follow_the_override(self):
        cfg = Path(tempfile.mkdtemp()) / "config.yaml"
        cfg.write_text(yaml.safe_dump({"colpali": {"enabled": False,
                                                   "marker": "временный"}},
                                      allow_unicode=True), encoding="utf-8")
        os.environ["FLYING_RAG_CONFIG"] = str(cfg)

        self.assertEqual(colpali._cfg().get("marker"), "временный")


class ErrorIsVisibleTests(unittest.TestCase):
    def test_a_failed_call_leaves_its_error_behind(self):
        store = Path(tempfile.mkdtemp())
        with patch.object(colpali, "_cfg", return_value={"api_provider": "jina",
                                                         "api_key": "x"}), \
                patch.object(colpali, "_store_path", return_value=store), \
                patch.object(colpali, "_jina_embed",
                             side_effect=RuntimeError("HTTP Error 451")):
            hits = colpali.search_visual("проверка")

        self.assertEqual(hits, [])
        self.assertIn("451", colpali.LAST_ERROR or "")

    def test_a_successful_call_clears_the_error(self):
        colpali.LAST_ERROR = "старая ошибка"
        with patch.object(colpali, "_store_path", return_value=Path("нет-такого")):
            colpali.search_visual("проверка")

        self.assertIsNone(colpali.LAST_ERROR)


if __name__ == "__main__":
    unittest.main()
