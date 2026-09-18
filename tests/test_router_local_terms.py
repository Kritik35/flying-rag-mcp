"""Имя объекта заказчика не должно лежать в публичном репозитории.

Репозиторий открыт на GitHub. Вчера я добавил домен `project_object`, чтобы
маршрутизатор понимал название объекта, и вписал в отслеживаемый
`config/retrieval_terms.yaml` название объекта и его адрес. Механизм нужен,
а данные — нет: они говорят, чей это проект и где он стоит.

Тот же приём, которым в проекте уже решён `config.yaml`: отслеживается пример,
а рабочий файл лежит рядом и в `.gitignore`. Здесь — `retrieval_terms.local.yaml`
рядом с общим файлом: домены из него дополняют общие, одноимённые заменяют.
Нет файла — работает ровно как раньше.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from rag_server.query_router import _load_config


SHARED = {
    "confidence": {"confident": 0.62},
    "domains": [
        {"id": "normative_scope", "label": "normative_scope",
         "dataset": "normative", "terms": ["в нормативах"]},
        {"id": "project_object", "label": "project_object",
         "dataset": "project", "terms": []},
    ],
}

LOCAL = {
    "domains": [
        {"id": "project_object", "label": "project_object",
         "dataset": "project", "terms": ["вымышленск", "улица вымышленная"]},
        {"id": "project_site_b", "label": "project_site_b",
         "dataset": "project", "terms": ["вторая площадка"]},
    ],
}


class LocalOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.shared = self.tmp / "retrieval_terms.yaml"
        self.shared.write_text(yaml.safe_dump(SHARED, allow_unicode=True),
                               encoding="utf-8")
        self.local = self.tmp / "retrieval_terms.local.yaml"
        _load_config.cache_clear()

    def tearDown(self):
        _load_config.cache_clear()

    def test_without_a_local_file_nothing_changes(self):
        cfg = _load_config(str(self.shared))

        self.assertEqual([d["id"] for d in cfg["domains"]],
                         ["normative_scope", "project_object"])

    def test_a_local_domain_is_added(self):
        self.local.write_text(yaml.safe_dump(LOCAL, allow_unicode=True),
                              encoding="utf-8")
        _load_config.cache_clear()

        cfg = _load_config(str(self.shared))
        ids = [d["id"] for d in cfg["domains"]]

        self.assertIn("project_site_b", ids)

    def test_a_local_domain_replaces_the_shared_one_of_the_same_name(self):
        self.local.write_text(yaml.safe_dump(LOCAL, allow_unicode=True),
                              encoding="utf-8")
        _load_config.cache_clear()

        cfg = _load_config(str(self.shared))
        obj = next(d for d in cfg["domains"] if d["id"] == "project_object")

        self.assertEqual(obj["terms"], ["вымышленск", "улица вымышленная"])

    def test_the_shared_domains_survive(self):
        self.local.write_text(yaml.safe_dump(LOCAL, allow_unicode=True),
                              encoding="utf-8")
        _load_config.cache_clear()

        cfg = _load_config(str(self.shared))

        self.assertIn("normative_scope", [d["id"] for d in cfg["domains"]])

    def test_shared_settings_are_kept(self):
        self.local.write_text(yaml.safe_dump(LOCAL, allow_unicode=True),
                              encoding="utf-8")
        _load_config.cache_clear()

        cfg = _load_config(str(self.shared))

        self.assertEqual(cfg["confidence"]["confident"], 0.62)

    def test_a_broken_local_file_does_not_break_routing(self):
        self.local.write_text("это: [не, закрытый", encoding="utf-8")
        _load_config.cache_clear()

        cfg = _load_config(str(self.shared))

        self.assertEqual([d["id"] for d in cfg["domains"]],
                         ["normative_scope", "project_object"])


class PublishedVocabularyTests(unittest.TestCase):
    """Сам отслеживаемый файл не должен называть заказчика."""

    def test_the_tracked_vocabulary_names_no_client(self):
        shared = Path(__file__).resolve().parent.parent / "config" / "retrieval_terms.yaml"
        text = shared.read_text(encoding="utf-8").casefold()

        for marker in ("охт", "красногвард", "общественно-делов"):
            self.assertNotIn(marker, text, marker)

    def test_the_object_domain_still_exists_for_operators_to_fill(self):
        shared = Path(__file__).resolve().parent.parent / "config" / "retrieval_terms.yaml"
        cfg = yaml.safe_load(shared.read_text(encoding="utf-8"))

        self.assertIn("project_object", [d["id"] for d in cfg["domains"]])


if __name__ == "__main__":
    unittest.main()
