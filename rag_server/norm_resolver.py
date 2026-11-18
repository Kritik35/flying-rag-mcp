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
    parent_ids: list[str] = field(default_factory=list)
    is_stitched: bool = False

    def __post_init__(self):
        if not self.parent_ids and self.parent_id:
            self.parent_ids = [self.parent_id]


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
    r"(?:согласно|в соответствии с|по формуле|по таблице|см\.|требованиями|на основании|руководствуясь|по п\.|по разделу)\s*(?:п\.|пункту|пунктом|пункта|разделу)?\s*$",
    re.IGNORECASE
)

# Structural heading detection for isolating clause boundaries: "6.11", "Раздел 7", "Таблица А.1"
NEXT_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:(?:п\.|пункт|раздел|таблиц[аеы]|приложени[еи])\s*)?([А-Яа-яA-Za-z0-9]+(?:\.[А-Яа-яA-Za-z0-9]+)*)(?:\.?(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
    re.IGNORECASE
)


def _open_db(db_path: str | Path, readonly: bool = True) -> Optional[sqlite3.Connection]:
    """Safe SQLite connection handling Windows paths with drive letters in true mode=ro.

    Ensures genuine read-only access (SQLITE_OPEN_READONLY) via SQLite URI syntax.
    Does NOT alter PRAGMA journal_mode on read-only connections.
    Supports reading WAL-mode databases on Windows with PRAGMA query_only = ON and busy_timeout.
    """
    p = Path(db_path).resolve()
    if not p.exists():
        return None
    try:
        if readonly:
            posix_path = p.as_posix()
            if not posix_path.startswith("/"):
                posix_path = "/" + posix_path
            uri = f"file://{posix_path}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=10.0)
            con.execute("PRAGMA busy_timeout = 10000")
            con.execute("PRAGMA query_only = ON")
            return con
        else:
            con = sqlite3.connect(str(p), timeout=10.0)
            con.execute("PRAGMA busy_timeout = 10000")
            return con
    except Exception:
        try:
            con = sqlite3.connect(str(p), timeout=10.0)
            con.execute("PRAGMA busy_timeout = 10000")
            if readonly:
                con.execute("PRAGMA query_only = ON")
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
                target_yr_match = (ed_yr == target.year) if target.year else True
                in_force = doc.get("confirmed_in_force", False)
                return (not is_deriv, target_yr_match, in_force, ed_yr)

            sorted_candidates = sorted(candidates, key=sort_key, reverse=True)

            primary_candidates = [c for c in sorted_candidates if not c.get("is_derivative")]
            eval_candidates = primary_candidates if primary_candidates else sorted_candidates
            distinct_years = sorted(list(set(c["edition_year"] for c in eval_candidates if c.get("edition_year"))))

            if not target.year:
                if len(distinct_years) > 1:
                    status = "ambiguous_editions"
                    warning = (
                        f"Документ {target.raw_match} имеет несколько редакций в корпусе ({', '.join(distinct_years)}). "
                        "Требуется явное указание редакции (года)."
                    )
                    primary_doc = sorted_candidates[0]
                    target_paths.append(primary_doc["source_path"])
                else:
                    status = "found"
                    warning = ""
                    primary_doc = sorted_candidates[0]
                    target_paths.append(primary_doc["source_path"])
            else:
                matching_docs = [c for c in sorted_candidates if c.get("edition_year") == target.year]
                if matching_docs:
                    status = "found"
                    warning = ""
                    primary_doc = matching_docs[0]
                    target_paths.append(primary_doc["source_path"])
                else:
                    status = "edition_not_found"
                    warning = (
                        f"Запрошенная редакция {target.year} для документа {target.raw_match} "
                        f"отсутствует в корпусе (доступны: {', '.join(distinct_years) if distinct_years else 'нет данных'})"
                    )
                    primary_doc = None

            resolutions.append(SingleNormResolution(
                target=target,
                status=status,
                candidates=sorted_candidates,
                warning=warning,
                target_source_path=primary_doc["source_path"] if primary_doc else None
            ))

        found_count = sum(1 for r in resolutions if r.status in ("found", "edition_unverified"))
        if any(r.status == "ambiguous_editions" for r in resolutions):
            overall_status = "ambiguous_editions"
        elif any(r.status == "edition_not_found" for r in resolutions):
            overall_status = "edition_not_found"
        elif found_count == len(resolutions):
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
        - Slices exact clause boundaries starting at header and stopping before next clause/section.
        - Bounded consecutive stitching of adjacent parent chunks within the same document.
        """
        c_num = str(clause_num).strip()
        c_escaped = re.escape(c_num)
        c_type_lower = (clause_type or "").lower().strip()

        # Build precise header pattern with negative lookahead for dot+digit
        if c_type_lower in ("таблица", "таблицы", "таблице", "таблицу"):
            header_pattern = re.compile(
                rf"(?:^|\n)\s*(?:Таблиц[аеы]\s*){c_escaped}(?!\.\d)(?:\.?(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
                re.IGNORECASE
            )
        elif c_type_lower in ("приложение", "приложения", "приложении"):
            header_pattern = re.compile(
                rf"(?:^|\n)\s*(?:Приложени[еи]\s*){c_escaped}(?!\.\d)(?:\.?(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
                re.IGNORECASE
            )
        else:
            header_pattern = re.compile(
                rf"(?:^|\n)\s*(?:(?:п\.|пункт|раздел|таблиц[аеы]|приложени[еи])\s*)?{c_escaped}(?!\.\d)(?:\.?(?:\s+[А-Яа-яA-Za-z]|\s*[\—\–\-]|\s*\n|\s*$))",
                re.IGNORECASE
            )

        con = _open_db(self.db_path)
        if con is None:
            return []

        try:
            cur = con.cursor()
            cur.execute(
                "SELECT parent_id, parent_text FROM parent_chunks WHERE source_path = ? ORDER BY rowid ASC",
                (source_path,)
            )
            rows = cur.fetchall()
        finally:
            con.close()

        results: list[ClauseMatch] = []
        for idx, (p_id, p_text) in enumerate(rows):
            for m in header_pattern.finditer(p_text):
                raw_pos = m.start()
                pos = raw_pos + 1 if p_text[raw_pos] == "\n" else raw_pos
                match_line = p_text[pos:p_text.find("\n", pos) if "\n" in p_text[pos:] else len(p_text)]
                
                # 1. Table of Contents detection: dot leaders or trailing page numbers
                is_toc = bool(re.search(r"(?:\.{2,}|\s{4,})\s*\d+\s*$", match_line.strip()))
                if not is_toc and any(w in p_text[:120].lower() for w in ["содержание", "оглавление"]):
                    is_toc = True

                line_start = p_text.rfind("\n", 0, pos)
                line_start = 0 if line_start == -1 else line_start + 1
                line_end = p_text.find("\n", pos)
                line_end = len(p_text) if line_end == -1 else line_end
                current_line = p_text[line_start:line_end]

                # 2. Citation / Mention detection
                lead_snippet = p_text[max(line_start, pos - 50):pos]
                is_citation = bool(CITATION_LEAD_RE.search(lead_snippet))
                # Check if clause is enclosed in parentheses on current line: (п. 6.4)
                if re.search(r"\([^\)]*" + c_escaped + r"[^\)]*\)", current_line):
                    is_citation = True

                is_header = (not is_citation) and (not is_toc)

                if is_toc:
                    status = "toc_entry"
                    final_text = p_text[pos:].rstrip()
                    parent_ids = [p_id]
                    is_stitched = False
                elif is_citation or not is_header:
                    status = "clause_mention_only"
                    final_text = p_text[pos:].rstrip()
                    parent_ids = [p_id]
                    is_stitched = False
                else:
                    # Valid structural header: slice exact clause boundaries
                    line_end = p_text.find("\n", pos)
                    next_header_pos = -1
                    if line_end != -1:
                        for nm in NEXT_HEADER_RE.finditer(p_text, line_end):
                            cand_num = nm.group(1).strip()
                            if cand_num == c_num or cand_num.startswith(c_num + "."):
                                continue
                            nm_pos = nm.start()
                            cand_line_start = p_text.rfind("\n", 0, nm_pos)
                            cand_line_start = 0 if cand_line_start == -1 else cand_line_start + 1
                            cand_line_end = p_text.find("\n", nm_pos)
                            cand_line_end = len(p_text) if cand_line_end == -1 else cand_line_end
                            cand_line = p_text[cand_line_start:cand_line_end]

                            nm_lead = p_text[max(cand_line_start, nm_pos - 50):nm_pos]
                            if CITATION_LEAD_RE.search(nm_lead):
                                continue
                            if re.search(r"\([^\)]*" + re.escape(cand_num) + r"[^\)]*\)", cand_line):
                                continue
                            next_header_pos = nm_pos
                            break

                    if next_header_pos != -1:
                        # Fully contained within current parent chunk
                        final_text = p_text[pos:next_header_pos].rstrip()
                        parent_ids = [p_id]
                        is_stitched = False
                        terminated_properly = True
                    else:
                        # Reaches end of current chunk: attempt bounded adjacent stitch
                        chunk_slice = p_text[pos:].rstrip()
                        terminated_properly = False
                        adj_stitched = False
                        stitched_parent_ids = [p_id]
                        final_text = chunk_slice

                        if idx + 1 < len(rows):
                            next_p_id, next_p_text = rows[idx + 1]
                            m_cur = re.search(r"^(.*_p_)(\d+)$", p_id)
                            m_nxt = re.search(r"^(.*_p_)(\d+)$", next_p_id)
                            is_consecutive = bool(
                                m_cur and m_nxt and
                                m_cur.group(1) == m_nxt.group(1) and
                                int(m_nxt.group(2)) == int(m_cur.group(2)) + 1
                            )
                            if is_consecutive:
                                next_adj_header_pos = -1
                                for nm in NEXT_HEADER_RE.finditer(next_p_text):
                                    cand_num = nm.group(1).strip()
                                    if cand_num == c_num or cand_num.startswith(c_num + "."):
                                        continue
                                    nm_pos = nm.start()
                                    cand_line_start = next_p_text.rfind("\n", 0, nm_pos)
                                    cand_line_start = 0 if cand_line_start == -1 else cand_line_start + 1
                                    cand_line_end = next_p_text.find("\n", nm_pos)
                                    cand_line_end = len(next_p_text) if cand_line_end == -1 else cand_line_end
                                    cand_line = next_p_text[cand_line_start:cand_line_end]

                                    nm_lead = next_p_text[max(cand_line_start, nm_pos - 50):nm_pos]
                                    if CITATION_LEAD_RE.search(nm_lead):
                                        continue
                                    if re.search(r"\([^\)]*" + re.escape(cand_num) + r"[^\)]*\)", cand_line):
                                        continue
                                    next_adj_header_pos = nm_pos
                                    break

                                if next_adj_header_pos != -1:
                                    adj_text = next_p_text[:next_adj_header_pos].rstrip()
                                    if adj_text:
                                        final_text = chunk_slice + "\n" + adj_text
                                    else:
                                        final_text = chunk_slice
                                    stitched_parent_ids.append(next_p_id)
                                    adj_stitched = True
                                    terminated_properly = True
                                else:
                                    adj_text = next_p_text.rstrip()
                                    if len(chunk_slice) + len(adj_text) <= 5000:
                                        final_text = chunk_slice + "\n" + adj_text
                                        stitched_parent_ids.append(next_p_id)
                                        adj_stitched = True
                                    terminated_properly = False

                        parent_ids = stitched_parent_ids
                        is_stitched = adj_stitched

                    # Evaluate context completeness
                    t_strip = final_text.strip()
                    is_partial = False
                    if not terminated_properly:
                        is_partial = True
                    if not t_strip.endswith((".", "!", "?", ")", '"', "»")):
                        is_partial = True
                    if t_strip.endswith(("...", "…", "—", ",", ";", ":", "в ред.")):
                        is_partial = True
                    if any(t_strip.endswith(d) for d in ("а также", "в том числе", "следующие:", "следующих:", "в случаях:", "подпунктам")):
                        is_partial = True
                    clean_parens = re.sub(r"(?:^|\n|\s)[а-яa-z0-9]\)", " ", t_strip)
                    if clean_parens.count("(") != clean_parens.count(")") or t_strip.count("[") != t_strip.count("]"):
                        is_partial = True
                    if re.search(r"\(\s*[А-Яа-я0-9\.\-]+\s*$", t_strip):
                        is_partial = True
                    lines = [l.strip() for l in t_strip.splitlines() if "|" in l]
                    if lines and lines[-1].count("|") < 2:
                        is_partial = True
                    if len(final_text) > 5000:
                        is_partial = True

                    status = "context_partial" if is_partial else "context_sufficient"

                # 4. Amendment check in clause
                amend_note = ""
                am_match = re.search(
                    r"\((?:п\.\s*" + c_escaped + r"\s*)?в\s*ред\.\s*Изменени[яе]\s*N?\s*\d+[^)]*\)",
                    final_text,
                    re.IGNORECASE
                )
                if am_match:
                    amend_note = am_match.group(0)

                results.append(ClauseMatch(
                    clause_num=c_num,
                    clause_type=clause_type or "пункт",
                    is_header=is_header,
                    context_status=status,
                    parent_id=p_id,
                    source_path=source_path,
                    file_name=Path(source_path).name,
                    text=final_text,
                    amendment_note=amend_note,
                    parent_ids=parent_ids,
                    is_stitched=is_stitched
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
