"""VERIFIED должен означать «посчитано то, что спросили», а не «посчитано».

Три места, где статус обещал больше, чем ответ давал. Все три воспроизведены
аудитом от 17 сентября и здесь.

1. Спросили сумму денег — получили сумму метров. `_select_field` при нулевой
   сумме выбранного поля переключался на `qty`, в том числе когда поле названо
   явно: `field="amount"` при `amount=0, qty=7` возвращал `field=qty`,
   `total=7`, `status=VERIFIED`. Фактическое поле в ответе было, но вопрос был
   другой. Явно названное поле теперь не подменяется никогда; подмена остаётся
   только там, где поле выбиралось само, и тогда о ней сказано.

2. Файлов больше, чем лимит. `_resolve_files` обрезает список по `max_files`
   (по умолчанию 20) и молчит об этом. Сумма по двадцати файлам из сорока —
   не сумма.

3. Файл не разобрался. Битый xlsx или большой PDF без пригодного parquet
   пропускался, и итог всё равно получал VERIFIED.

Общее правило: пока охват полный и поле то самое — `VERIFIED`; как только
что-то выпало — `PARTIAL` и перечень того, что именно.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

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


class FieldIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = _spec(os.path.join(self.tmp, "ВОР.xlsx"),
                          [("1", "Кабель ВВГнг 3х1,5", "м", 7, 0)])
        self._orig = table_query._resolve_files
        table_query._resolve_files = lambda *a, **k: ([self.file], [])

    def tearDown(self):
        table_query._resolve_files = self._orig

    def test_an_explicitly_asked_field_is_never_swapped(self):
        result = table_query.sum_table_values(subject="кабель", field="amount")

        self.assertEqual(result.get("field"), "amount")
        self.assertNotEqual(result.get("total"), 7.0)

    def test_an_empty_explicit_field_says_so_instead_of_answering(self):
        result = table_query.sum_table_values(subject="кабель", field="amount")

        self.assertNotEqual(result.get("status"), "VERIFIED")
        self.assertIn("amount", str(result.get("reason", "")))

    def test_an_automatic_choice_may_still_fall_back_but_reports_it(self):
        """Без явного поля переключение на «кол-во» полезно и остаётся.

        Предмет назван так, что поле выбирается само и выбирается «сумма»; в
        ВОР она нулевая, и ответить количеством — ровно то, что нужно. Но об
        этом должно быть сказано."""
        result = table_query.sum_table_values(subject="стоимость кабеля")

        self.assertEqual(result.get("field"), "qty")
        self.assertEqual(result.get("total"), 7.0)
        self.assertTrue(result.get("field_fallback_from"))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.files = [
            _spec(os.path.join(self.tmp, f"спец{i}.xlsx"),
                  [("1", "Воздуховод 300x400", "м", 10, 100)])
            for i in range(3)
        ]
        self._orig = table_query._resolve_files

    def tearDown(self):
        table_query._resolve_files = self._orig

    def test_a_complete_pass_is_verified(self):
        table_query._resolve_files = lambda *a, **k: (list(self.files), [])

        result = table_query.sum_table_values(subject="воздуховод")

        self.assertEqual(result.get("status"), "VERIFIED")
        self.assertEqual(result["coverage"]["parsed"], 3)
        self.assertEqual(result["coverage"]["unreadable"], [])

    def test_a_file_that_did_not_parse_is_named_and_downgrades_the_status(self):
        broken = os.path.join(self.tmp, "битая.xlsx")
        Path(broken).write_text("это не xlsx", encoding="utf-8")
        table_query._resolve_files = lambda *a, **k: (self.files + [broken], [])

        result = table_query.sum_table_values(subject="воздуховод")

        self.assertEqual(result.get("status"), "PARTIAL")
        self.assertEqual([Path(p).name for p in result["coverage"]["unreadable"]],
                         ["битая.xlsx"])

    def test_hitting_the_file_limit_downgrades_the_status(self):
        table_query._resolve_files = lambda *a, **k: (list(self.files), [])

        result = table_query.sum_table_values(subject="воздуховод", max_files=3)

        self.assertEqual(result.get("status"), "PARTIAL")
        self.assertTrue(result["coverage"]["hit_file_limit"])

    def test_copies_set_aside_are_named_in_the_answer(self):
        """Отброшенное издание должно быть видно, иначе это тихая потеря."""
        newer = _spec(os.path.join(self.tmp, "ведомость.xlsx"),
                      [("1", "Воздуховод 300x400", "м", 10, 100)])
        older = _spec(os.path.join(self.tmp, "ведомость-04.xlsx"),
                      [("1", "Воздуховод 300x400", "м", 10, 100)])
        os.utime(older, (1, 1))
        table_query._resolve_files = lambda *a, **k: (
            table_query._one_file_per_document([newer, older]),
            table_query._copy_groups([newer, older]))

        result = table_query.sum_table_values(subject="воздуховод")

        self.assertEqual(result.get("total"), 10.0)
        self.assertEqual([Path(p).name for p in result["coverage"]["set_aside"]],
                         ["ведомость-04.xlsx"])


if __name__ == "__main__":
    unittest.main()
