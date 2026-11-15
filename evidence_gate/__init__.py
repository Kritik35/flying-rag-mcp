"""
evidence_gate package.

Evidence Integrity Gate (EIG) — Deterministic Normative Evidence Resolver and Safe Stitcher.
"""
from __future__ import annotations

from .evidence_gate import EvidenceIntegrityGate, EvidenceGateResult
from .stitcher import (
    stitch_sequential_chunks,
    extract_and_stitch_clause,
    match_structural_element,
    match_structural_clause,
    check_formula_integrity,
    compute_overlap,
    StitchResult,
    ChunkSpan
)

__all__ = [
    "EvidenceIntegrityGate",
    "EvidenceGateResult",
    "stitch_sequential_chunks",
    "extract_and_stitch_clause",
    "match_structural_element",
    "match_structural_clause",
    "check_formula_integrity",
    "compute_overlap",
    "StitchResult",
    "ChunkSpan"
]
