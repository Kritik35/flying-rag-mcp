"""A named norm has to reach its own document.

Measured on the live corpus: СП 484.1311500 names itself in 2% of its own chunks
(2 of 98), while 93 *other* documents cite that designation. A lexical channel
that reads chunk text therefore answers "СП 484" with the documents that
reference it and almost never with the norm itself — it sat at rank 40 for a
query that spelled its number out.

The designation is document identity, and identity lives in the file name.
"""
from __future__ import annotations

import unittest

from rag_server.named_norms import extract_norm_designations


class ExtractionTests(unittest.TestCase):
    def test_a_full_designation_is_found(self):
        self.assertEqual(
            extract_norm_designations("что говорит СП 484.1311500 про извещатели"),
            ["СП 484.1311500"],
        )

    def test_a_bare_number_after_the_marker_is_kept(self):
        self.assertEqual(
            extract_norm_designations("требования СП 60 по вентиляции"), ["СП 60"]
        )

    def test_missing_space_is_normalised(self):
        self.assertEqual(extract_norm_designations("см. СП7.13130"), ["СП 7.13130"])

    def test_case_and_yo_are_normalised(self):
        self.assertEqual(extract_norm_designations("сп 7.13130"), ["СП 7.13130"])

    def test_gost_r_keeps_its_letter(self):
        self.assertEqual(
            extract_norm_designations("по ГОСТ Р 59972-2021"), ["ГОСТ Р 59972-2021"]
        )

    def test_snip_and_dashes_survive(self):
        self.assertEqual(
            extract_norm_designations("СНиП 2.09.04-87 бытовые здания"),
            ["СНиП 2.09.04-87"],
        )

    def test_a_federal_law_is_a_designation_too(self):
        self.assertEqual(extract_norm_designations("что требует 123-ФЗ"), ["123-ФЗ"])

    def test_several_designations_keep_query_order_without_duplicates(self):
        self.assertEqual(
            extract_norm_designations("СП 7.13130 и СП 60.13330, снова СП 7.13130"),
            ["СП 7.13130", "СП 60.13330"],
        )

    def test_a_question_without_a_designation_yields_nothing(self):
        for query in (
            "в каких случаях нужно предусматривать удаление дыма из коридоров",
            "как обозначается прочность бетона на сжатие",
            "перечень оборудования по вентиляции в проекте",
        ):
            self.assertEqual(extract_norm_designations(query), [], query)

    def test_a_bare_number_without_a_marker_is_not_a_designation(self):
        """Otherwise "расход 60 м3/ч" would drag in СП 60."""
        self.assertEqual(extract_norm_designations("расход 60 м3/ч на человека"), [])

    def test_a_paragraph_reference_is_not_a_designation(self):
        self.assertEqual(extract_norm_designations("пункт 7.4.1 и таблица 12"), [])


if __name__ == "__main__":
    unittest.main()
