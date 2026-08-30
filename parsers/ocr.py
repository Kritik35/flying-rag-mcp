from __future__ import annotations
import sys
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_WINDOWS_TESSERACT_PATHS = (
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
)


class OCRProcessingError(RuntimeError):
    """OCR could not produce text for a page.

    Fail closed with a stable machine-readable code. The alternative — the old
    behaviour — was to return the error message as if it were page text, which
    then got chunked, embedded and served as evidence.
    """

    def __init__(self, code: str, page: int | None = None, detail: str = ""):
        self.code = code
        self.page = page
        self.detail = detail
        parts = [code]
        if page is not None:
            parts.append(f"page={page}")
        if detail:
            parts.append(detail)
        super().__init__(" ".join(parts))


def _find_tesseract_cmd() -> str | None:
    env_cmd = os.getenv('TESSERACT_CMD')
    if env_cmd and os.path.exists(env_cmd):
        return env_cmd

    cmd = shutil.which('tesseract')
    if cmd:
        return cmd
    if sys.platform == 'win32':
        for path in _WINDOWS_TESSERACT_PATHS:
            if os.path.exists(path):
                return path
    return None


def _page_indices(doc_len: int, pages) -> list[int]:
    """Normalize a page selection to sorted, in-range 0-based indices."""
    if pages is None:
        return list(range(doc_len))
    return sorted({int(p) for p in pages if 0 <= int(p) < doc_len})


class OCRParser:
    def __init__(self):
        self.provider = 'none'
        if sys.platform == 'darwin':
            try:
                import mlx.core
                import mlx_vlm
                self.provider = 'mlx'
            except ImportError:
                pass
        if self.provider == 'none':
            try:
                import pytesseract
                tesseract_cmd = _find_tesseract_cmd()
                if tesseract_cmd:
                    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
                    self.provider = 'tesseract'
            except ImportError:
                pass

    def parse_pdf(self, pdf_path: Path, pages=None) -> str:
        """OCR the given pages (all of them when ``pages`` is None).

        Raises :class:`OCRProcessingError` instead of returning a placeholder,
        so a failure can never enter the index as text.
        """
        logger.info(f'[OCR] Parsing PDF with provider: {self.provider}')
        if self.provider == 'mlx':
            return self._parse_mlx(pdf_path, pages)
        if self.provider == 'tesseract':
            return self._parse_tesseract(pdf_path, pages)
        raise OCRProcessingError('ocr_provider_unavailable')

    def _parse_mlx(self, pdf_path: Path, pages=None) -> str:
        try:
            from mlx_vlm import load, generate
            from mlx_vlm.prompt_utils import apply_chat_template
            import pypdfium2 as pdfium
        except Exception as e:
            raise OCRProcessingError('mlx_vision_import_failed', detail=str(e)) from None

        try:
            model_id = 'mlx-community/GLM-OCR-4bit'
            model, processor = load(model_id)
        except Exception as e:
            raise OCRProcessingError('mlx_vision_load_failed', detail=str(e)) from None

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            pages_md = []
            for idx in _page_indices(len(doc), pages):
                try:
                    page = doc[idx]
                    bitmap = page.render(scale=150 / 72.0)
                    pil_img = bitmap.to_pil()
                    formatted_prompt = apply_chat_template(
                        processor, model.config, 'Text Recognition:', num_images=1
                    )
                    res = generate(
                        model, processor, prompt=formatted_prompt, image=pil_img,
                        temperature=0.0, max_tokens=1024,
                    )
                    text = res.text if hasattr(res, 'text') else res
                except Exception as e:
                    raise OCRProcessingError(
                        'mlx_vision_generate_failed', page=idx + 1, detail=str(e)
                    ) from None
                pages_md.append(f'## Стр. {idx + 1}\n\n{text}')
            return '\n\n'.join(pages_md)
        finally:
            doc.close()

    def _parse_tesseract(self, pdf_path: Path, pages=None) -> str:
        try:
            import pytesseract
            import pypdfium2 as pdfium
        except Exception as e:
            raise OCRProcessingError('tesseract_import_failed', detail=str(e)) from None

        tesseract_cmd = _find_tesseract_cmd()
        if not tesseract_cmd:
            raise OCRProcessingError('tesseract_executable_missing')
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            pages_text = []
            for idx in _page_indices(len(doc), pages):
                try:
                    page = doc[idx]
                    bitmap = page.render(scale=150 / 72.0)
                    pil_img = bitmap.to_pil()
                    text = pytesseract.image_to_string(pil_img, lang='rus+eng')
                except Exception as e:
                    raise OCRProcessingError(
                        'tesseract_page_failed', page=idx + 1, detail=str(e)
                    ) from None
                pages_text.append(f'## Стр. {idx + 1}\n\n{text}')
            return '\n\n'.join(pages_text)
        finally:
            doc.close()
