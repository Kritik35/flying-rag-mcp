"""A citation has to be able to say which page it came from.

The store has no page field — adding one means reindexing 1.25M chunks — so the
page is looked up in the source document at the moment someone asks for it.
Measured on 40 stored chunks before building this: the page was found for all
40, 39 of them on a twelve-word probe, median 694ms per lookup. Too slow to
attach to every search result, fast enough to answer on demand.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from rag_server.locator import locate_quote, probes

PAGES = [
    "Общие положения настоящего свода правил распространяются на здания",
    "Системы вытяжной противодымной вентиляции следует предусматривать "
    "для удаления продуктов горения из коридоров и холлов зданий",
    "Расход приточного воздуха определяется расчетом воздухообмена помещения",
]


# A font that actually carries Cyrillic. PyMuPDF's built-in fonts are
# Latin-only: insert_text writes a row of dots for Russian text, and a
# fixture built with them would be testing nothing at all.
CYRILLIC_FONT = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "Fonts" / "arial.ttf"


def _make_pdf(path: Path) -> None:
    """A fixture with real Cyrillic in it.

    PyMuPDF's built-in fonts are Latin-only: insert_text writes a row of dots
    for Cyrillic and the fixture then tests nothing. The font has to be a real
    one that carries the alphabet the corpus is written in.
    """
    import fitz

    doc = fitz.open()
    for text in PAGES:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=11,
                         fontname="cyr", fontfile=str(CYRILLIC_FONT))
    doc.save(str(path))
    doc.close()


class ProbeLadderTests(unittest.TestCase):
    def test_the_longest_probe_comes_first(self):
        words = " ".join(f"слово{i}" for i in range(30))
        ladder = probes(words)

        self.assertEqual([len(p.split()) for p in ladder], [12, 8, 5])

    def test_a_short_quote_still_yields_a_probe(self):
        ladder = probes("система вытяжной противодымной вентиляции коридоров шесть")
        self.assertTrue(ladder)
        self.assertLessEqual(len(ladder[0].split()), 6)

    def test_an_empty_quote_yields_nothing(self):
        self.assertEqual(probes("   "), [])

    def test_line_breaks_do_not_survive_into_the_needle(self):
        ladder = probes("предел\nогнестойкости   воздуховодов\tне менее EI 30 "
                        "для транзитных участков систем вентиляции здания")
        self.assertTrue(all("\n" not in p and "  " not in p for p in ladder))


class LocateQuoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CYRILLIC_FONT.exists():
            raise unittest.SkipTest(f"нет шрифта с кириллицей: {CYRILLIC_FONT}")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf = Path(cls.tmp.name) / "СП тестовый.pdf"
        _make_pdf(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_quote_is_traced_to_its_page(self):
        result = locate_quote(str(self.pdf), PAGES[1], allowed=[str(self.pdf)])

        self.assertEqual(result["pages"], [2])
        self.assertEqual(result["status"], "found")

    def test_the_first_page_is_page_one_not_page_zero(self):
        result = locate_quote(str(self.pdf), PAGES[0], allowed=[str(self.pdf)])
        self.assertEqual(result["pages"], [1])

    def test_text_that_is_not_there_is_reported_as_not_found(self):
        result = locate_quote(str(self.pdf), "класс бетона по прочности на сжатие "
                                             "принимается по таблице приложения",
                              allowed=[str(self.pdf)])

        self.assertEqual(result["pages"], [])
        self.assertEqual(result["status"], "not_found")

    def test_a_document_outside_the_index_is_refused(self):
        result = locate_quote(str(self.pdf), PAGES[0], allowed=["другой.pdf"])

        self.assertEqual(result["status"], "not_indexed")
        self.assertEqual(result["pages"], [])

    def test_a_missing_file_is_reported_not_raised(self):
        missing = str(Path(self.tmp.name) / "нет.pdf")
        result = locate_quote(missing, PAGES[0], allowed=[missing])

        self.assertEqual(result["status"], "missing")

    def test_a_format_without_pages_says_so(self):
        other = Path(self.tmp.name) / "таблица.xlsx"
        other.write_bytes(b"not a pdf")
        result = locate_quote(str(other), PAGES[0], allowed=[str(other)])

        self.assertEqual(result["status"], "unsupported_format")

    def test_the_answer_says_how_it_matched(self):
        result = locate_quote(str(self.pdf), PAGES[1], allowed=[str(self.pdf)])

        self.assertIn("probe_words", result)
        self.assertGreater(result["probe_words"], 0)


if __name__ == "__main__":
    unittest.main()
