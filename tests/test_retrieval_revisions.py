"""Изм.4 и изм.6 одного листа — один документ, и показывать надо изм.6.

В индексе 1851 файл, из них 185 — вторая (а иногда третья) редакция уже
лежащего там листа: `PR-RD-HV2-С-00-31.02.1-04.pdf` рядом с
`…-31.02.1-06.pdf`. Ключ документа обрезал только суффикс копии « (1)», а
номер изменения принимал за часть имени, поэтому каждая редакция получала
собственный лимит в выдаче. На запросе по коду помещения это дало четыре
слота из пяти под один лист: изм.4 дважды и изм.6 дважды.

Хуже, что при равных очках наверх могла попасть старая редакция — а для
рабочей документации это разница между верным и неверным ответом. Номер
изменения добавлен последним тай-брейком: он решает только там, где всё
остальное уже сравнялось, и ничего не прячет.

Подсуффиксы листа при этом остаются разными документами: `31.02.1` и
`31.02.2` — разные листы, а не редакции друг друга.
"""
from __future__ import annotations

import unittest

from rag_server.retrieval_quality import apply_retrieval_quality, document_key, revision_of


def item(name: str, score: float = 1.0, text: str = "текст") -> dict:
    return {"file_name": name, "source_path": rf"C:\corpus\{name}",
            "text": text, "score": score}


class DocumentKeyTests(unittest.TestCase):
    def test_two_revisions_of_a_sheet_are_one_document(self):
        self.assertEqual(document_key(item("PR-RD-HV2-С-00-31.02.1-04.pdf")),
                         document_key(item("PR-RD-HV2-С-00-31.02.1-06.pdf")))

    def test_a_sub_sheet_is_not_a_revision_of_its_neighbour(self):
        self.assertNotEqual(document_key(item("PR-RD-HV2-С-00-31.02.1-04.pdf")),
                            document_key(item("PR-RD-HV2-С-00-31.02.2-04.pdf")))

    def test_a_copy_and_a_revision_meet_at_the_same_key(self):
        self.assertEqual(document_key(item("PR-RD-HV2-С-00-10.03 (1).pdf")),
                         document_key(item("PR-RD-HV2-С-00-10.03-06.pdf")))

    def test_a_norm_year_is_not_a_revision(self):
        """«ГОСТ 12.1.019-2017» — год в обозначении, а не номер изменения."""
        self.assertEqual(document_key(item("ГОСТ 12.1.019-2017. Стандарт.docx")),
                         "гост 12.1.019-2017. стандарт")

    def test_a_name_without_a_sheet_number_is_left_alone(self):
        self.assertEqual(document_key(item("Приложение-02.pdf")), "приложение-02")


class RevisionTests(unittest.TestCase):
    def test_the_revision_is_read_from_the_name(self):
        self.assertEqual(revision_of(item("PR-RD-HV2-С-00-10.03-06.pdf")), 6)
        self.assertEqual(revision_of(item("PR-RD-HV2-С-00-10.03-04.pdf")), 4)

    def test_a_sheet_without_a_revision_is_the_oldest(self):
        self.assertEqual(revision_of(item("PR-RD-HV2-С-00-10.03 (1).pdf")), 0)


class DiversifyTests(unittest.TestCase):
    def test_one_sheet_no_longer_takes_four_slots_of_five(self):
        results = [
            item("PR-RD-HV2-С-00-10.03-06.pdf", 1.0, "а"),
            item("PR-RD-HV2-С-00-10.03 (1).pdf", 1.0, "б"),
            item("PR-RD-HV2-С-00-10.03-04.pdf", 1.0, "в"),
            item("PR-RD-HV2-С-00-10.03 (1).pdf", 1.0, "г"),
            item("PR-RD-HV3-С-00-31.07-02.pdf", 0.9, "д"),
            item("PR-RD-HV4-С-00-10.01-02.pdf", 0.8, "е"),
        ]
        out = apply_retrieval_quality("R.L2.15.092", results, top_k=5, max_per_doc=2)
        keys = [document_key(r) for r in out]

        self.assertLessEqual(keys.count("pr-rd-hv2-b-00-10.03"), 2)
        self.assertEqual(len(set(keys)), 3)

    def test_the_newer_revision_is_shown_when_nothing_else_separates_them(self):
        results = [
            item("PR-RD-HV2-С-00-10.03-04.pdf", 1.0, "а"),
            item("PR-RD-HV2-С-00-10.03-06.pdf", 1.0, "б"),
        ]
        out = apply_retrieval_quality("R.L2.15.092", results, top_k=1, max_per_doc=2)

        self.assertEqual(out[0]["file_name"], "PR-RD-HV2-С-00-10.03-06.pdf")

    def test_the_revision_never_reorders_different_documents(self):
        """Номер изменения решает внутри листа, а не между листами.

        Свежая редакция одного листа не должна обгонять другой лист, который
        отвечает лучше: изм.6 — признак того, какое издание показать, а не
        того, что лист отвечает на вопрос. Внутри одного листа правило
        обратное и намеренное, см. OneRevisionPerDocumentTests.
        """
        results = [
            item("PR-RD-HV2-С-00-10.03-06.pdf", 0.4, "б"),
            item("PR-RD-HV4-С-00-31.01-02.pdf", 0.9, "а"),
        ]
        out = apply_retrieval_quality("R.L2.15.092", results, top_k=1, max_per_doc=2)

        self.assertEqual(out[0]["file_name"], "PR-RD-HV4-С-00-31.01-02.pdf")


if __name__ == "__main__":
    unittest.main()


class OneRevisionPerDocumentTests(unittest.TestCase):
    """Два издания одного листа в ответе — это один лист, показанный дважды.

    Лимит на документ считает их за один документ, поэтому оба помещаются в
    его бюджет: на запросе по кодам помещений в выдаче стояли рядом
    `PR-RD-HV2-С-00-31.17-06.pdf` и `…-31.17-04.pdf`. Из всех редакций листа,
    попавших в пул, показывается только старшая — и решает это не порядок
    очков, а максимум по пулу, иначе редакция ответа зависела бы от того,
    какой кусок текста набрал больше.

    Цена названа прямо: если у изм.6 в пуле кусок хуже, чем у изм.4, ответ
    станет хуже. Для рабочей документации это лучше, чем молча показать
    отменённый лист.
    """

    def test_only_the_newest_revision_in_the_pool_is_shown(self):
        results = [
            item("PR-RD-HV2-С-00-31.17-06.pdf", 1.0, "а"),
            item("PR-RD-HV2-С-00-31.17-04.pdf", 0.99, "б"),
            item("PR-RD-HV4-С-00-10.01-02.pdf", 0.5, "в"),
        ]
        out = apply_retrieval_quality("R.L2.15.092", results, top_k=5, max_per_doc=2)

        self.assertEqual([r["file_name"] for r in out],
                         ["PR-RD-HV2-С-00-31.17-06.pdf", "PR-RD-HV4-С-00-10.01-02.pdf"])

    def test_the_older_revision_loses_even_when_it_scores_higher(self):
        results = [
            item("PR-RD-HV2-С-00-31.17-04.pdf", 1.0, "б"),
            item("PR-RD-HV2-С-00-31.17-06.pdf", 0.3, "а"),
        ]
        out = apply_retrieval_quality("R.L2.15.092", results, top_k=5, max_per_doc=2)

        self.assertEqual([r["file_name"] for r in out], ["PR-RD-HV2-С-00-31.17-06.pdf"])

    def test_a_sheet_present_in_one_revision_only_is_untouched(self):
        results = [
            item("PR-RD-HV2-С-00-31.17-04.pdf", 1.0, "а"),
            item("PR-RD-HV2-С-00-31.17-04.pdf", 0.9, "б"),
        ]
        out = apply_retrieval_quality("R.L2.15.092", results, top_k=5, max_per_doc=2)

        self.assertEqual(len(out), 2)

    def test_documents_without_revisions_are_not_affected(self):
        results = [
            item("СП 7.13130.docx", 1.0, "а"),
            item("СП 60.13330.2020.pdf", 0.9, "б"),
        ]
        out = apply_retrieval_quality("дымоудаление", results, top_k=5, max_per_doc=2)

        self.assertEqual(len(out), 2)
