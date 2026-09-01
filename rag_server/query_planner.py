from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import re
from typing import Iterable


@dataclass(frozen=True)
class QueryPlan:
    route: str
    reason: str
    queries: list[str]
    broad: bool = False


FIRE_SMOKE_TOKENS = (
    "противодым",
    "дымоудал",
    "дымозащит",
    "подпор",
    "сп 7",
    "7.13130",
)

FIRE_EGRESS_TOKENS = (
    "эвакуац",
    "путь эвак",
    "выход",
    "лестнич",
    "сп 1",
    "1.13130",
)

HVAC_TOKENS = (
    "вентиляц",
    "отоплен",
    "кондиционир",
    "воздухообмен",
    "расход воздуха",
    "микроклимат",
    "сп 60",
    "60.13330",
)

# What a project question is actually asking for. The artefact it names lives
# in the sheet's own title block — "Спецификация оборудования, изделий и
# материалов" — while the body of that sheet is rows of parts and GOSTs. Asking
# for "перечень оборудования" therefore matches nothing in the document that
# holds the answer, so the expansion has to say the artefact's real name.
PROJECT_SHEET_EXPANSIONS = (
    (
        ("оборудован", "спецификац", "перечень", "номенклатур", "материал"),
        "спецификация оборудования, изделий и материалов",
        "ведомость объёмов работ спецификация марка тип количество",
    ),
    (
        ("изменени", "замен", "ревизи"),
        "таблица регистрации изменений номера листов заменённых новых",
        "изм. кол.уч. лист №док. подп. дата лист изменений",
    ),
    (
        ("ведомость", "чертеж", "комплект", "лист"),
        "ведомость рабочих чертежей основного комплекта",
        "общие данные ведомость ссылочных и прилагаемых документов",
    ),
    (
        ("раздел", "состав", "что входит", "пояснительн"),
        "пояснительная записка содержание раздела проектной документации",
        "общая часть основание для разработки исходные данные",
    ),
)


PP87_TOKENS = (
    "87",
    "постановлен",
    "раздел",
    "проектн",
    "состав проект",
)

# Router vocabulary and planner vocabulary used to be two lists that drifted
# apart: a query the router placed in a domain could still reach the store as a
# single unexpanded string because the planner's own tokens did not know the
# words it was phrased with. The route is the shared decision; these are the
# expansions it implies.
ROUTE_EXPANSIONS = {
    "normative_fire": (
        "fire/smoke route",
        (
            "СП 7.13130 противодымная вентиляция дымоудаление требования",
            "удаление продуктов горения из коридоров и помещений",
            "дымоудаление допускается не предусматривать исключения",
            "системы вытяжной противодымной вентиляции подпор воздуха лестничные клетки",
        ),
    ),
    "normative_fire_alarm": (
        "fire alarm route",
        (
            "СП 484.1311500 системы пожарной сигнализации требования",
            "СП 486.1311500 перечень зданий подлежащих защите пожарной сигнализацией",
            "размещение пожарных извещателей в помещении",
            "СП 3.13130 система оповещения и управления эвакуацией",
        ),
    ),
    "normative_accessibility": (
        "accessibility route",
        (
            "СП 59.13330 доступность зданий для маломобильных групп населения",
            "пути движения инвалидов внутри здания требования",
            "габариты проходов и подъёмных устройств для МГН",
        ),
    ),
    "normative_hvac": (
        "hvac route",
        (
            "СП 60.13330 отопление вентиляция кондиционирование требования",
            "расход воздуха воздухообмен микроклимат вентиляция помещений",
            "приточная вытяжная вентиляция расчет воздуха",
        ),
    ),
}


BROAD_QUESTION_TOKENS = (
    "где",
    "в каких",
    "когда",
    "для каких",
    "нужна",
    "требуется",
    "обязательно",
    "случа",
    "перечисл",
)


def _cf(text: object) -> str:
    return str(text or "").casefold()


def _has_any(text: str, tokens: Iterable[str]) -> bool:
    return any(token in text for token in tokens)


def _dedupe_keep_order(items: Iterable[str], limit: int = 6) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = re.sub(r"\s+", " ", item.strip())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        result.append(normalized)
        seen.add(key)
        if len(result) >= limit:
            break
    return result


def plan_query(
    query: str, dataset: str | None = None, route: str | None = None
) -> QueryPlan:
    """Build cheap deterministic subqueries for broad engineering questions.

    ``route`` is the router's decision. Its own token heuristics come first —
    they are more specific — and the route is the fallback for a query phrased
    in words the planner does not carry.
    """
    lowered = _cf(query)
    broad = _has_any(lowered, BROAD_QUESTION_TOKENS)

    if dataset == "project" and _has_any(lowered, FIRE_SMOKE_TOKENS):
        expansions = [
            query,
            "ОВ2 ПВ противодымная вентиляция дымоудаление подпор воздуха",
            "система дымоудаления вытяжная противодымная вентиляция лист схема",
            "противодымная защита вентиляция проектная документация ОВ ПВ",
        ]
        return QueryPlan(
            route="project_smoke",
            reason="project smoke-control terms",
            queries=_dedupe_keep_order(expansions, limit=4),
            broad=broad,
        )

    # A project question must not be expanded with norm wording. The token
    # lists below match on subject alone, so "перечень оборудования по
    # вентиляции в проекте" used to take the HVAC branch and go to the store
    # as "СП 60.13330 отопление вентиляция кондиционирование требования" —
    # searched inside the project's own sheets, where no norm can be, while the
    # dataset filter kept the norms out. Three of four subqueries wasted.
    if dataset == "project":
        for tokens, *expansions in PROJECT_SHEET_EXPANSIONS:
            if _has_any(lowered, tokens):
                return QueryPlan(
                    route="project_sheet",
                    reason="project sheet artefact terms",
                    queries=_dedupe_keep_order([query, *expansions], limit=4),
                    broad=broad,
                )
        return QueryPlan(
            route="project_scope",
            reason="project scope without a recognised artefact",
            queries=[query],
            broad=broad,
        )

    if _has_any(lowered, FIRE_SMOKE_TOKENS):
        expansions = [
            query,
            "СП 7.13130 противодымная вентиляция дымоудаление требования",
            "дымоудаление допускается не предусматривать исключения",
            "противодымная защита автостоянки тоннели атриумы общественные здания",
            "системы вытяжной противодымной вентиляции подпор воздуха лестничные клетки",
        ]
        return QueryPlan(
            route="fire_smoke",
            reason="fire/smoke-control terms",
            queries=_dedupe_keep_order(expansions, limit=5),
            broad=broad,
        )

    if _has_any(lowered, FIRE_EGRESS_TOKENS):
        expansions = [
            query,
            "СП 1.13130 эвакуационные пути и выходы требования",
            "ширина эвакуационных выходов лестничные клетки коридоры",
            "пожарная безопасность эвакуация людей из зданий",
        ]
        return QueryPlan(
            route="fire_egress",
            reason="fire/egress terms",
            queries=_dedupe_keep_order(expansions, limit=4),
            broad=broad,
        )

    if _has_any(lowered, HVAC_TOKENS):
        expansions = [
            query,
            "СП 60.13330 отопление вентиляция кондиционирование требования",
            "расход воздуха воздухообмен микроклимат вентиляция помещений",
            "приточная вытяжная вентиляция расчет воздуха",
        ]
        return QueryPlan(
            route="hvac",
            reason="hvac terms",
            queries=_dedupe_keep_order(expansions, limit=4),
            broad=broad,
        )

    if _has_any(lowered, PP87_TOKENS):
        expansions = [
            query,
            "Постановление 87 состав разделов проектной документации",
            "требования к содержанию разделов проектной документации",
            "пояснительная записка проект организации строительства перечень мероприятий",
        ]
        return QueryPlan(
            route="project_documentation",
            reason="project documentation composition terms",
            queries=_dedupe_keep_order(expansions, limit=4),
            broad=broad,
        )

    expansion = ROUTE_EXPANSIONS.get(route or "")
    if expansion:
        reason, extra = expansion
        return QueryPlan(
            route=route,
            reason=reason,
            queries=_dedupe_keep_order([query, *extra], limit=5),
            broad=broad,
        )

    return QueryPlan(route="default", reason="no deterministic route", queries=[query], broad=broad)


def _merge_key(item: dict) -> str:
    for key in ("parent_id", "chunk_id", "id"):
        value = item.get(key)
        if value:
            return f"{key}:{value}"
    source = item.get("source_path") or item.get("file_name") or item.get("doc_id") or ""
    text = re.sub(r"\s+", " ", _cf(item.get("text")))[:240]
    return f"text:{source}:{text}"


def fuse_ranked_results(result_lists: list[list[dict]], limit: int, k: int = 60) -> list[dict]:
    """Fuse several ranked retrieval lists with Reciprocal Rank Fusion."""
    if not result_lists:
        return []

    merged: dict[str, dict] = {}
    for query_index, results in enumerate(result_lists):
        for rank, raw in enumerate(results, start=1):
            key = _merge_key(raw)
            base = float(raw.get("score") or 0.0)
            rrf = 1.0 / (k + rank)
            if key not in merged:
                item = deepcopy(raw)
                item["_fusion_score"] = 0.0
                item["_base_score"] = base
                item["_matched_query_indexes"] = set()
                merged[key] = item

            item = merged[key]
            item["_fusion_score"] += rrf
            item["_base_score"] = max(float(item.get("_base_score") or 0.0), base)
            item["_matched_query_indexes"].add(query_index)

    fused = list(merged.values())
    fused.sort(
        key=lambda item: (
            item.get("_fusion_score", 0.0),
            item.get("_base_score", 0.0),
        ),
        reverse=True,
    )

    output: list[dict] = []
    for item in fused[: max(1, limit)]:
        matched = item.pop("_matched_query_indexes", set())
        fusion_score = float(item.pop("_fusion_score", 0.0))
        base_score = float(item.pop("_base_score", item.get("score") or 0.0))
        item["matched_queries"] = len(matched)
        item["score"] = round(base_score + min(0.08, fusion_score * 2.0), 4)
        output.append(item)
    return output
