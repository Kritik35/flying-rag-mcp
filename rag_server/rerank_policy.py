from __future__ import annotations

from dataclasses import dataclass

from rag_server.query_planner import QueryPlan


# Kept for the routes that predate route-driven planning; the decision below no
# longer depends on membership. A list of route names is exactly the thing that
# drifts: the planner grew normative_fire, normative_hvac, project_scope and
# others, this set was not updated, and 16 of 20 golden queries silently stopped
# being reranked — auto mode scored hit@5 0.65 where a forced rerank scored
# 0.80, and the MCP tool defaults to auto.
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

    # What the planner did, rather than what the route is called. Expanding a
    # query into several subqueries is the planner saying the question was not
    # a single lookup; the fused pool that comes back is exactly what a
    # cross-encoder is for.
    if len(plan.queries) > 1:
        return RerankDecision(True, "expanded_query")

    scores = _top_scores(quality_pool, top_k)
    if scores and max(scores) < 0.45:
        return RerankDecision(True, "weak_scores")
    if len(scores) >= 2 and (scores[0] - scores[-1]) < 0.04 and scores[0] < 0.70:
        return RerankDecision(True, "ambiguous_scores")

    return RerankDecision(False, "not_needed")
