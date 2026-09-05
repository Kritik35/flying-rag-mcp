"""Trace a quote back to the page it came from.

A citation that cannot say where it sits is hard to act on: an engineer holding
"предел огнестойкости не менее EI 30" needs the page to put in a remark. The
store has no page field, and adding one means reindexing 1.25M chunks, so the
page is looked up in the source document when someone asks for it.

Measured on 40 stored chunks before this was built: the page was found for all
40, 39 of them on a twelve-word probe, median 694ms per lookup. That is too
slow to attach to every result of every search — hence a separate call rather
than another field — and fast enough to answer when it is actually wanted.

Exact search is the wrong tool on its own. Chunk text has been through a parser
that collapses whitespace and drops hyphenation, so it rarely matches the page
byte for byte; and a chunk usually starts mid-sentence, where a split fell. The
ladder below therefore skips the first few words and shortens the needle until
something lands.
"""
from __future__ import annotations

import os
import re

PROBE_LENGTHS = (12, 8, 5)
HEAD_SKIP = 3
MAX_PAGES = 400
MAX_FILE_MB = 60.0
MAX_HITS = 3


def probes(text: str) -> list[str]:
    """Needles to try, longest first."""
    words = re.sub(r"\s+", " ", str(text or "")).strip().split()
    if not words:
        return []
    ladder = []
    for length in PROBE_LENGTHS:
        if len(words) >= length:
            start = min(HEAD_SKIP, len(words) - length)
            ladder.append(" ".join(words[start:start + length]))
    if not ladder:
        ladder.append(" ".join(words))
    return ladder


def _is_allowed(path: str, allowed) -> bool:
    """Only documents the index knows about may be opened."""
    if allowed is None:
        return True
    target = os.path.normcase(os.path.abspath(path))
    return any(os.path.normcase(os.path.abspath(p)) == target for p in allowed)


def locate_quote(source_path: str, quote: str, allowed=None,
                 max_pages: int = MAX_PAGES) -> dict:
    """Pages of `source_path` carrying `quote`, or why they could not be found.

    `allowed` is the set of paths the index holds. Without it any file on the
    machine could be read through this call.
    """
    answer = {"source_path": source_path, "pages": [], "status": "not_found",
              "probe_words": 0}

    if not _is_allowed(source_path, allowed):
        answer["status"] = "not_indexed"
        return answer
    if not source_path.lower().endswith(".pdf"):
        # Only PDFs have pages to point at; a spreadsheet has sheets and rows.
        answer["status"] = "unsupported_format"
        return answer
    if not os.path.exists(source_path):
        answer["status"] = "missing"
        return answer
    if os.path.getsize(source_path) > MAX_FILE_MB * 1024 ** 2:
        answer["status"] = "too_large"
        return answer

    try:
        import fitz
    except Exception as e:
        answer["status"] = f"unavailable: {type(e).__name__}"
        return answer

    try:
        doc = fitz.open(source_path)
    except Exception as e:
        answer["status"] = f"unreadable: {type(e).__name__}"
        return answer

    try:
        answer["page_count"] = doc.page_count
        for needle in probes(quote):
            hits = []
            for index, page in enumerate(doc):
                if index >= max_pages:
                    break
                try:
                    if page.search_for(needle):
                        hits.append(index + 1)
                        if len(hits) >= MAX_HITS:
                            break
                except Exception:
                    continue
            if hits:
                answer.update(pages=hits, status="found",
                              probe_words=len(needle.split()))
                return answer
    finally:
        doc.close()

    return answer
