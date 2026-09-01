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
# Chars per page below this → that *page* is scanned. The decision is per page,
# not per document: a mixed PDF whose first pages carry a text layer used to be
# classified as text, and its scanned pages were then dropped without a trace.
_MIN_CHARS_PER_PAGE = int(os.getenv("PDF_MIN_CHARS_PER_PAGE", "50"))


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

def _page_text_lengths(doc) -> list[int]:
    return [len(page.get_text("text") or "") for page in doc]


def scanned_page_indices(page_lengths: list[int]) -> list[int]:
    """0-based indices of pages whose text layer is too thin to be real text.

    Per page, deliberately. The old whole-document average let a 200-page PDF
    with ten text pages read as "text", silently discarding the other 190.
    """
    return [i for i, n in enumerate(page_lengths) if n < _MIN_CHARS_PER_PAGE]


def _is_raster_pdf(doc) -> bool:
    """True if the PDF has no usable text layer at all (fully scanned)."""
    if not doc:
        return True
    lengths = _page_text_lengths(doc)
    if not lengths:
        return True
    return len(scanned_page_indices(lengths)) == len(lengths)


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
    if os.environ.get("DISABLE_PDFPLUMBER") or os.environ.get("PDF_DISABLE_PDFPLUMBER"):
        return []
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


def _vision_pages(doc, page_indices: list[int]) -> tuple[dict[int, str], int]:
    """Vision-OCR the given pages, capped at VISION_MAX_PAGES (paid remote call).

    Returns ``(text_by_page_index, attempted_count)``.
    """
    out: dict[int, str] = {}
    attempted = 0
    for idx in page_indices[:VISION_MAX_PAGES]:
        attempted += 1
        try:
            text = _call_vision_llm(_render_page_b64(doc[idx]))
        except Exception:
            text = ""
        if text and text.strip():
            out[idx] = text.strip()
    return out, attempted


def _local_ocr_pages(path: Path, page_indices: list[int]) -> tuple[dict[int, str], str, str]:
    """Local OCR for the given pages. Returns (text_by_index, provider, error_code).

    A provider failure surfaces as an error code — never as placeholder text.
    Local OCR has no page cap: it is the path that must not lose pages.
    """
    try:
        from parsers.ocr import OCRParser, OCRProcessingError
    except Exception as e:
        return {}, "none", f"ocr_import_failed: {e}"

    try:
        ocr = OCRParser()
    except Exception as e:
        return {}, "none", f"ocr_init_failed: {e}"
    if ocr.provider == "none":
        return {}, "none", "ocr_provider_unavailable"

    try:
        markdown = ocr.parse_pdf(path, pages=page_indices)
    except OCRProcessingError as e:
        return {}, ocr.provider, e.code
    except Exception as e:
        return {}, ocr.provider, f"ocr_failed: {type(e).__name__}: {e}"

    return _split_ocr_markdown(markdown, page_indices), ocr.provider, ""


_OCR_PAGE_HEADER_RE = re.compile(r"^##\s*(?:Стр\.?|Page)\s*(\d+)\s*$", re.MULTILINE)


def _split_ocr_markdown(markdown: str, fallback_indices: list[int]) -> dict[int, str]:
    """Map ``## Стр. N`` blocks back onto 0-based page indices."""
    text = str(markdown or "")
    if not text.strip():
        return {}
    matches = list(_OCR_PAGE_HEADER_RE.finditer(text))
    if not matches:
        # No headers (a mocked or minimal provider): treat the whole result as
        # belonging to the first requested page rather than dropping it.
        return {fallback_indices[0]: text.strip()} if fallback_indices else {}
    out: dict[int, str] = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            out[int(match.group(1)) - 1] = body
    return out


def _extract_mixed_pages(doc, path: Path, scanned: list[int]) -> tuple[str, dict]:
    """Assemble a mixed PDF in page order, OCR-ing only the pages that need it.

    Returns ``(text, report)``. The report names how many scanned pages were
    recovered and how many were not, so a partially readable file is visible as
    partial instead of passing for complete.
    """
    vision_text, vision_attempted = _vision_pages(doc, scanned)
    remaining = [i for i in scanned if i not in vision_text]
    local_text: dict[int, str] = {}
    provider, error_code = "none", ""
    if remaining:
        local_text, provider, error_code = _local_ocr_pages(path, remaining)

    recovered = {**vision_text, **local_text}
    parts: list[str] = []
    for idx, page in enumerate(doc):
        if idx in recovered:
            parts.append(recovered[idx])
            continue
        # An unrecovered scan contributes whatever thin text layer it has and
        # nothing else — never a placeholder. Keeping it makes this path
        # strictly non-lossy against the previous text-only extraction.
        text = _WS_RE.sub(" ", (page.get_text("text") or "")).strip()
        if text:
            parts.append(text)

    missed = [i for i in scanned if i not in recovered]
    if recovered and vision_text:
        method = "vision_llm" if not local_text else f"vision_llm+ocr_{provider}"
    elif recovered:
        method = f"ocr_{provider}"
    else:
        method = "fitz"

    report = {
        "status": "ok" if not missed else ("partial" if recovered else "failed"),
        "scanned_pages": len(scanned),
        "recovered_pages": len(recovered),
        "unrecovered_pages": [i + 1 for i in missed],
        "vision_attempted": vision_attempted,
        "method": method,
    }
    if error_code:
        report["error_code"] = error_code
    return "\n\n".join(parts), report


def _extract_scanned_pages_local(path: Path) -> tuple[str, str]:
    """OCR a fully scanned PDF with a local provider when Vision is unavailable."""
    try:
        from parsers.ocr import OCRParser, OCRProcessingError

        ocr = OCRParser()
        if ocr.provider == "none":
            return "", "none"
        try:
            return ocr.parse_pdf(path), ocr.provider
        except OCRProcessingError:
            # Fail closed: no text is honest, an error string in the index is not.
            return "", ocr.provider
    except Exception:
        return "", "none"


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
    method = "fitz"
    ocr_report: dict = {"status": "not_needed"}

    try:
        with fitz.open(str(path)) as doc:
            page_count = len(doc)
            is_raster = _is_raster_pdf(doc)

            if is_raster:
                # Scanned PDF: Vision API for first N pages
                ocr_text = _extract_scanned_pages(doc)
                if ocr_text:
                    method = "vision_llm"
                else:
                    ocr_text, local_provider = _extract_scanned_pages_local(path)
                    if ocr_text:
                        method = f"ocr_{local_provider}"
                if ocr_text:
                    text_parts.append(ocr_text)
                    ocr_report = {"status": "ok", "scanned_pages": page_count}
                else:
                    ocr_report = {
                        "status": "failed",
                        "scanned_pages": page_count,
                        "recovered_pages": 0,
                        "error_code": "ocr_produced_no_text",
                    }
            else:
                page_lengths = _page_text_lengths(doc)
                scanned = scanned_page_indices(page_lengths)
                if scanned:
                    # Mixed document: recover the scanned pages and keep the
                    # whole file in page order, rather than emitting only the
                    # pages that happened to carry a text layer.
                    main_text, ocr_report = _extract_mixed_pages(doc, path, scanned)
                    if ocr_report.get("recovered_pages"):
                        method = ocr_report.get("method", method)
                else:
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
            "method": method,
            "ocr": ocr_report,
        },
    )
