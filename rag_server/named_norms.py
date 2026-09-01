"""Recognise a norm the query names outright.

A designation is document *identity*, and the lexical channel reads chunk text.
Measured on the corpus: СП 484.1311500 carries its own designation in 2% of its
chunks, while 93 other documents cite it — so a query that spells the number out
retrieves everything that references the norm and hardly ever the norm itself.
It sat at rank 40 for a query naming it.

What is extracted here is used as a document filter, so the surrounding
retrieval can run one extra restricted read and put the named document's own
best passages into the pool. Fusion still decides where they land.
"""
from __future__ import annotations

import re

# Written the way file names are: "СП 484.1311500.2020.docx", "ГОСТ Р 59972-2021".
MARKERS = {
    "сп": "СП",
    "снип": "СНиП",
    "гост": "ГОСТ",
    "гост р": "ГОСТ Р",
    "санпин": "СанПиН",
    "всн": "ВСН",
    "рд": "РД",
    "сто": "СТО",
}

_MARKER_ALT = "гост\\s*р|гост|снип|санпин|всн|сп|сто|рд"
_DESIGNATION_RE = re.compile(
    rf"(?<![а-яa-z0-9])({_MARKER_ALT})\s*№?\s*(\d+(?:[.\-]\d+)*)",
    re.IGNORECASE,
)
# 123-ФЗ, 384-ФЗ — the number carries the identity, the suffix marks it as one.
_FEDERAL_LAW_RE = re.compile(r"(?<![\w.])(\d{1,4})\s*-\s*фз(?![\w])", re.IGNORECASE)


def _canonical_marker(raw: str) -> str:
    key = re.sub(r"\s+", " ", raw.casefold()).strip()
    return MARKERS.get(key, MARKERS.get(key.replace(" ", ""), raw.upper()))


def extract_norm_designations(query: str) -> list[str]:
    """Designations named in the query, in order, without duplicates.

    A bare number is only a designation when a marker introduces it: "расход 60
    м3/ч" must not drag in СП 60, and "пункт 7.4.1" is a reference inside a
    document, not the name of one.
    """
    text = re.sub(r"\s+", " ", str(query or "").replace("ё", "е"))
    found: list[str] = []

    for match in _DESIGNATION_RE.finditer(text):
        designation = f"{_canonical_marker(match.group(1))} {match.group(2)}"
        if designation not in found:
            found.append(designation)

    for match in _FEDERAL_LAW_RE.finditer(text):
        designation = f"{match.group(1)}-ФЗ"
        if designation not in found:
            found.append(designation)

    return found
