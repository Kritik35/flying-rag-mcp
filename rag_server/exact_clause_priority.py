"""Deterministic visibility for an explicitly requested normative clause.

A reconstructed *partial* clause is more useful than a document cover when
the user explicitly requested that clause, but it must never be mislabeled as
complete or converted into an ANN score. This runs only on existing retrieval
results and a NormRegistry-generated, physically attributed clause item.

No DB, model, search, network, file I/O or mutable global state.
"""
from __future__ import annotations

from typing import Any


def _path_id(value: object) -> str:
    """Compare Windows/Unix paths without changing the evidence metadata."""
    return str(value or "").strip().replace("\\", "/").casefold()


def _same_target_source(item: dict, target_sources: tuple[str, ...]) -> bool:
    source = _path_id(item.get("source_path"))
    return bool(source and source in target_sources)


def _is_complete_requested_clause(item: dict, *, clause_id: str, target_sources: tuple[str, ...]) -> bool:
    """A high numeric score without target-clause identity is not evidence."""
    return (
        _same_target_source(item, target_sources)
        and (
            item.get("derived_clause_id") == clause_id
            or item.get("derived_label") == clause_id
            or str(item.get("section") or "").strip() == f"Пункт {clause_id.removeprefix('clause_')}"
        )
        and item.get("clause_status") == "context_sufficient"
        and item.get("evidence_status") == "USABLE_FOR_ANSWER"
        and item.get("structural_start_verified") is True
        and item.get("structural_end_verified") is True
        and item.get("continuity_verified") is True
    )


def preserve_requested_clause(
    visible: list[dict],
    derived: dict | None,
    *,
    target_clause: str | None,
    target_sources: list[str] | tuple[str, ...] | None,
    top_k: int,
    folder_filter: str | None = None,
) -> tuple[list[dict], str]:
    """Keep one *physically grounded* ENR result visible, with honest provenance.

    Only applies to an explicit, resolved document+clause and a heading-verified
    NormRegistry result. If a structurally complete matching result is already
    visible, keep it ahead of a partial. Otherwise put the requested partial
    clause first while preserving its score=0.85, EVIDENCE_PARTIAL and
    structural_end_verified=False. Keep the other hits' relative order.
    """
    original = list(visible[:max(0, top_k)])
    if not derived or not target_clause or not target_sources or top_k < 1:
        return original, "not_applicable"

    expected = tuple(_path_id(p) for p in target_sources if p)
    source_id = _path_id(derived.get("source_path"))
    if not source_id or source_id not in expected:
        return original, "source_mismatch"
    if folder_filter and _path_id(folder_filter) not in source_id:
        return original, "scope_mismatch"

    label = f"clause_{target_clause}"
    physical_ids = derived.get("physical_parent_ids") or []
    valid_parents = (
        isinstance(physical_ids, list)
        and any(isinstance(p, str) and p.strip() and p != "UNKNOWN" and not p.startswith("clause_") for p in physical_ids)
    )
    if (
        derived.get("retrieval_origin") != "ENR_DERIVED_CLAUSE"
        or derived.get("derived_clause_id") != label
        or derived.get("structural_start_verified") is not True
        or not valid_parents
    ):
        return original, "unverified_derived_clause"

    status = derived.get("clause_status")
    if status == "context_sufficient":
        if (
            derived.get("evidence_status") != "USABLE_FOR_ANSWER"
            or derived.get("structural_end_verified") is not True
        ):
            return original, "inconsistent_full_clause"
    elif status == "context_partial":
        if (
            derived.get("evidence_status") != "EVIDENCE_PARTIAL"
            or derived.get("structural_end_verified") is True
        ):
            return original, "inconsistent_partial_clause"
    else:
        return original, "unrecognized_clause_status"

    # Do not displace a genuinely verified full answer for the same clause.
    # "score: 1.0" alone, or an unrelated section, is never such a proof.
    for hit in original:
        if _is_complete_requested_clause(hit, clause_id=label, target_sources=expected):
            if hit is original[0]:
                return original, "verified_target_already_visible"
            return [hit] + [x for x in original if x is not hit][:top_k - 1], "verified_target_promoted"

    already_first = (
        original
        and original[0].get("derived_clause_id") == label
        and _same_target_source(original[0], expected)
    )
    if already_first:
        return original, "requested_clause_already_first"

    pinned: dict[str, Any] = dict(derived)
    pinned["rank_policy"] = "explicit_target_clause_identity"
    if status == "context_partial":
        pinned["evidence_warning"] = "PARTIAL_CLAUSE_STRUCTURAL_END_UNVERIFIED"
    remaining = [
        item for item in original
        if not (
            item.get("derived_clause_id") == label
            and _same_target_source(item, expected)
        )
    ]
    return [pinned] + remaining[:top_k - 1], (
        "partial_requested_clause_pinned"
        if status == "context_partial"
        else "complete_requested_clause_pinned"
    )
