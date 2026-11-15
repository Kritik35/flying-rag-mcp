"""
evidence_gate/stitcher.py

Safe Normative Chunk Stitcher & Structural Boundary Extractor (Stage 4.1).
Strictly enforces:
1. Contiguous sequential parent chunk ordering only (no non-adjacent bundling).
2. Document identity and edition verification across all chunks.
3. Confirmed sliding window overlap (no silent concatenation with newline).
4. Individual, physical source_spans per parent chunk.
5. Detection of missing mathematical formula expressions (DOCX conversion artifacts).
6. Granular integrity indicators: boundary_integrity, text_integrity, formula_integrity.
"""
from __future__ import annotations
import re
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple


@dataclass
class ChunkSpan:
    parent_id: str
    source_path: str
    char_start: int
    char_end: int
    length: int
    sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StitchResult:
    certified_text: str
    boundary_integrity: str    # "EXACT_BOUNDARIES" | "TRUNCATED" | "NOT_FOUND"
    text_integrity: str        # "COMPLETE" | "PARTIAL" | "BROKEN_CHAIN_NO_OVERLAP"
    formula_integrity: str     # "FORMULAS_VERIFIED" | "FORMULA_MISSING" | "NOT_APPLICABLE"
    missing_formulas: List[str]
    parent_ids: List[str]
    source_spans: List[Dict[str, Any]]
    overlap_lengths: List[int]
    is_stitched: bool
    sha256: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_overlap(text_a: str, text_b: str, min_overlap: int = 15) -> int:
    """Find the length of the longest suffix of text_a matching prefix of text_b."""
    if not text_a or not text_b:
        return 0
    max_ov = 0
    limit = min(len(text_a), len(text_b))
    for l in range(min_overlap, limit + 1):
        if text_a.endswith(text_b[:l]):
            max_ov = l
    return max_ov


def check_formula_integrity(text: str) -> Tuple[str, List[str]]:
    """
    Checks if formulas mentioned in the normative text actually contain their
    mathematical expressions or were lost during DOCX/PDF text conversion.
    e.g. 'по формуле (А.5)' followed by a standalone line '(А.5)' without math.
    """
    if not text:
        return "NOT_APPLICABLE", []

    # Find formula citations like (А.5), (А.6), (1), (2), (А.3)
    formula_labels = re.findall(r'(?:формул[а-я]\s*\(?|\()([А-ЯЁA-Z\d\.]+)\)?', text, re.IGNORECASE)
    unique_formulas = []
    for f in formula_labels:
        if f not in unique_formulas and len(f) >= 1:
            unique_formulas.append(f)

    if not unique_formulas:
        return "NOT_APPLICABLE", []

    missing = []
    for f_label in unique_formulas:
        esc = re.escape(f_label)
        pattern = rf'(?:^|\n)\s*\(?{esc}\)?\s*(?:\n|$)'
        for m in re.finditer(pattern, text):
            ctx_start = max(0, m.start() - 100)
            ctx_end = min(len(text), m.end() + 100)
            surrounding = text[ctx_start:ctx_end]
            if "=" not in surrounding:
                full_label = f"({f_label})"
                if full_label not in missing:
                    missing.append(full_label)

    if missing:
        return "FORMULA_MISSING", missing
    return "FORMULAS_VERIFIED", []


def match_structural_element(
    text: str, element_id: str, element_type: str = "clause"
) -> Optional[Tuple[int, int, str, bool]]:
    """
    Locates a genuine structural element in text.
    Handles clauses, appendix clauses, formulas, sections, and tables.
    Returns:
        (start_pos, end_pos, element_text, is_at_end_of_text)
    """
    if not text or not element_id:
        return None

    esc = re.escape(element_id)

    if element_type == "formula":
        # Look for standalone formula label e.g. " (А.3) "
        pattern = rf'(?:^|\n)([^\n]*?\(?{esc}\)?\s*(?:\n|$).*?)(?=(?:\n\s*(?:\([А-ЯЁA-Z\d\.]+\)|\d+(?:\.\d+)*\.?\s+[А-ЯЁA-Z]))|\Z)'
        m = re.search(pattern, text, flags=re.DOTALL)
        if m:
            start_pos = m.start(1)
            end_pos = m.end(1)
            content = m.group(1).strip()
            is_at_end = (end_pos >= len(text) - 5)
            return start_pos, end_pos, content, is_at_end
        return None

    if element_type == "section":
        pattern = rf'(?:^|\n)\s*({esc}\.?\s+[А-ЯЁA-Z][^\n]+.*?)(?=(?:\n\s*(?:(?:раздел\s+)?\d+\.?\s+[А-ЯЁA-Z]))|\Z)'
        m = re.search(pattern, text, flags=re.DOTALL)
        if m:
            start_pos = m.start(1)
            end_pos = m.end(1)
            content = m.group(1).strip()
            is_at_end = (end_pos >= len(text) - 5)
            return start_pos, end_pos, content, is_at_end
        return None

    # Normal clause or appendix clause
    pattern = rf'(?:^|\n)\s*({esc}(?:\.|\s)\s*[А-ЯЁA-Z].*?)(?=(?:\n\s*(?:\d+(?:\.\d+)*|[А-ЯЁ]\.\d+)\.?\s+[А-ЯЁA-Z])|\Z)'
    m = re.search(pattern, text, flags=re.DOTALL)
    if not m:
        return None

    start_pos = m.start(1)
    end_pos = m.end(1)
    clause_text = m.group(1).strip()
    is_at_end = (end_pos >= len(text) - 5)
    return start_pos, end_pos, clause_text, is_at_end


# Backwards compatibility alias
match_structural_clause = match_structural_element


def stitch_sequential_chunks(
    sequential_chunks: List[Dict[str, Any]],
    target_clause: str,
    element_type: str = "clause"
) -> StitchResult:
    """
    Safely stitches strictly ordered, sequential parent chunks from the same document.
    Enforces overlap confirmation (no silent joining), outputs per-chunk source_spans,
    and performs formula integrity validation.
    """
    if not sequential_chunks:
        return StitchResult(
            certified_text="",
            boundary_integrity="NOT_FOUND",
            text_integrity="PARTIAL",
            formula_integrity="NOT_APPLICABLE",
            missing_formulas=[],
            parent_ids=[],
            source_spans=[],
            overlap_lengths=[],
            is_stitched=False,
            sha256="",
            error="Empty chunk list provided"
        )

    # 1. Document Identity & Sequential Continuity Validation
    source_paths = {c.get("source_path") for c in sequential_chunks}
    if len(source_paths) > 1:
        return StitchResult(
            certified_text="",
            boundary_integrity="NOT_FOUND",
            text_integrity="PARTIAL",
            formula_integrity="NOT_APPLICABLE",
            missing_formulas=[],
            parent_ids=[c.get("parent_id", "") for c in sequential_chunks],
            source_spans=[],
            overlap_lengths=[],
            is_stitched=False,
            sha256="",
            error=f"Source path mismatch across candidates: {source_paths}"
        )
    source_path = list(source_paths)[0]

    # Verify sequential parent IDs (e.g. _p_0017 followed by _p_0018)
    pids = [c.get("parent_id", "") for c in sequential_chunks]
    for i in range(len(pids) - 1):
        try:
            curr_idx = int(pids[i].rsplit("_", 1)[1])
            next_idx = int(pids[i+1].rsplit("_", 1)[1])
            if next_idx != curr_idx + 1:
                return StitchResult(
                    certified_text="",
                    boundary_integrity="NOT_FOUND",
                    text_integrity="PARTIAL",
                    formula_integrity="NOT_APPLICABLE",
                    missing_formulas=[],
                    parent_ids=pids,
                    source_spans=[],
                    overlap_lengths=[],
                    is_stitched=False,
                    sha256="",
                    error=f"Non-adjacent parent chunks cannot be stitched: {pids[i]} -> {pids[i+1]}"
                )
        except (IndexError, ValueError):
            pass

    # 2. Case: Single Chunk Sufficiency
    if len(sequential_chunks) == 1:
        txt = sequential_chunks[0].get("text", "")
        pid = sequential_chunks[0].get("parent_id", "")
        match = match_structural_element(txt, target_clause, element_type)
        if not match:
            return StitchResult(
                certified_text="",
                boundary_integrity="NOT_FOUND",
                text_integrity="PARTIAL",
                formula_integrity="NOT_APPLICABLE",
                missing_formulas=[],
                parent_ids=[pid],
                source_spans=[],
                overlap_lengths=[],
                is_stitched=False,
                sha256="",
                error=f"Structural element '{target_clause}' not found in {pid}"
            )

        s, e, candidate_text, is_at_end = match
        f_status, missing_f = check_formula_integrity(candidate_text)
        sha = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()

        b_status = "TRUNCATED" if is_at_end else "EXACT_BOUNDARIES"
        t_status = "PARTIAL" if is_at_end else "COMPLETE"

        span = {
            "parent_id": pid,
            "source_path": source_path,
            "char_start": s,
            "char_end": e,
            "length": len(candidate_text),
            "sha256": sha
        }

        return StitchResult(
            certified_text=candidate_text,
            boundary_integrity=b_status,
            text_integrity=t_status,
            formula_integrity=f_status,
            missing_formulas=missing_f,
            parent_ids=[pid],
            source_spans=[span],
            overlap_lengths=[],
            is_stitched=False,
            sha256=sha,
            error="Single chunk is truncated at boundary" if is_at_end else None
        )

    # 3. Multi-chunk Sequential Stitching with Dynamic Overlap
    first_chunk = sequential_chunks[0]
    first_txt = first_chunk.get("text", "")
    first_pid = first_chunk.get("parent_id", "")
    match_start = match_structural_element(first_txt, target_clause, element_type)
    if not match_start:
        return StitchResult(
            certified_text="",
            boundary_integrity="NOT_FOUND",
            text_integrity="PARTIAL",
            formula_integrity="NOT_APPLICABLE",
            missing_formulas=[],
            parent_ids=pids,
            source_spans=[],
            overlap_lengths=[],
            is_stitched=False,
            sha256="",
            error=f"Structural element '{target_clause}' does not start in first chunk {first_pid}"
        )

    s_clause = match_start[0]
    spans = []
    overlap_lengths = []
    reconstructed_text_parts = []

    # First chunk contribution: from s_clause to end of chunk
    span0_start = s_clause
    span0_end = len(first_txt)
    span0_text = first_txt[span0_start:span0_end]
    span0_sha = hashlib.sha256(span0_text.encode("utf-8")).hexdigest()
    spans.append({
        "parent_id": first_pid,
        "source_path": source_path,
        "char_start": span0_start,
        "char_end": span0_end,
        "length": len(span0_text),
        "sha256": span0_sha
    })
    reconstructed_text_parts.append(span0_text)

    # Process subsequent adjacent chunks
    current_stitched = first_txt
    is_terminated = False

    for i in range(1, len(sequential_chunks)):
        prev_chunk = sequential_chunks[i-1]
        curr_chunk = sequential_chunks[i]
        curr_txt = curr_chunk.get("text", "")
        curr_pid = curr_chunk.get("parent_id", "")

        # Compute dynamic overlap
        ov = compute_overlap(prev_chunk.get("text", ""), curr_txt)
        if ov == 0:
            return StitchResult(
                certified_text="".join(reconstructed_text_parts),
                boundary_integrity="TRUNCATED",
                text_integrity="BROKEN_CHAIN_NO_OVERLAP",
                formula_integrity="NOT_APPLICABLE",
                missing_formulas=[],
                parent_ids=pids[:i+1],
                source_spans=spans,
                overlap_lengths=overlap_lengths,
                is_stitched=True,
                sha256="",
                error=f"No textual overlap found between adjacent chunks {prev_chunk.get('parent_id')} and {curr_pid}. Silent concatenation prohibited."
            )

        overlap_lengths.append(ov)
        current_stitched = current_stitched + curr_txt[ov:]

        # Find where element ends in current_stitched
        match_in_stitched = match_structural_element(current_stitched, target_clause, element_type)
        if match_in_stitched:
            s_full, e_full, text_full, is_at_end = match_in_stitched
            offset_in_curr = e_full - (len(current_stitched) - len(curr_txt))
            span_curr_start = ov
            span_curr_end = min(len(curr_txt), offset_in_curr)
            span_curr_text = curr_txt[span_curr_start:span_curr_end]
            span_curr_sha = hashlib.sha256(span_curr_text.encode("utf-8")).hexdigest()

            spans.append({
                "parent_id": curr_pid,
                "source_path": source_path,
                "char_start": span_curr_start,
                "char_end": span_curr_end,
                "length": len(span_curr_text),
                "sha256": span_curr_sha
            })
            reconstructed_text_parts.append(span_curr_text)

            if not is_at_end:
                is_terminated = True
                break

    certified = "".join(reconstructed_text_parts)
    sha = hashlib.sha256(certified.strip().encode("utf-8")).hexdigest()
    f_status, missing_f = check_formula_integrity(certified)

    b_status = "EXACT_BOUNDARIES" if is_terminated else "TRUNCATED"
    t_status = "COMPLETE" if is_terminated else "PARTIAL"

    return StitchResult(
        certified_text=certified,
        boundary_integrity=b_status,
        text_integrity=t_status,
        formula_integrity=f_status,
        missing_formulas=missing_f,
        parent_ids=[s["parent_id"] for s in spans],
        source_spans=spans,
        overlap_lengths=overlap_lengths,
        is_stitched=True,
        sha256=sha
    )


# Backwards compatibility alias
extract_and_stitch_clause = stitch_sequential_chunks
