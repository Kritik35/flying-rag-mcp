from __future__ import annotations

import re
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Iterable

from rag_server.query_shape import exact_hits, exact_tokens


STOPWORDS = {
    "для", "или", "при", "над", "под", "это", "что", "как", "где",
    "the", "and", "with", "from", "this", "that",
}

TITLE_MARKERS = (
    "утвержден",
    "введен в действие",
    "национальный стандарт",
    "межгосударственный стандарт",
    "предисловие",
    "дата введения",
    "окс ",
    "мкс ",
    "информация об изменениях",
    "федерального агентства по техническому регулированию",
)

SUBSTANTIVE_MARKERS = (
    "должен",
    "должна",
    "должны",
    "следует",
    "не менее",
    "не более",
    "допускается",
    "принимается",
    "требования",
    "таблица",
    "пункт",
    "расчет",
    "расчёт",
    "предел",
)

PROJECT_DISCIPLINES = {
    "ов": ("ов", "пв", "вентиляц", "дымоудален", "противодым", "подпор"),
    "вк": ("вк", "водопровод", "канализац"),
    "эом": ("эом", "электро", "освещен", "светильник", "кабель"),
    "спз": ("спз", "пожар", "сигнализац", "оповещен"),
}

STAMP_MARKERS = (
    "copyright by",
    "формат:",
    "подп. дата",
    "подп. и дата",
    "инв.",
    "инв.№",
    "лист листов",
    "стадия",
    "кол.уч",
    "№док",
    "заказчик:",
    "разраб.",
    "проверил",
    "н.контр",
)


def _cf(text: object) -> str:
    return str(text or "").casefold()


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[0-9a-zа-яё]+", text.casefold())
        if len(t) >= 2 and t not in STOPWORDS
    ]


def _query_tokens(query: str) -> set[str]:
    return {t for t in _tokens(query) if len(t) >= 3}


def title_penalty(text: str) -> float:
    lowered = _cf(text)
    first_part = lowered[:1800]
    matches = sum(1 for marker in TITLE_MARKERS if marker in first_part)
    if matches == 0:
        return 0.0
    penalty = min(0.48, 0.12 * matches)
    if "1. область применения" in lowered or "область применения" in lowered:
        penalty *= 0.65
    return round(penalty, 4)


def table_noise_penalty(text: str) -> float:
    lowered = _cf(text)
    if not lowered.strip():
        return 0.35

    lines = [line.strip() for line in lowered.splitlines() if line.strip()]
    pipe_count = lowered.count("|")
    line_count = max(1, len(lines))
    table_lines = sum(1 for line in lines if line.count("|") >= 3)

    tokens = _tokens(lowered)
    token_count = max(1, len(tokens))
    counts = Counter(tokens)
    repeated_top = counts.most_common(1)[0][1] / token_count if counts else 0.0
    short_token_ratio = sum(1 for t in tokens if len(t) <= 2) / token_count
    digit_token_ratio = sum(1 for t in tokens if any(ch.isdigit() for ch in t)) / token_count
    code_like_count = sum(
        1
        for t in tokens
        if any(ch.isdigit() for ch in t) and (len(t) >= 5 or "-" in t or "." in t)
    )
    dimension_count = len(re.findall(r"\b\d{2,5}\s*[xх]\s*\d{2,5}\b", lowered))
    elevation_count = len(re.findall(r"[-+]\d{1,3}[,.]\d{2,3}\b", lowered))

    penalty = 0.0
    if pipe_count >= 10:
        penalty += min(0.28, pipe_count / max(200.0, len(lowered)) * 4.0)
    if table_lines / line_count >= 0.35:
        penalty += 0.18
    if repeated_top >= 0.18:
        penalty += 0.16
    if lowered.count("шт.") >= 8:
        penalty += 0.12
    if re.search(r"\bа(?:\s+а){8,}\b", lowered):
        penalty += 0.22
    if short_token_ratio >= 0.55 and token_count >= 25:
        penalty += 0.10
    if digit_token_ratio >= 0.35 and token_count >= 20:
        penalty += 0.14
    if code_like_count >= 8:
        penalty += 0.16
    if dimension_count >= 2:
        penalty += 0.12
    if elevation_count >= 3:
        penalty += 0.12

    stamp_matches = sum(1 for marker in STAMP_MARKERS if marker in lowered)
    if stamp_matches >= 3:
        penalty += min(0.34, 0.08 * stamp_matches)

    return round(min(0.58, penalty), 4)


def lexical_bonus(query: str, result: dict) -> float:
    query_terms = _query_tokens(query)
    if not query_terms:
        return 0.0

    text = _cf(result.get("text"))
    file_name = _cf(result.get("file_name"))
    source_path = _cf(result.get("source_path"))
    source_blob = f"{file_name} {source_path}"

    text_matches = sum(1 for token in query_terms if token in text)
    source_matches = sum(1 for token in query_terms if token in source_blob)
    bonus = min(0.22, text_matches * 0.045)
    bonus += min(0.20, source_matches * 0.055)

    query_phrase = " ".join(_tokens(query))
    if query_phrase and query_phrase in text:
        bonus += 0.10

    return round(min(0.38, bonus), 4)


def substantive_bonus(text: str, dataset: str | None) -> float:
    lowered = _cf(text)
    matches = sum(1 for marker in SUBSTANTIVE_MARKERS if marker in lowered)
    bonus = min(0.20, matches * 0.035)
    if dataset == "normative" and re.search(r"(?:^|\s)(?:п\.|пункт|таблица)\s*\d+", lowered):
        bonus += 0.05
    return round(min(0.25, bonus), 4)


def path_bonus(query: str, result: dict, dataset: str | None) -> float:
    query_l = _cf(query)
    file_name = _cf(result.get("file_name"))
    source_path = _cf(result.get("source_path"))
    source_blob = f"{file_name} {source_path}"

    bonus = 0.0
    penalty = 0.0

    if dataset == "project":
        wanted = [
            key
            for key, markers in PROJECT_DISCIPLINES.items()
            if key in query_l or any(marker in query_l for marker in markers)
        ]
        if wanted:
            matched = any(
                key in source_blob or any(marker in source_blob for marker in PROJECT_DISCIPLINES[key])
                for key in wanted
            )
            if matched:
                bonus += 0.24
            else:
                penalty += 0.18

        if "эом" in source_blob and any(m in query_l for m in ("ов", "вентиляц", "противодым", "дымоудален")):
            penalty += 0.16

    source_matches = sum(1 for token in _query_tokens(query) if token in source_blob)
    bonus += min(0.12, source_matches * 0.03)

    return round(max(-0.35, min(0.35, bonus - penalty)), 4)


def score_result(query: str, result: dict, dataset: str | None = None) -> dict:
    item = deepcopy(result)
    base_score = float(item.get("score") or 0.0)
    text = item.get("text") or ""

    quality = {
        "base_score": round(base_score, 4),
        "title_penalty": title_penalty(text),
        "table_penalty": table_noise_penalty(text),
        "lexical_bonus": lexical_bonus(query, item),
        "substantive_bonus": substantive_bonus(text, dataset),
        "path_bonus": path_bonus(query, item, dataset),
        "exact_hits": 0,
        "exact_bonus": 0.0,
    }

    # A verbatim identifier is the strongest signal this function has. Without
    # it the scorer prefers a norm's prose over a project sheet's table — it
    # hands out substantive_bonus for connected text and table_penalty for a
    # table — so a lookup for «С.П2.15.114» came back answered by СП 326 and
    # СП 53, which do not contain the code, while chunks that do fell away.
    identifiers = exact_tokens(query)
    if identifiers:
        hits = exact_hits(identifiers, f"{item.get('text', '')} "
                                       f"{item.get('file_name', '')}")
        quality["exact_hits"] = hits
        quality["exact_bonus"] = round(min(0.45, 0.25 * hits), 4)

    adjusted = (
        base_score
        + quality["exact_bonus"]
        + quality["lexical_bonus"]
        + quality["substantive_bonus"]
        + quality["path_bonus"]
        - quality["title_penalty"]
        - quality["table_penalty"]
    )
    quality["adjusted_score"] = round(max(0.0, min(1.0, adjusted)), 4)

    item["score"] = quality["adjusted_score"]
    item["quality"] = quality
    return item


_COPY_SUFFIX_RE = re.compile(r"[\s_]*\(\d+\)$")


# Номер изменения листа РД: «…-31.02.1-06» -> лист «…-31.02.1», изменение 6.
# Обрезается только там, где в имени уже есть номер листа с точкой, иначе
# правило съело бы хвосты обычных имён. Год в обозначении нормы
# («ГОСТ 12.1.019-2017») не подходит под шаблон: там четыре цифры, не две.
_REVISION_RE = re.compile(r"(?<=\d)-(\d{2})$")
_SHEET_NUMBER_RE = re.compile(r"\d\.\d")


def _stem_of(item: dict) -> str:
    raw = item.get("source_path") or item.get("file_name") or item.get("doc_id") or ""
    name = re.split(r"[\\/]", str(raw))[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return _COPY_SUFFIX_RE.sub("", stem.strip().casefold()).strip()


def revision_of(item: dict) -> int:
    """Номер изменения листа; 0, если в имени его нет."""
    stem = _stem_of(item)
    if not _SHEET_NUMBER_RE.search(stem):
        return 0
    match = _REVISION_RE.search(stem)
    return int(match.group(1)) if match else 0


def document_key(item: dict) -> str:
    """Identity of the *document*, not of the file that carries it.

    The corpus holds the same norm as .docx and as .pdf, under different paths
    and different doc_ids. A cap keyed on the path therefore gave a document one
    budget per copy: with three copies of СП 120.13330 in the store it took four
    of five answer slots while the norm that answered the question, held in a
    single copy, kept two and was then dropped entirely by source concentration.

    A sheet's revision number is part of the file name too, and 185 of the 1851
    indexed files are a second or third revision of a sheet already there. Asked
    for a room code, the search answered with изм.4 twice and изм.6 twice — four
    of five slots on one sheet. The revision is stripped here and read back by
    `revision_of`, so the sheet gets one budget and the newer revision is the
    one shown.
    """
    stem = _stem_of(item)
    if _SHEET_NUMBER_RE.search(stem):
        return _REVISION_RE.sub("", stem)
    return stem


def _diversify(results: Iterable[dict], top_k: int, max_per_doc: int) -> list[dict]:
    results = list(results)

    # Из всех редакций листа, попавших в пул, в ответ идёт только старшая.
    # Лимит на документ их не разводит: он считает изм.4 и изм.6 за один
    # документ, и обе редакции спокойно помещаются в его бюджет — на запросе
    # по кодам помещений рядом стояли `…-31.17-06.pdf` и `…-31.17-04.pdf`,
    # то есть один лист, показанный дважды.
    #
    # Максимум берётся по пулу, а не по порядку очков: иначе редакция ответа
    # зависела бы от того, какой кусок текста набрал больше, и на один вопрос
    # выпадал бы действующий лист, а на соседний — отменённый.
    #
    # Цена прямая: если у старшей редакции кусок в пуле хуже, ответ станет
    # хуже. Для рабочей документации это лучше, чем молча показать лист,
    # который уже заменён.
    newest: defaultdict[str, int] = defaultdict(int)
    for item in results:
        key = document_key(item) or item.get("doc_id") or ""
        newest[key] = max(newest[key], revision_of(item))

    selected: list[dict] = []
    per_doc: defaultdict[str, int] = defaultdict(int)
    seen_text: set[str] = set()

    for item in results:
        key = document_key(item) or item.get("doc_id") or ""
        if revision_of(item) < newest[key]:
            continue
        text_key = re.sub(r"\s+", " ", _cf(item.get("text")))[:260]
        if text_key and text_key in seen_text:
            continue
        if per_doc[key] >= max_per_doc:
            continue
        selected.append(item)
        per_doc[key] += 1
        if text_key:
            seen_text.add(text_key)
        if len(selected) >= top_k:
            return selected

    return selected


def apply_retrieval_quality(
    query: str,
    results: list[dict],
    dataset: str | None = None,
    top_k: int = 5,
    max_per_doc: int = 2,
) -> list[dict]:
    if not results:
        return []

    scored = [score_result(query, result, dataset=dataset) for result in results]
    scored.sort(
        key=lambda item: (
            # exact_hits leads the tie-breaks: the displayed score is clamped at
            # 1.0 and a third of results reach it, so without this a chunk that
            # carries the asked-for code ties with one that does not and the
            # order is settled by something unrelated.
            item.get("quality", {}).get("exact_hits", 0),
            item.get("score", 0.0),
            item.get("quality", {}).get("lexical_bonus", 0.0),
            item.get("quality", {}).get("path_bonus", 0.0),
            # Последним: между двумя редакциями одного листа, у которых всё
            # остальное сравнялось, показывается свежая. Выше ставить нельзя —
            # номер изменения не признак того, что лист отвечает на вопрос.
            revision_of(item),
        ),
        reverse=True,
    )
    return _diversify(scored, max(1, top_k), max(1, max_per_doc))
