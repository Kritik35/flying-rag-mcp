"""OCR must fail closed and must not lose pages.

Three defects this covers:
  1. a failed page used to enter the index as "[Ошибка распознавания ...]";
  2. rasterness was decided per document, so a mixed PDF dropped its scans;
  3. nothing recorded that pages were never recovered.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parsers import pdf_vision
from parsers.ocr import OCRParser, OCRProcessingError


class FakePage:
    def __init__(self, text: str = ""):
        self._text = text

    def get_text(self, *_args, **_kwargs):
        return self._text


class FakeDoc:
    def __init__(self, texts: list[str]):
        self.pages = [FakePage(t) for t in texts]

    def __len__(self):
        return len(self.pages)

    def __iter__(self):
        return iter(self.pages)

    def __getitem__(self, item):
        return self.pages[item]


class OCRProcessingErrorTests(unittest.TestCase):
    def test_carries_a_stable_code_and_page(self):
        error = OCRProcessingError("tesseract_page_failed", page=7, detail="boom")
        self.assertEqual(error.code, "tesseract_page_failed")
        self.assertEqual(error.page, 7)
        self.assertIn("page=7", str(error))

    def test_absent_provider_raises_instead_of_returning_empty(self):
        parser = OCRParser.__new__(OCRParser)
        parser.provider = "none"
        with self.assertRaises(OCRProcessingError) as ctx:
            parser.parse_pdf(Path("x.pdf"))
        self.assertEqual(ctx.exception.code, "ocr_provider_unavailable")


class ScannedPageDetectionTests(unittest.TestCase):
    def test_pages_are_classified_individually(self):
        lengths = [2000, 5, 1800, 0]
        self.assertEqual(pdf_vision.scanned_page_indices(lengths), [1, 3])

    def test_mixed_document_is_not_classified_as_fully_raster(self):
        # The old whole-document average: (2000+5+1800+0)/4 = 951 > 50 → "text",
        # and pages 1 and 3 were then silently dropped.
        doc = FakeDoc(["x" * 2000, "x" * 5, "x" * 1800, ""])
        self.assertFalse(pdf_vision._is_raster_pdf(doc))
        self.assertEqual(
            pdf_vision.scanned_page_indices(pdf_vision._page_text_lengths(doc)), [1, 3]
        )

    def test_fully_scanned_document_is_raster(self):
        self.assertTrue(pdf_vision._is_raster_pdf(FakeDoc(["", "", ""])))


class SplitOcrMarkdownTests(unittest.TestCase):
    def test_headers_map_back_to_zero_based_indices(self):
        markdown = "## Стр. 2\n\nвторая\n\n## Стр. 4\n\nчетвёртая"
        self.assertEqual(
            pdf_vision._split_ocr_markdown(markdown, [1, 3]),
            {1: "вторая", 3: "четвёртая"},
        )

    def test_english_headers_are_accepted(self):
        self.assertEqual(
            pdf_vision._split_ocr_markdown("## Page 1\n\nfirst", [0]), {0: "first"}
        )

    def test_headerless_output_is_attributed_not_discarded(self):
        self.assertEqual(
            pdf_vision._split_ocr_markdown("плоский текст", [2]), {2: "плоский текст"}
        )

    def test_empty_output_yields_nothing(self):
        self.assertEqual(pdf_vision._split_ocr_markdown("", [0]), {})


class MixedPageRecoveryTests(unittest.TestCase):
    def _run(self, doc, scanned, local_return):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp, \
             patch.object(pdf_vision, "_vision_pages", return_value=({}, 0)), \
             patch.object(pdf_vision, "_local_ocr_pages", return_value=local_return):
            return pdf_vision._extract_mixed_pages(doc, Path(tmp.name), scanned)

    def test_recovered_scans_are_placed_in_page_order(self):
        doc = FakeDoc(["первая страница текстом", "", "третья страница текстом"])
        text, report = self._run(
            doc, [1], ({1: "распознанная вторая"}, "tesseract", "")
        )

        self.assertEqual(
            text.split("\n\n"),
            ["первая страница текстом", "распознанная вторая", "третья страница текстом"],
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["recovered_pages"], 1)
        self.assertEqual(report["unrecovered_pages"], [])

    def test_unrecovered_page_is_reported_and_emits_no_placeholder(self):
        doc = FakeDoc(["первая страница текстом", "", ""])
        text, report = self._run(
            doc, [1, 2], ({1: "распознанная вторая"}, "tesseract", "tesseract_page_failed")
        )

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["recovered_pages"], 1)
        self.assertEqual(report["unrecovered_pages"], [3])
        self.assertEqual(report["error_code"], "tesseract_page_failed")
        self.assertNotIn("Ошибка", text)
        self.assertNotIn("tesseract_page_failed", text)

    def test_total_ocr_failure_keeps_the_text_pages_and_reports_failed(self):
        doc = FakeDoc(["первая страница текстом", "", ""])
        text, report = self._run(
            doc, [1, 2], ({}, "none", "ocr_provider_unavailable")
        )

        self.assertEqual(text, "первая страница текстом")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["recovered_pages"], 0)
        self.assertEqual(report["unrecovered_pages"], [2, 3])
        self.assertEqual(report["error_code"], "ocr_provider_unavailable")


class LocalOcrErrorSurfaceTests(unittest.TestCase):
    def test_provider_error_becomes_a_code_never_page_text(self):
        class FailingParser:
            provider = "tesseract"

            def parse_pdf(self, *_args, **_kwargs):
                raise OCRProcessingError("tesseract_page_failed", page=2)

        with patch("parsers.ocr.OCRParser", return_value=FailingParser()):
            pages, provider, code = pdf_vision._local_ocr_pages(Path("x.pdf"), [1])

        self.assertEqual(pages, {})
        self.assertEqual(provider, "tesseract")
        self.assertEqual(code, "tesseract_page_failed")

    def test_absent_provider_is_reported_without_raising(self):
        class NoProvider:
            provider = "none"

        with patch("parsers.ocr.OCRParser", return_value=NoProvider()):
            pages, provider, code = pdf_vision._local_ocr_pages(Path("x.pdf"), [0])

        self.assertEqual(pages, {})
        self.assertEqual(provider, "none")
        self.assertEqual(code, "ocr_provider_unavailable")


if __name__ == "__main__":
    unittest.main()
