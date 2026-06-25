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

    def parse_pdf(self, pdf_path: Path) -> str:
        logger.info(f'[OCR] Parsing PDF with provider: {self.provider}')
        if self.provider == 'mlx':
            try:
                from mlx_vlm import load, generate
                from mlx_vlm.prompt_utils import apply_chat_template
                import pypdfium2 as pdfium
                
                model_id = 'mlx-community/GLM-OCR-4bit'
                model, processor = load(model_id)
                doc = pdfium.PdfDocument(str(pdf_path))
                pages_md = []
                for idx in range(len(doc)):
                    page = doc[idx]
                    bitmap = page.render(scale=150/72.0)
                    pil_img = bitmap.to_pil()
                    formatted_prompt = apply_chat_template(
                        processor, model.config, 'Text Recognition:', num_images=1
                    )
                    res = generate(model, processor, prompt=formatted_prompt, image=pil_img, temperature=0.0, max_tokens=1024)
                    text = res.text if hasattr(res, 'text') else res
                    pages_md.append(f'## Стр. {idx+1}\n\n{text}')
                doc.close()
                return '\n\n'.join(pages_md)
            except Exception as e:
                logger.error(f'[OCR] mlx error: {e}')
                return ''
        elif self.provider == 'tesseract':
            try:
                import pytesseract
                import pypdfium2 as pdfium
                tesseract_cmd = _find_tesseract_cmd()
                if not tesseract_cmd:
                    logger.error('[OCR] tesseract executable not found')
                    return ''
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

                doc = pdfium.PdfDocument(str(pdf_path))
                pages_text = []
                for idx in range(len(doc)):
                    page = doc[idx]
                    bitmap = page.render(scale=150/72.0)
                    pil_img = bitmap.to_pil()
                    text = pytesseract.image_to_string(pil_img, lang='rus+eng')
                    pages_text.append(f'## Стр. {idx+1}\n\n{text}')
                doc.close()
                return '\n\n'.join(pages_text)
            except Exception as e:
                logger.error(f'[OCR] tesseract error: {e}')
                return ''
        return ''
