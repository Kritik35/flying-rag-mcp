from __future__ import annotations

import unittest
import tempfile
import os
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


class PdfOcrPipelineTests(unittest.TestCase):
    def test_dispatcher_keeps_pdf_on_guarded_vision_pipeline(self):
        from parsers.dispatcher import get_parser

        parser = get_parser(Path("scan.pdf"))

        self.assertEqual(parser.__module__, "parsers.pdf_vision")

    def test_raster_pdf_uses_local_ocr_fallback_when_vision_returns_empty(self):
        from parsers import pdf_vision

        class FakePage:
            def get_text(self, *_args, **_kwargs):
                return ""

        class FakeDoc:
            def __init__(self):
                self.pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __len__(self):
                return len(self.pages)

            def __iter__(self):
                return iter(self.pages)

            def __getitem__(self, item):
                return self.pages[item]

        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp, \
             patch.object(pdf_vision.fitz, "open", return_value=FakeDoc()), \
             patch.object(pdf_vision, "_extract_scanned_pages", return_value=""), \
             patch("parsers.ocr.OCRParser") as ocr_cls:
            ocr_cls.return_value.provider = "tesseract"
            ocr_cls.return_value.parse_pdf.return_value = "OCR TEXT"

            parsed = pdf_vision.parse(Path(tmp.name))

        self.assertEqual(parsed.text, "OCR TEXT")
        self.assertEqual(parsed.extra["method"], "ocr_tesseract")

    def test_tesseract_provider_requires_executable_on_windows(self):
        with patch("sys.platform", "win32"), \
             patch("shutil.which", return_value=None), \
             patch("os.path.exists", return_value=False):
            from parsers.ocr import OCRParser

            self.assertEqual(OCRParser().provider, "none")

    def test_tesseract_provider_can_use_env_command_on_windows(self):
        fake_pytesseract = SimpleNamespace(pytesseract=SimpleNamespace(tesseract_cmd=None))

        with patch("sys.platform", "win32"), \
             patch.dict(os.environ, {"TESSERACT_CMD": r"C:\Tools\Tesseract-OCR\tesseract.exe"}, clear=False), \
             patch.dict(sys.modules, {"pytesseract": fake_pytesseract}), \
             patch("shutil.which", return_value=None), \
             patch("os.path.exists", return_value=True):
            from parsers.ocr import OCRParser

            self.assertEqual(OCRParser().provider, "tesseract")


if __name__ == "__main__":
    unittest.main()
