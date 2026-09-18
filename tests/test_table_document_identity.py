"""Спецификация вышла новым изданием — и сумма стала вдвое больше.

`scripts/table_baseline.py` поймал это на живом корпусе: по `ОВ2-С-00-СО`
воздуховод дал 161 673.83 при сверенных с openpyxl 81 511.01, ровно вдвое.
Причина в данных, а не в правке: 4 сентября в корпус добавили новое издание той
же спецификации, и оно легло рядом со старым —

    PR-RD-HV2-С-00-СО-06.xlsx   изменён 2026-06-02, 12 700 строк
    PR-RD-HV2-С-00-СО.xlsx      изменён 2026-09-04, 13 235 строк

Ключ документа сравнивал имена целиком, `…-СО` и `…-СО-06` считались разными
документами, и обе ведомости сложились. В поиске этот же номер изменения я уже
срезаю (`retrieval_quality.document_key`), в табличном пути — нет.

По корпусу срез хвоста `-NN` склеивает 247 групп, и в каждой это издания одного
листа: `-04` и `-06`, «(1)» и без суффикса. Ни одной группы, где под общим
ключом оказались бы разные документы, среди них нет.

Из группы берётся файл с самой поздней датой изменения, а не с большим номером:
сентябрьское издание вышло без суффикса вообще, и по номеру победило бы
июньское. Отложенные файлы больше не исчезают молча — они названы в ответе.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from rag_server.table_query import _copy_groups, _document_key, _one_file_per_document


class DocumentKeyTests(unittest.TestCase):
    def test_an_issue_number_is_not_part_of_the_identity(self):
        self.assertEqual(_document_key(r"C:\corpus\PR-RD-HV2-С-00-СО-06.xlsx"),
                         _document_key(r"C:\corpus\PR-RD-HV2-С-00-СО.xlsx"))

    def test_a_sheet_number_survives(self):
        """«10.03» и «10.04» — разные листы, а не издания друг друга."""
        self.assertNotEqual(_document_key(r"C:\corpus\PR-RD-HV2-С-00-10.03-06.pdf"),
                            _document_key(r"C:\corpus\PR-RD-HV2-С-00-10.04-06.pdf"))

    def test_a_sub_sheet_survives(self):
        self.assertNotEqual(_document_key(r"C:\corpus\PR-RD-HV2-С-00-31.02.1-04.pdf"),
                            _document_key(r"C:\corpus\PR-RD-HV2-С-00-31.02.2-04.pdf"))

    def test_a_qualifier_in_the_name_still_separates_documents(self):
        """«СО (ПДВ)» — отдельная ведомость, а не издание «СО»."""
        self.assertNotEqual(_document_key(r"C:\corpus\PR-RD-HV2-С-00-СО (ПДВ).xlsx"),
                            _document_key(r"C:\corpus\PR-RD-HV2-С-00-СО.xlsx"))

    def test_a_numbered_copy_is_the_same_document(self):
        self.assertEqual(_document_key(r"C:\corpus\ведомость (1).xlsx"),
                         _document_key(r"C:\corpus\ведомость.xlsx"))

    def test_a_year_in_a_norm_designation_is_not_an_issue_number(self):
        self.assertEqual(_document_key(r"C:\corpus\ГОСТ 12.1.019-2017.docx"),
                         "гост 12.1.019-2017")


class NewestIssueWinsTests(unittest.TestCase):
    """Из изданий одного документа считается самое свежее по дате файла."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name: str, mtime: float) -> str:
        path = os.path.join(self.tmp, name)
        Path(path).write_text("x", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_the_september_issue_wins_over_the_june_one(self):
        june = self._write("PR-RD-HV2-С-00-СО-06.xlsx", time.time() - 90 * 86400)
        sept = self._write("PR-RD-HV2-С-00-СО.xlsx", time.time())

        kept = _one_file_per_document([june, sept])

        self.assertEqual(kept, [sept])

    def test_the_twin_formats_still_collapse_to_the_cell_based_one(self):
        """При равной дате решает формат: в .xlsx таблица лежит ячейками."""
        now = time.time()
        pdf = self._write("ведомость.pdf", now)
        xlsx = self._write("ведомость.xlsx", now)

        kept = _one_file_per_document([pdf, xlsx])

        self.assertEqual(kept, [xlsx])

    def test_different_documents_are_all_kept(self):
        now = time.time()
        files = [self._write(n, now) for n in
                 ("ОВ2-СО.xlsx", "ОВ3-СО.xlsx", "ОВ4-СО.xlsx")]

        self.assertEqual(len(_one_file_per_document(files)), 3)


class SetAsideIsReportedTests(unittest.TestCase):
    """Отложенный файл, о котором не сказано, — это молчаливая потеря данных."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name: str, mtime: float) -> str:
        path = os.path.join(self.tmp, name)
        Path(path).write_text("x", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_the_files_left_out_are_named(self):
        june = self._write("PR-RD-HV2-С-00-СО-06.xlsx", time.time() - 90 * 86400)
        sept = self._write("PR-RD-HV2-С-00-СО.xlsx", time.time())

        groups = _copy_groups([june, sept])

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(Path(group["used"]).name, "PR-RD-HV2-С-00-СО.xlsx")
        self.assertEqual([Path(p).name for p in group["set_aside"]],
                         ["PR-RD-HV2-С-00-СО-06.xlsx"])

    def test_without_dates_the_issue_number_decides(self):
        """Файлов может не быть на диске: тогда номер издания — всё, что есть."""
        groups = _copy_groups([r"C:\нет\PR-RD-HV2-С-00-СО.xlsx",
                               r"C:\нет\PR-RD-HV2-С-00-СО-06.xlsx"])

        self.assertEqual(Path(groups[0]["used"]).name, "PR-RD-HV2-С-00-СО-06.xlsx")

    def test_a_document_without_copies_is_not_reported(self):
        self.assertEqual(_copy_groups([r"C:\corpus\единственная.xlsx"]), [])


if __name__ == "__main__":
    unittest.main()
