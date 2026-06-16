"""Deterministic retrieval-quality metrics (RAGAS-style, no LLM judge).

Given retrieved results and a gold set of expected source substrings, computes
context-recall-style metrics: Hit@k, MRR, Precision@k. Used to quantify the
effect of changes (e.g. enabling the reranker) without re-embedding the corpus.
"""
from __future__ import annotations


def _blob(result: dict) -> str:
    return (
        f"{result.get('file_name','')} "
        f"{result.get('source_path','')} "
        f"{result.get('text','')}"
    ).casefold()


def is_relevant(result: dict, expected_any: list[str]) -> bool:
    blob = _blob(result)
    return any(str(e).casefold() in blob for e in expected_any)


def first_relevant_rank(results: list[dict], expected_any: list[str]) -> int | None:
    """1-based rank of the first relevant result, or None."""
    for i, r in enumerate(results, start=1):
        if is_relevant(r, expected_any):
            return i
    return None


def hit_at_k(results: list[dict], expected_any: list[str], k: int) -> bool:
    rank = first_relevant_rank(results[:k], expected_any)
    return rank is not None


def reciprocal_rank(results: list[dict], expected_any: list[str]) -> float:
    rank = first_relevant_rank(results, expected_any)
    return 1.0 / rank if rank else 0.0


def precision_at_k(results: list[dict], expected_any: list[str], k: int) -> float:
    top = results[:k]
    if not top:
        return 0.0
    hits = sum(1 for r in top if is_relevant(r, expected_any))
    return hits / len(top)


def evaluate_case(results: list[dict], expected_any: list[str], k: int) -> dict:
    return {
        f"hit@{k}": hit_at_k(results, expected_any, k),
        "rr": reciprocal_rank(results, expected_any),
        f"precision@{k}": precision_at_k(results, expected_any, k),
    }


def aggregate(per_case: list[dict], k: int) -> dict:
    n = len(per_case)
    if n == 0:
        return {f"hit_rate@{k}": 0.0, "mrr": 0.0, f"mean_precision@{k}": 0.0, "n": 0}
    return {
        f"hit_rate@{k}": sum(1 for c in per_case if c.get(f"hit@{k}")) / n,
        "mrr": sum(c.get("rr", 0.0) for c in per_case) / n,
        f"mean_precision@{k}": sum(c.get(f"precision@{k}", 0.0) for c in per_case) / n,
        "n": n,
    }
