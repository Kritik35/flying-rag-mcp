"""Deterministic scope router for retrieval.

Infers dataset / folder_filter for a query from a YAML term/pattern config,
without any LLM call. Complements (does not replace) ``query_planner``:
the planner expands a query into subqueries, the router decides *where* to look.

Design notes:
- Explicit ``dataset`` / ``folder_filter`` from the caller always win.
- A folder_filter is only auto-applied when the route is confident and not
  ambiguous (a single weak term must not force an aggressive filter).
- A cross-dataset conflict (e.g. "ОВ2" + "СП 7.13130") is marked ambiguous and
  neither dataset nor folder is forced, so one side is not silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = ROOT / "config" / "retrieval_terms.yaml"

TERM_WEIGHT = 1.0
PATTERN_WEIGHT = 2.0
# Terms >= this length match as a word-start stem ("противодым" -> "противодымная");
# shorter tokens require a full word boundary ("вк" must not hit "установки").
STEM_MIN_LEN = 5


@dataclass(frozen=True)
class RouteDecision:
    route: str
    dataset: str | None
    folder_filter: str | None
    confidence: float
    reason: str
    matched_terms: tuple[str, ...]
    ambiguous: bool
    structured: bool = False
    inferred_dataset: str | None = None
    inferred_folder_filter: str | None = None
    structured_label: str | None = None


# ── config loading ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_config(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        return {"confidence": {}, "domains": []}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _compiled_domains(path_str: str):
    cfg = _load_config(path_str)
    domains = []
    for d in cfg.get("domains", []):
        patterns = []
        for p in d.get("patterns", []) or []:
            try:
                patterns.append(re.compile(p))
            except re.error:
                continue
        terms = []
        for t in (d.get("terms") or []):
            norm = _normalize(t)
            if not norm:
                continue
            # Short tokens ("вк", "па", "пв", "ов2") need a full word boundary so
            # they don't match inside unrelated words ("вк" in "установки").
            # Longer terms act as stems matched at a word start ("противодым" ->
            # "противодымная"), so only a left boundary is required.
            if len(norm) >= STEM_MIN_LEN:
                term_re = re.compile(r"(?<!\w)" + re.escape(norm))
            else:
                term_re = re.compile(r"(?<!\w)" + re.escape(norm) + r"(?!\w)")
            terms.append((norm, term_re))
        domains.append(
            {
                "id": d.get("id", "domain"),
                "dataset": d.get("dataset"),
                "folder_filter": d.get("folder_filter"),
                # A domain with scope: false is scored for its side effect only
                # (the structured hint) and never competes for dataset/folder.
                "scope": bool(d.get("scope", True)),
                "terms": terms,
                "patterns": patterns,
            }
        )
    conf = cfg.get("confidence", {}) or {}
    settings = {
        "confident": float(conf.get("confident", 0.62)),
        "ambiguous_gap": float(conf.get("ambiguous_gap", 0.12)),
        "cross_dataset_ratio": float(conf.get("cross_dataset_ratio", 0.4)),
    }
    return domains, settings


# ── helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "").casefold().replace("ё", "е")).strip()


def suggest_structured_label(query: str) -> str | None:
    q = _normalize(query)
    if "параметр настройки" in q:
        return "Параметр настройки"
    if "потеря давления" in q:
        return "Потеря давления"
    if "падение давления" in q:
        return "Падение давления"
    return None


def _score_domain(norm_query: str, domain: dict) -> tuple[float, list[str]]:
    matched: list[str] = []
    score = 0.0
    for term, term_re in domain["terms"]:
        if term_re.search(norm_query):
            matched.append(term)
            score += TERM_WEIGHT
    for pat in domain["patterns"]:
        if pat.search(norm_query):
            matched.append(pat.pattern)
            score += PATTERN_WEIGHT
    return score, matched


# ── public API ────────────────────────────────────────────────────────────────

def route_query(
    query: str,
    explicit_dataset: str | None = None,
    explicit_folder_filter: str | None = None,
    config_path: str | None = None,
) -> RouteDecision:
    domains, settings = _compiled_domains(config_path or str(_CONFIG_PATH))
    norm_query = _normalize(query)

    scored = []
    structured_matched = False
    for d in domains:
        score, matched = _score_domain(norm_query, d)
        if d["id"] == "structured_table" and score > 0:
            structured_matched = True
        if score > 0 and d.get("scope", True):
            scored.append((score, d, matched))

    structured_label = suggest_structured_label(query) if structured_matched else None

    if not scored:
        return RouteDecision(
            route="default",
            dataset=explicit_dataset,
            folder_filter=explicit_folder_filter,
            confidence=0.0,
            reason="no deterministic domain match",
            matched_terms=(),
            ambiguous=False,
            structured=structured_matched,
            inferred_dataset=None,
            inferred_folder_filter=None,
            structured_label=structured_label,
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    total = sum(s for s, _, _ in scored)
    top_score, top, top_matched = scored[0]
    confidence = top_score / total if total else 0.0

    ambiguous = False
    cross_conflict = False
    if len(scored) > 1:
        second_score, second, _ = scored[1]
        gap = (top_score - second_score) / total if total else 0.0
        if gap < settings["ambiguous_gap"]:
            ambiguous = True
        if (
            second["dataset"] != top["dataset"]
            and second_score >= settings["cross_dataset_ratio"] * top_score
        ):
            ambiguous = True
            cross_conflict = True

    # Inferred values (pure inference from the query)
    inferred_dataset = None if cross_conflict else top["dataset"]
    apply_folder = (
        not ambiguous
        and confidence >= settings["confident"]
        and top["folder_filter"] is not None
    )
    inferred_folder = top["folder_filter"] if apply_folder else None

    # Honour explicit caller params (never override)
    final_dataset = explicit_dataset if explicit_dataset is not None else inferred_dataset
    final_folder = (
        explicit_folder_filter
        if explicit_folder_filter is not None
        else inferred_folder
    )

    reason_bits = [f"top={top['id']}({top_score:.0f})", f"conf={confidence:.2f}"]
    if cross_conflict:
        reason_bits.append("cross-dataset-conflict")
    elif ambiguous:
        reason_bits.append("ambiguous-gap")
    if explicit_dataset is not None:
        reason_bits.append("explicit-dataset")
    if explicit_folder_filter is not None:
        reason_bits.append("explicit-folder")

    return RouteDecision(
        route=top["id"],
        dataset=final_dataset,
        folder_filter=final_folder,
        confidence=round(confidence, 4),
        reason="; ".join(reason_bits),
        matched_terms=tuple(top_matched),
        ambiguous=ambiguous,
        structured=structured_matched,
        inferred_dataset=inferred_dataset,
        inferred_folder_filter=inferred_folder,
        structured_label=structured_label,
    )
