from __future__ import annotations
import re

"""
storage/source_focus.py

Source concentration & Lexical Boost: 
1. rank_chunks_for_query: Apply a lexical boost on top of vector score for exact matches of query tokens.
2. concentrate_sources: Keep chunks from the most relevant documents only to reduce context contamination.

Ported from les_rag2/proxy/services/saferag_service.py.
"""

STOPWORDS = {
    "какая", "какие", "какой", "каким", "что", "это", "для", "или", "при", "над",
    "под", "если", "есть", "нужно", "нужен", "требуется", "применяется", "применяются",
    "регулируется", "относится", "относятся"
}


def rank_chunks_for_query(query: str, results: list[dict]) -> list[dict]:
    """
    Начисление лексического буста к скору за точное совпадение слов поискового запроса.
    Повышает точность при поиске аббревиатур (СП, ГОСТ) и номеров пунктов.
    """
    if not query or not results:
        return results

    tokens = {
        token
        for token in re.findall(r"[0-9a-zа-яё]{3,}", query.casefold())
        if token not in STOPWORDS and len(token) >= 4
    }

    if not tokens:
        return results

    boosted = []
    for r in results:
        text = r.get("text", "").casefold()
        file_name = r.get("file_name", "").casefold()

        matches = sum(1 for t in tokens if t in text)
        title_matches = sum(1 for t in tokens if t in file_name)

        score = r.get("score", 0.0)
        boosted_score = score + matches * 0.12 + title_matches * 0.03
        r["score"] = round(min(1.0, boosted_score), 4)
        boosted.append(r)

    return sorted(boosted, key=lambda x: x["score"], reverse=True)


def concentrate_sources(
    results: list[dict],
    max_docs: int = 3,
    min_score: float = 0.40,
    query: str | None = None,
) -> list[dict]:
    """
    Фильтрация результатов поиска для удержания чанков только из top_docs наиболее релевантных документов.

    Args:
        results:   список результатов поиска (чанков)
        max_docs:  максимальное количество документов
        min_score: порог отсечения по скору
        query:     поисковый запрос (если передан, сначала применяется лексический буст)
    """
    if not results:
        return results

    # Сначала применяем лексический буст, если передан запрос
    if query:
        results = rank_chunks_for_query(query, results)

    # Фильтруем по min_score
    filtered = [r for r in results if r.get("score", 1.0) >= min_score]
    if not filtered:
        filtered = list(results)

    # Находим лучшие скоры по каждому документу
    doc_best: dict[str, float] = {}
    for r in filtered:
        key = r.get("doc_id") or r.get("file_name") or ""
        score = r.get("score", 0.0)
        if key not in doc_best or doc_best[key] < score:
            doc_best[key] = score

    top_docs = set(sorted(doc_best, key=lambda k: -doc_best[k])[:max_docs])
    return [r for r in filtered if (r.get("doc_id") or r.get("file_name") or "") in top_docs]
