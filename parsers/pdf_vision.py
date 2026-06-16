from __future__ import annotations
"""
parsers/pdf_vision.py

PDF parser for flying-rag:
  1. Text extraction via fitz (PyMuPDF) — all pages
  2. Table extraction: PyMuPDF find_tables() → pdfplumber fallback
  3. Vision LLM (Gemini) only for scanned pages (no text layer)

Replaces the prototype that processed only page 0.
"""
import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import fitz  # PyMuPDF
    _FITZ_OK = True
except ImportError:
    _FITZ_OK = False

_WS_RE = re.compile(r"\s{3,}")

MAX_TEXT_PAGES = int(os.getenv("PDF_TEXT_MAX_PAGES", "300"))
MAX_TABLE_PAGES = int(os.getenv("PDF_TABLE_MAX_PAGES", "50"))
MAX_TABLES_TOTAL = int(os.getenv("PDF_TABLE_MAX_TABLES", "100"))
VISION_MAX_PAGES = int(os.getenv("PDF_VISION_MAX_PAGES", "5"))
# Chars per page below this → treat as scanned
_MIN_CHARS_PER_PAGE = 50


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


# ─── raster detection ────────────────────────────────────────────────────────

def _is_raster_pdf(doc) -> bool:
    """True if PDF has no text layer (scanned)."""
    if not doc:
        return True
    total = sum(len(page.get_text("text")) for page in doc)
    return total < _MIN_CHARS_PER_PAGE * len(doc)


# ─── text extraction ──────────────────────────────────────────────────────────

def _extract_text_fitz(doc) -> str:
    """Extract full text from all pages via fitz."""
    parts: list[str] = []
    for page in doc:
        t = page.get_text("text") or ""
        t = _WS_RE.sub(" ", t).strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)


# ─── table extraction ─────────────────────────────────────────────────────────

def _clean_table(raw: list) -> list[str]:
    """Convert raw table rows (list of list) into text lines."""
    lines: list[str] = []
    for row in raw or []:
        cells = [str(c or "").strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


def _extract_tables_fitz(doc) -> list[str]:
    """Extract tables from PDF using PyMuPDF find_tables()."""
    table_lines: list[str] = []
    tables_found = 0
    for page_no in range(min(MAX_TABLE_PAGES, len(doc))):
        page = doc[page_no]
        if not page.get_text("text").strip():
            continue
        finder = getattr(page, "find_tables", None)
        if not finder:
            continue
        try:
            tables = finder()
        except Exception:
            continue
        for table in (getattr(tables, "tables", []) or []):
            try:
                lines = _clean_table(table.extract())
                if lines:
                    table_lines.extend(lines)
                    tables_found += 1
            except Exception:
                continue
            if tables_found >= MAX_TABLES_TOTAL:
                return table_lines
    return table_lines


def _extract_tables_pdfplumber(path: Path, doc=None) -> list[str]:
    """Fallback table extraction via pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return []

    table_lines: list[str] = []
    tables_found = 0
    with pdfplumber.open(str(path)) as pdf:
        for idx, page in enumerate(pdf.pages[:MAX_TABLE_PAGES]):
            # Skip page if text is too dense (potential corrupt/scanned text layer hang)
            if doc is not None and idx < len(doc):
                try:
                    fitz_page = doc[idx]
                    fitz_text = fitz_page.get_text("text") or ""
                    if len(fitz_text) > 10000:
                        continue
                except Exception:
                    pass
            else:
                try:
                    p_text = page.extract_text() or ""
                    if len(p_text) > 10000:
                        continue
                except Exception:
                    pass

            try:
                for raw in (page.extract_tables() or []):
                    lines = _clean_table(raw)
                    if lines:
                        table_lines.extend(lines)
                        tables_found += 1
                    if tables_found >= MAX_TABLES_TOTAL:
                        return table_lines
            except Exception:
                continue
    return table_lines


# ─── Vision API (for scanned pages only) ──────────────────────────────────────

def _render_page_b64(page) -> str:
    pix = page.get_pixmap(dpi=150)
    return base64.b64encode(pix.tobytes("png")).decode()


def _call_vision_llm(b64: str) -> str:
    """Call Gemini Vision API on a scanned page image. Returns text."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return ""

    import requests
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/gemini-2.5-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": "Extract all text from this document page. Return only the text, preserve structure."},
                {"inline_data": {"mime_type": "image/png", "data": b64}},
            ]
        }],
    }
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return ""


def _extract_scanned_pages(doc, n_pages: int = VISION_MAX_PAGES) -> str:
    """OCR scanned pages via Vision LLM (limited to first n_pages)."""
    parts: list[str] = []
    for page in doc[:n_pages]:
        if len(page.get_text("text")) >= _MIN_CHARS_PER_PAGE:
            continue  # has text, skip Vision
        b64 = _render_page_b64(page)
        text = _call_vision_llm(b64)
        if text:
            parts.append(text.strip())
    return "\n\n".join(parts)


# ─── main parse ───────────────────────────────────────────────────────────────

def parse(path: Path) -> ParsedDocument:
    from parsers.table_normalizer import normalize_matrix, enrich_and_validate

    try:
        created_at, modified_at = _timestamps(path)
    except Exception as e:
        return ParsedDocument(
            source_path=str(path), file_name=path.name, format="pdf",
            text="", created_at="", modified_at="",
            extra={"error": str(e)},
        )

    if not _FITZ_OK:
        return ParsedDocument(
            source_path=str(path), file_name=path.name, format="pdf",
            text="", created_at=created_at, modified_at=modified_at,
            extra={"error": "PyMuPDF (fitz) not installed"},
        )

    text_parts: list[str] = []
    page_count = 0
    is_raster = False
    tables_extracted = 0
    extractor = "fitz"

    try:
        with fitz.open(str(path)) as doc:
            page_count = len(doc)
            is_raster = _is_raster_pdf(doc)

            if is_raster:
                # Scanned PDF: Vision API for first N pages
                ocr_text = _extract_scanned_pages(doc)
                if ocr_text:
                    text_parts.append(ocr_text)
            else:
                # Text PDF: extract all pages
                main_text = _extract_text_fitz(doc)
                if main_text:
                    text_parts.append(main_text)

                # Tables via fitz find_tables
                table_lines = _extract_tables_fitz(doc)
                if not table_lines:
                    # pdfplumber fallback
                    table_lines = _extract_tables_pdfplumber(path, doc=doc)
                    if table_lines:
                        extractor = "pdfplumber"

                if table_lines:
                    tables_extracted = len(table_lines)
                    # Also textualize table rows through normalizer if vision data present
                    text_parts.append("\n".join(table_lines))

    except Exception as e:
        return ParsedDocument(
            source_path=str(path), file_name=path.name, format="pdf",
            text="", created_at=created_at, modified_at=modified_at,
            extra={"error": str(e)},
        )

    full_text = "\n\n".join(p for p in text_parts if p.strip())

    return ParsedDocument(
        source_path=str(path),
        file_name=path.name,
        format="pdf",
        text=full_text,
        created_at=created_at,
        modified_at=modified_at,
        extra={
            "pages": page_count,
            "is_raster": is_raster,
            "tables_extracted": tables_extracted,
            "extractor": extractor,
            "method": "vision_llm" if is_raster else "fitz",
        },
    )
