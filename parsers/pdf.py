from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ParsedDocument:
    source_path: str
    file_name: str
    format: str
    text: str
    created_at: str
    modified_at: str
    extra: dict = field(default_factory=dict)


def _timestamps(path: Path) -> tuple[str, str]:
    stat = path.stat()
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return fmt(stat.st_ctime), fmt(stat.st_mtime)


def _parse_markitdown(path: Path) -> tuple[str, int]:
    try:
        from markitdown import MarkItDown
        import fitz
        md = MarkItDown()
        result = md.convert(str(path))
        text = result.text_content
        with fitz.open(str(path)) as doc:
            page_count = len(doc)
        return text, page_count
    except Exception:
        return "", 0


def _parse_pymupdf(path: Path) -> tuple[str, int]:
    import fitz
    with fitz.open(str(path)) as doc:
        page_count = len(doc)
        text = "\n".join(page.get_text() for page in doc)
    return text, page_count


def _extract_tables_pdfplumber(path: Path) -> str:
    try:
        import pdfplumber
        rows_all = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        row_text = " | ".join(
                            str(cell).strip() if cell is not None else "" for cell in row
                        )
                        rows_all.append(row_text)
                    rows_all.append("")
        return "\n".join(rows_all).strip()
    except Exception:
        return ""


def parse(path: Path) -> ParsedDocument:
    try:
        created_at, modified_at = _timestamps(path)
    except Exception as e:
        return ParsedDocument(
            source_path=str(path), file_name=path.name, format="pdf",
            text="", created_at="", modified_at="", extra={"error": str(e)}
        )
    try:
        text, page_count = _parse_pymupdf(path)
        method = "pymupdf"
        if len(text.strip()) <= 100:
            text, page_count = _parse_markitdown(path)
            method = "markitdown"
        
        if len(text.strip()) <= 100:
            try:
                from parsers.ocr import OCRParser
                ocr = OCRParser()
                if ocr.provider != "none":
                    ocr_text = ocr.parse_pdf(path)
                    if ocr_text.strip():
                        text = ocr_text
                        method = f"ocr_{ocr.provider}"
            except Exception as ocr_err:
                print(f"[PDF_PARSER] OCR fallback failed: {ocr_err}")
                
        tables_text = _extract_tables_pdfplumber(path)
        if tables_text:
            text = text + "\n\n[TABLES]\n" + tables_text
        extra = {"pages": page_count, "method": method, "has_tables": bool(tables_text)}
    except Exception as e:
        text = ""
        extra = {"error": str(e)}
    return ParsedDocument(
        source_path=str(path), file_name=path.name, format="pdf",
        text=text, created_at=created_at, modified_at=modified_at, extra=extra
    )


if __name__ == "__main__":
    try:
        from markitdown import MarkItDown
        print("OK markitdown import")
    except ImportError as e:
        print(f"WARN markitdown not installed: {e}")
    try:
        import fitz
        print("OK pymupdf import")
    except ImportError as e:
        print(f"WARN pymupdf not installed: {e}")
    print("parsers/pdf.py ready")
