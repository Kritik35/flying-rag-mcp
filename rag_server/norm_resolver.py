"""Exact Norm Resolution (ENR) & Structural Clause Extraction for FlyingRAG.

Resolves normative designations (СП, ГОСТ, ГОСТ Р, СНиП, СанПиН, ГЭСН, ФЗ)
against the actual document registry in metadata.db.
Distinguishes original standards from citing documents and derivative manuals.
Provides clause header boundary verification, table/appendix support, and context completeness checks.
Prevents false attribution of absent norms (e.g. ГЭСН, absent SP).
Supports independent resolution of multi-norm queries.
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
    context_status: str         # 'context_sufficient', 'context_partial', 'clause_mention_only', 'toc_entry'
    parent_id: str
    source_path: str
    file_name: str
    text: str
    amendment_note: str = ""


@dataclass
class SingleNormResolution:
    target: NormRef
    status: str                 # "found", "norm_absent_from_corpus", "edition_unverified"
    candidates: list[dict]
    warning: str = ""
    target_source_path: Optional[str] = None


@dataclass
class MultiNormResolution:
    overall_status: str         # "found", "norm_not_found", "partial_found", "no_norm"
    resolutions: list[SingleNormResolution]
    primary_target: Optional[NormRef] = None
    target_source_paths: list[str] = field(default_factory=list)


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
    r"(?:(?P<type>пункт|п\.|раздел|таблиц[аеы]|приложени[еи])\s*(?P<num>[А-Яа-яA-Za-z0-9]+(?:[\.\-][А-Яа-яA-Za-z0-9]+)*))",
    re.IGNORECASE
)

# Mentions/citations preceding clause numbers: "согласно п. 6.4", "в соответствии с 6.4"
CITATION_LEAD_RE = re.compile(
    r"(?:согласно|в соответствии с|по формуле|по таблице|см\.|требованиями|на основании|руководствуясь|по п\.|по разделу)\s*$",
    re.IGNORECASE
)


def _open_db(db_path: str | Path) -> Optional[sqlite3.Connection]:
    """Safe SQLite connection handling Windows paths with drive letters."""
    p = Path(db_path)
    if not p.exists():
        return None
    try:
        con = sqlite3.connect(str(p), timeout=10.0)
        con.execute("PRAGMA busy_timeout=10000")
        return con
    except Exception:
        return None


def parse_all_norm_queries(query: str) -> List[NormRef]:
    """Extracts all normative designations found in the query string in appearance order."""
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
    Differentiates latest_in_corpus, confirmed_in_force, and applicable editions.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.corpus_generation = ""
        self.doc_records: list[dict] = []
        self._norm_map: dict[tuple[str, str], list[dict]] = {}
        self._reload_if_needed()

    def _get_current_generation(self) -> str:
        con = _open_db(self.db_path)
        if con is None:
            return "default"
        try:
            row = con.execute("SELECT value FROM runtime_state WHERE key = 'corpus_generation'").fetchone()
            return str(row[0]) if row else "default"
        except Exception:
            return "default"
        finally:
            con.close()

    def _reload_if_needed(self):
        current_gen = self._get_current_generation()
        if self.doc_records and current_gen == self.corpus_generation:
            return

        con = _open_db(self.db_path)
        if con is None:
            return

        self.corpus_generation = current_gen
        self.doc_records = []
        self._norm_map = {}

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
                    "latest_in_corpus": False,
                    "confirmed_in_force": not bool(depr) and not is_derivative,
                }
                self.doc_records.append(rec)
                if norm_ref:
                    key = (norm_ref.prefix, norm_ref.number)
                    if key not in self._norm_map:
                        self._norm_map[key] = []
                    self._norm_map[key].append(rec)

            # Mark latest_in_corpus for each norm key
            for key, cands in self._norm_map.items():
                if cands:
                    # Sort candidates by edition year (latest first)
                    sorted_by_year = sorted(
                        cands,
                        key=lambda c: (
                            not c["is_derivative"],
                            c["edition_year"] or "0000",
                            not c["is_deprecated"]
                        ),
                        reverse=True
                    )
                    sorted_by_year[0]["latest_in_corpus"] = True
        finally:
            con.close()

    def _inspect_edition_if_needed(self, rec: dict):
        """Lazy inspection of intro chunks for the matched target document."""
        if rec.get("_edition_inspected"):
            return
        rec["_edition_inspected"] = True
        sp = rec["source_path"]
        con = _open_db(self.db_path)
        if con is None:
            return
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
                # Check cancellation in intro text
                if any(m in combined_intro.lower() for m in ["утратил силу", "отменен"]):
                    rec["confirmed_in_force"] = False
                    rec["is_deprecated"] = True
        finally:
            con.close()

    def resolve(self, query: str) -> Tuple[Optional[NormRef], str, list[dict]]:
        """Resolves primary norm from query (backward-compatible tuple contract)."""
        multi = self.resolve_all(query)
        if not multi.resolutions:
            return None, "no_norm", []
        primary = multi.resolutions[0]
        return primary.target, primary.status, primary.candidates

    def resolve_all(self, query: str) -> MultiNormResolution:
        """Resolves all normative designations found in the query string independently."""
        self._reload_if_needed()
        all_norms = parse_all_norm_queries(query)
        if not all_norms:
            return MultiNormResolution(overall_status="no_norm", resolutions=[])

        resolutions: list[SingleNormResolution] = []
        target_paths: list[str] = []

        for target in all_norms:
            key = (target.prefix, target.number)
            candidates = self._norm_map.get(key, [])
            
            if not candidates:
                resolutions.append(SingleNormResolution(
                    target=target,
                    status="norm_absent_from_corpus",
                    candidates=[],
                    warning=f"Нормативный документ {target.raw_match} отсутствует в корпоративном корпусе"
                ))
                continue

            for c in candidates:
                self._inspect_edition_if_needed(c)

            # Sort candidates:
            # 1. Non-derivative (primary standard) first
            # 2. Matching target.year (if specified)
            # 3. Confirmed in force first
            # 4. Latest in corpus (higher edition_year)
            def sort_key(doc):
                is_deriv = doc["is_derivative"]
                ed_yr = doc.get("edition_year") or ""
                target_yr_match = (ed_yr == target.year) if (target.year and ed_yr) else True
                in_force = doc.get("confirmed_in_force", False)
                return (not is_deriv, target_yr_match, in_force, ed_yr)

            sorted_candidates = sorted(candidates, key=sort_key, reverse=True)
            primary_doc = sorted_candidates[0]
            target_paths.append(primary_doc["source_path"])

            status = "found"
            warning = ""
            if target.year and primary_doc.get("edition_year") and primary_doc["edition_year"] != target.year:
                status = "edition_unverified"
                warning = f"Запрошена редакция {target.year}, в корпусе используется редакция {primary_doc['edition_year']}"

            resolutions.append(SingleNormResolution(
                target=target,
                status=status,
                candidates=sorted_candidates,
                warning=warning,
                target_source_path=primary_doc["source_path"]
            ))

        found_count = sum(1 for r in resolutions if r.status in ("found", "edition_unverified"))
        if found_count == len(resolutions):
            overall_status = "found"
        elif found_count > 0:
            overall_status = "partial_found"
        else:
            overall_status = "norm_not_found"

        return MultiNormResolution(
            overall_status=overall_status,
            resolutions=resolutions,
            primary_target=resolutions[0].target if resolutions else None,
            target_source_paths=target_paths
        )

    def extract_clause_from_doc(self, source_path: str, clause_num: str, clause_type: str | None = None) -> List[ClauseMatch]:
        """Extracts and verifies specific clause boundaries in the given document.
        
        Strictly distinguishes:
        - Hierarchical sub-clauses: 6.4 vs 6.4.1, 4.2.19 vs 4.2.19.1.
        - True structural headers vs Table of Contents (оглавление).
        - Normative clause headers vs in-text citations/references.
        - Alphanumeric tables (Таблица А.1) and appendices (Приложение А.3).
        - Structural context completeness (terminal punctuation, balanced brackets, un-truncated tables).
        """
        c_escaped = re.escape(str(clause_num).strip())
        c_type_lower = (clause_type or "").lower().strip()

        # Build precise header pattern with negative lookahead for dot+digit
        if c_type_lower in ("таблица", "таблицы", "таблице", "таблицу"):
            header_pattern = re.compile(
                rf"(?:^|\n)\s*(?:Таблиц[аеы]\s*){c_escaped}(?:\.?(?!\d)(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
                re.IGNORECASE
            )
        elif c_type_lower in ("приложение", "приложения", "приложении"):
            header_pattern = re.compile(
                rf"(?:^|\n)\s*(?:Приложени[еи]\s*){c_escaped}(?:\.?(?!\d)(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
                re.IGNORECASE
            )
        else:
            header_pattern = re.compile(
                rf"(?:^|\n)\s*(?:(?:п\.|пункт|раздел|таблиц[аеы]|приложени[еи])\s*)?{c_escaped}(?:\.?(?!\d)(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
                re.IGNORECASE
            )

        con = _open_db(self.db_path)
        if con is None:
            return []

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
            if not m:
                continue

            pos = m.start()
            match_line = p_text[pos:p_text.find("\n", pos) if "\n" in p_text[pos:] else len(p_text)]
            
            # 1. Table of Contents detection: dot leaders or trailing page numbers
            is_toc = bool(re.search(r"(?:\.{2,}|\s{4,})\s*\d+\s*$", match_line.strip()))
            if not is_toc and any(w in p_text[:120].lower() for w in ["содержание", "оглавление"]):
                is_toc = True

            # 2. Citation / Mention detection
            lead_snippet = p_text[max(0, pos - 50):pos]
            is_citation = bool(CITATION_LEAD_RE.search(lead_snippet))
            # Also check if clause is enclosed in parentheses: (п. 6.4)
            surrounding = p_text[max(0, pos - 15):pos + len(clause_num) + 20]
            if re.search(r"\((?:см\.\s*)?(?:п\.|пункт)?\s*" + c_escaped + r"[^\)]*\)", surrounding, re.IGNORECASE):
                is_citation = True

            is_header = (not is_citation) and (not is_toc)

            # 3. Context completeness evaluation (not merely size!)
            t_strip = p_text.strip()
            is_partial = False
            if is_toc:
                status = "toc_entry"
            elif is_citation or not is_header:
                status = "clause_mention_only"
            else:
                # Check terminal punctuation
                if not t_strip.endswith((".", ":", "!", "?", ";", ")", '"', "»")):
                    is_partial = True
                # Check trailing cutoff markers
                if t_strip.endswith(("...", "…", "—", ",", ";", "в ред.")):
                    is_partial = True
                # Check balanced brackets
                if t_strip.count("(") != t_strip.count(")") or t_strip.count("[") != t_strip.count("]"):
                    is_partial = True
                # Check formula truncated index: e.g. text ends with "( 6." or "( А."
                if re.search(r"\(\s*[А-Яа-я0-9\.\-]+\s*$", t_strip):
                    is_partial = True
                # Check dangling table: abrupt end mid-row
                lines = [l.strip() for l in t_strip.splitlines() if "|" in l]
                if lines and lines[-1].count("|") < 2:
                    is_partial = True

                status = "context_partial" if is_partial else "context_sufficient"

            # 4. Amendment check in clause
            amend_note = ""
            am_match = re.search(r"\((?:п\.\s*" + c_escaped + r"\s*)?в\s*ред\.\s*Изменени[яе]\s*N?\s*\d+[^)]*\)", p_text, re.IGNORECASE)
            if am_match:
                amend_note = am_match.group(0)

            results.append(ClauseMatch(
                clause_num=clause_num,
                clause_type=clause_type or "пункт",
                is_header=is_header,
                context_status=status,
                parent_id=p_id,
                source_path=source_path,
                file_name=Path(source_path).name,
                text=p_text,
                amendment_note=amend_note
            ))

        # Prioritize true headers over citations, and sufficient over partial
        results.sort(
            key=lambda c: (
                c.is_header,
                c.context_status == "context_sufficient",
                c.context_status != "toc_entry"
            ),
            reverse=True
        )
        return results


_CACHED_REGISTRY: Optional[NormRegistry] = None


def get_norm_registry(db_path: str | Path) -> NormRegistry:
    global _CACHED_REGISTRY
    if _CACHED_REGISTRY is None or _CACHED_REGISTRY.db_path != str(db_path):
        _CACHED_REGISTRY = NormRegistry(db_path)
    return _CACHED_REGISTRY
