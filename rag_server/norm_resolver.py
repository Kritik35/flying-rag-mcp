"""Exact Norm Resolution (ENR) & Clause Extraction for FlyingRAG.

Resolves normative designations (СП, ГОСТ, ГОСТ Р, СНиП, СанПиН, ГЭСН, ФЗ)
against the actual document registry in metadata.db.
Distinguishes original standards from citing documents and derivative manuals.
Provides clause header boundary verification and context completeness checks.
Prevents false attribution of absent norms (e.g. ГЭСН).
"""
from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Tuple


@dataclass
class NormRef:
    prefix: str                 # 'СП', 'ГОСТ', 'ГОСТ Р', 'СНиП', 'СанПиН', 'ГЭСН', 'ГЭСНр', 'ГЭСНм', 'ФЗ'
    number: str                 # '7.13130', '59972', '08-01-001', '123'
    year: Optional[str] = None  # '2013', '2020', '21'
    clause: Optional[str] = None # '6.4', '8.1', '4.2.19', 'А.3'
    clause_type: Optional[str] = None # 'пункт', 'раздел', 'таблица', 'приложение'
    raw_match: str = ""


@dataclass
class ClauseMatch:
    clause_num: str
    clause_type: str
    is_header: bool             # True if match is a structural header, False if mention/citation
    context_status: str         # 'context_sufficient', 'context_partial', 'clause_mention_only'
    parent_id: str
    source_path: str
    file_name: str
    text: str
    amendment_note: str = ""


# Norm prefixes in priority order (longer patterns first to prevent 'ГОСТ' eating 'ГОСТ Р')
PREFIX_PATTERNS = [
    (r"\bГОСТ\s+Р\s+(?:ИСО\s+)?", "ГОСТ Р"),
    (r"\bГОСТ\s+", "ГОСТ"),
    (r"\bСНиП\s+", "СНиП"),
    (r"\bСанПиН\s+", "СанПиН"),
    (r"\bСП\s+", "СП"),
    (r"\bГЭСНр\s+", "ГЭСНр"),
    (r"\bГЭСНм\s+", "ГЭСНм"),
    (r"\bГЭСНп\s+", "ГЭСНп"),
    (r"\bГЭСН\s+", "ГЭСН"),
    (r"\bФЕРр\s+", "ФЕРр"),
    (r"\bФЕРм\s+", "ФЕРм"),
    (r"\bФЕР\s+", "ФЕР"),
    (r"\bТЕР\s+", "ТЕР"),
]

CLAUSE_RE = re.compile(
    r"(?:(?P<type>пункт|п\.|раздел|таблиц[аеы]|приложени[еи])\s*(?P<num>[А-Яа-я0-9]+(?:\.[0-9]+)*))",
    re.IGNORECASE
)

# Mentions/citations preceding clause numbers: "согласно п. 6.4", "в соответствии с 6.4"
CITATION_LEAD_RE = re.compile(
    r"(?:согласно|в соответствии с|по формуле|по таблице|см\.|требованиями)\s*$",
    re.IGNORECASE
)


def parse_all_norm_queries(query: str) -> List[NormRef]:
    """Extracts all normative designations found in the query string."""
    q = str(query or "").strip()
    if not q:
        return []

    clause = None
    clause_type = None
    c_match = CLAUSE_RE.search(q)
    if c_match:
        clause = c_match.group("num")
        clause_type = c_match.group("type").lower()

    found_with_pos: list[tuple[int, NormRef]] = []

    # 1. Federal Laws: 123-ФЗ, 384-ФЗ
    for fz in re.finditer(r"\b(\d{1,4})\s*-\s*ФЗ\b", q, re.IGNORECASE):
        found_with_pos.append((fz.start(), NormRef(
            prefix="ФЗ",
            number=fz.group(1),
            clause=clause,
            clause_type=clause_type,
            raw_match=fz.group(0).upper()
        )))

    # 2. Standard normative prefixes
    for pat, canonical_prefix in PREFIX_PATTERNS:
        for m in re.finditer(pat, q, re.IGNORECASE):
            rest = q[m.end():].strip()
            num_match = re.match(r"^([0-9]+(?:[\.\-][0-9]+)*)", rest)
            if num_match:
                full_num = num_match.group(1)
                parts = re.split(r"[\.\-]", full_num)
                year = None
                number = full_num
                if len(parts) >= 2:
                    last = parts[-1]
                    if len(last) == 4 and (last.startswith("19") or last.startswith("20")):
                        year = last
                        number = ".".join(parts[:-1]) if "." in full_num else "-".join(parts[:-1])
                    elif len(last) == 2 and last.isdigit() and len(parts) == 2:
                        year = last
                        number = parts[0]
                
                ref = NormRef(
                    prefix=canonical_prefix,
                    number=number,
                    year=year,
                    clause=clause,
                    clause_type=clause_type,
                    raw_match=f"{canonical_prefix} {full_num}"
                )
                if not any(x[1].prefix == ref.prefix and x[1].number == ref.number for x in found_with_pos):
                    found_with_pos.append((m.start(), ref))

    found_with_pos.sort(key=lambda x: x[0])
    return [x[1] for x in found_with_pos]


def parse_norm_query(query: str) -> Optional[NormRef]:
    """Single-norm helper (returns primary norm or first parsed)."""
    norms = parse_all_norm_queries(query)
    return norms[0] if norms else None


class NormRegistry:
    """In-memory index of canonical documents in metadata.db.
    
    Refreshes automatically when corpus_generation changes.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.corpus_generation = ""
        self.doc_records: list[dict] = []
        self._norm_map: dict[tuple[str, str], list[dict]] = {}
        self._reload_if_needed()

    def _get_current_generation(self) -> str:
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                row = con.execute("SELECT value FROM runtime_state WHERE key = 'corpus_generation'").fetchone()
                return str(row[0]) if row else "default"
            finally:
                con.close()
        except Exception:
            return "default"

    def _reload_if_needed(self):
        current_gen = self._get_current_generation()
        if self.doc_records and current_gen == self.corpus_generation:
            return

        self.corpus_generation = current_gen
        self.doc_records = []
        self._norm_map = {}

        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT file_name, source_path, dataset, is_deprecated "
                "FROM files WHERE dataset = 'normative' OR source_path LIKE '%НТД%'"
            )
            for fn, sp, ds, depr in cur.fetchall():
                norm_ref = parse_norm_query(fn)
                fn_lower = fn.lower()
                is_derivative = any(
                    m in fn_lower for m in [
                        "методические", "пособие", "рекомендации",
                        "изменения", "приказ", "внимание", "отменен"
                    ]
                )
                
                edition_year = norm_ref.year if (norm_ref and norm_ref.year) else None
                rec = {
                    "file_name": fn,
                    "source_path": sp,
                    "dataset": ds,
                    "is_deprecated": bool(depr),
                    "norm_ref": norm_ref,
                    "is_derivative": is_derivative,
                    "edition_year": edition_year,
                    "amendments": [],
                    "_edition_inspected": False,
                }
                self.doc_records.append(rec)
                if norm_ref:
                    key = (norm_ref.prefix, norm_ref.number)
                    if key not in self._norm_map:
                        self._norm_map[key] = []
                    self._norm_map[key].append(rec)
        finally:
            con.close()

    def _inspect_edition_if_needed(self, rec: dict):
        if rec.get("_edition_inspected"):
            return
        rec["_edition_inspected"] = True
        sp = rec["source_path"]
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                cur = con.cursor()
                cur.execute(
                    "SELECT parent_text FROM parent_chunks WHERE source_path = ? ORDER BY parent_id ASC LIMIT 2",
                    (sp,)
                )
                parents = [r[0] for r in cur.fetchall()]
                combined_intro = " ".join(parents)
                if combined_intro:
                    if not rec.get("edition_year"):
                        dates = re.findall(r"\b(?:от\s+)?\d{1,2}\s+[а-я]+\s+(\d{4})\s*г?\.", combined_intro, re.IGNORECASE)
                        if dates:
                            rec["edition_year"] = dates[0]
                    amends = re.findall(r"(?:Изменени[яе]\s*N?\s*\d+|в\s*ред\.\s*Изменени[яе]\s*N?\s*\d+[^)]*)", combined_intro, re.IGNORECASE)
                    rec["amendments"] = [a.strip() for a in amends[:3]]
            finally:
                con.close()
        except Exception:
            pass

    def resolve(self, query: str) -> Tuple[Optional[NormRef], str, list[dict]]:
        """Resolves a query against canonical normative documents.
        
        Returns:
            (target_norm, status, candidates)
            status in:
              - "no_norm"
              - "found"
              - "norm_absent_from_corpus"
              - "ambiguous_query"
        """
        self._reload_if_needed()
        all_norms = parse_all_norm_queries(query)
        if not all_norms:
            return None, "no_norm", []

        if len(all_norms) > 1:
            # Multiple distinct norm ciphers mentioned in one query
            # Check if all exist or if one is primary
            pass

        for target in all_norms:
            key = (target.prefix, target.number)
            candidates = self._norm_map.get(key, [])
            if candidates:
                for c in candidates:
                    self._inspect_edition_if_needed(c)
                def sort_key(doc):
                    is_deriv = doc["is_derivative"]
                    ed_yr = doc.get("edition_year") or ""
                    target_yr_match = (ed_yr == target.year) if (target.year and ed_yr) else True
                    not_depr = not doc["is_deprecated"]
                    return (not is_deriv, target_yr_match, not_depr, ed_yr)
                sorted_candidates = sorted(candidates, key=sort_key, reverse=True)
                return target, "found", sorted_candidates

        return all_norms[0], "norm_absent_from_corpus", []

    def extract_clause_from_doc(self, source_path: str, clause_num: str, clause_type: str | None = None) -> List[ClauseMatch]:
        """Extracts and verifies specific clause boundaries in the given document."""
        c_escaped = re.escape(clause_num)
        # Boundary pattern: must start at line start or clear structural delimiter
        header_pattern = re.compile(
            rf"(?:^|\n)\s*(?:(?:п\.|пункт|раздел|таблица|приложение)\s*)?{c_escaped}(?:\.|\s|[А-Яа-я]|\b)",
            re.IGNORECASE
        )
        
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT parent_id, parent_text FROM parent_chunks WHERE source_path = ?",
                (source_path,)
            )
            rows = cur.fetchall()
        finally:
            con.close()

        results: list[ClauseMatch] = []
        for p_id, p_text in rows:
            m = header_pattern.search(p_text)
            if m:
                pos = m.start()
                lead_snippet = p_text[max(0, pos - 40):pos]
                is_citation = bool(CITATION_LEAD_RE.search(lead_snippet))
                
                # Check completeness: does text contain truncated formula or cut-off table?
                is_partial = False
                if re.search(r"\(\s*[А-Я0-9]\.\s*$", p_text) or p_text.rstrip().endswith(("...", "…", "в ред.")):
                    is_partial = True

                status = "context_sufficient"
                if is_citation:
                    status = "clause_mention_only"
                elif is_partial:
                    status = "context_partial"

                # Check amendments in clause
                amend_note = ""
                am_match = re.search(r"\((?:п\.\s*" + c_escaped + r"\s*)?в\s*ред\.\s*Изменени[яе]\s*N?\s*\d+[^)]*\)", p_text, re.IGNORECASE)
                if am_match:
                    amend_note = am_match.group(0)

                results.append(ClauseMatch(
                    clause_num=clause_num,
                    clause_type=clause_type or "пункт",
                    is_header=not is_citation,
                    context_status=status,
                    parent_id=p_id,
                    source_path=source_path,
                    file_name=Path(source_path).name,
                    text=p_text,
                    amendment_note=amend_note
                ))

        # Prioritize true headers over mentions
        results.sort(key=lambda c: (c.is_header, c.context_status == "context_sufficient"), reverse=True)
        return results


_CACHED_REGISTRY: Optional[NormRegistry] = None


def get_norm_registry(db_path: str | Path) -> NormRegistry:
    global _CACHED_REGISTRY
    if _CACHED_REGISTRY is None or _CACHED_REGISTRY.db_path != str(db_path):
        _CACHED_REGISTRY = NormRegistry(db_path)
    return _CACHED_REGISTRY
