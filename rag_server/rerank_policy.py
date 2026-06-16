from __future__ import annotations

from dataclasses import dataclass

from rag_server.query_planner import QueryPlan


COMPLEX_ROUTES = {
    "fire_smoke",
    "fire_egress",
    "hvac",
    "project_documentation",
}


@dataclass(frozen=True)
class RerankDecision:
    apply: bool
    reason: str


def _top_scores(quality_pool: list[dict], top_k: int) -> list[float]:
    return [float(item.get("score") or 0.0) for item in quality_pool[: max(1, top_k)]]


def decide_rerank(
    explicit_rerank: bool | None,
    auto_enabled: bool,
    plan: QueryPlan,
    quality_pool: list[dict],
    top_k: int,
) -> RerankDecision:
    if explicit_rerank is True:
        return RerankDecision(True, "forced")
    if explicit_rerank is False:
        return RerankDecision(False, "disabled")
    if not auto_enabled:
        return RerankDecision(False, "auto_disabled")
    if len(quality_pool) <= top_k:
        return RerankDecision(False, "too_few_candidates")

    if plan.route in COMPLEX_ROUTES and (plan.broad or len(plan.queries) > 1):
        return RerankDecision(True, "complex_route")

    scores = _top_scores(quality_pool, top_k)
    if scores and max(scores) < 0.45:
        return RerankDecision(True, "weak_scores")
    if len(scores) >= 2 and (scores[0] - scores[-1]) < 0.04 and scores[0] < 0.70:
        return RerankDecision(True, "ambiguous_scores")

    return RerankDecision(False, "not_needed")
