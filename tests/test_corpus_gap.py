"""«Всё ли проиндексировано» должно быть командой, а не расследованием.

Пробел в корпусе я нашёл, идя от провалившихся заданий `reindex_path`: 104
документа, которых нет в индексе. Но так находится только то, по чему задание
запускали и оно упало. Папка, по которой задание не запускали вовсе, не
оставляет следа ни в индексе, ни в журнале — и остаётся невидимой.

Сверять есть с чем: `config.yaml` объявляет `watched_folders`, семь корней, по
которым работает наблюдатель в `main.py`. Это и есть заявление проекта о том,
что должно быть покрыто. Сверка объявленного с содержимым `files` даёт ответ
одной командой и ничего не запускает.

Здесь проверяется сама логика сверки — на выдуманных путях, без обращения ни к
диску, ни к базе.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.corpus_gap import find_gap, is_indexable


class IndexableTests(unittest.TestCase):
    def test_document_formats_count(self):
        for name in ("лист.pdf", "записка.docx", "спец.xlsx", "данные.csv"):
            self.assertTrue(is_indexable(Path(name)), name)

    def test_office_lock_files_do_not_count(self):
        """«~$ведомость.xlsx» — временный файл открытого Excel, не документ."""
        self.assertFalse(is_indexable(Path("~$ведомость.xlsx")))

    def test_other_formats_do_not_count(self):
        for name in ("модель.rvt", "чертёж.dwg", "скрипт.py", "фото.jpg"):
            self.assertFalse(is_indexable(Path(name)), name)

    def test_the_extension_list_can_be_widened(self):
        self.assertTrue(is_indexable(Path("чертёж.dwg"), extensions={".dwg"}))


class FindGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "корень"
        (self.root / "вложенная").mkdir(parents=True)
        self.a = self.root / "есть.pdf"
        self.b = self.root / "вложенная" / "нет.pdf"
        self.c = self.root / "~$временный.xlsx"
        for f in (self.a, self.b, self.c):
            f.write_text("x", encoding="utf-8")

    def test_a_file_in_the_index_is_not_a_gap(self):
        report = find_gap([str(self.root)], {str(self.a), str(self.b)})

        self.assertEqual(report[0]["missing"], [])
        self.assertEqual(report[0]["on_disk"], 2)

    def test_a_file_outside_the_index_is_reported(self):
        report = find_gap([str(self.root)], {str(self.a)})

        self.assertEqual([Path(p).name for p in report[0]["missing"]], ["нет.pdf"])

    def test_nested_folders_are_walked(self):
        report = find_gap([str(self.root)], set())

        self.assertEqual(report[0]["on_disk"], 2)

    def test_lock_files_are_not_counted_as_gaps(self):
        report = find_gap([str(self.root)], set())

        self.assertNotIn("~$временный.xlsx",
                         [Path(p).name for p in report[0]["missing"]])

    def test_the_comparison_ignores_case_and_path_shape(self):
        """В базе путь мог лечь с другим регистром или через прямые слэши."""
        odd = str(self.a).replace("\\", "/").upper()

        report = find_gap([str(self.root)], {odd, str(self.b)})

        self.assertEqual(report[0]["missing"], [])

    def test_a_root_that_is_not_on_disk_is_reported_as_such(self):
        report = find_gap([str(self.tmp / "нет-такого")], set())

        self.assertTrue(report[0]["unreachable"])
        self.assertEqual(report[0]["on_disk"], 0)

    def test_an_unreachable_root_is_not_counted_as_a_gap(self):
        """Съёмный H: не подключён — это не значит, что нормативов нет."""
        report = find_gap([str(self.tmp / "нет-такого")], set())

        self.assertEqual(report[0]["missing"], [])

    def test_every_declared_root_appears_in_the_report(self):
        report = find_gap([str(self.root), str(self.tmp / "нет-такого")], set())

        self.assertEqual(len(report), 2)


if __name__ == "__main__":
    unittest.main()
