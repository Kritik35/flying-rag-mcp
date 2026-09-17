"""What shape is this query, and what does that shape need?

Two kinds of query reach this system, and they want opposite things from the
hybrid. Taken from 191 real queries in the working history:

    С.П2.15.114                        room code
    1.02.11.024 1.02.11.025            room codes
    П1-TRF-01-01 ХОВС                  system tag
    завеса воздушная водяная спецификация   keywords
    в каких случаях нужно предусматривать удаление дыма   question

A question carries meaning, and the dense channel is the good judge of meaning.
A code carries none: the embedder answers it with noise, and — worse — a code
like «С.П2.15.114» looks like a norm designation, so the noise comes back
confidently normative. Only the lexical channel can match a code, and at the
default alpha=0.7 it is outvoted.

Measured before this module existed:

    «1.02.11.024 1.02.11.025»   alpha 0.7 → 0 of 5 contain the code
                                alpha 0.3 → 4 of 5
    «завеса воздушная водяная спецификация»
                                alpha 0.7 → 0 project documents
                                alpha 0.3 → 4 of 5

Nothing here changes what happens to a question: no identifier in the query and
every value below is the one already in use.
"""
from __future__ import annotations

import re

# An identifier is a token that carries a digit and is structured — dotted,
# hyphenated, or letters glued to digits. A bare number is a quantity, not an
# identifier: "расход 60 м3/ч" must not turn into a lookup.
_TOKEN_RE = re.compile(r"[^\s,;()\[\]«»\"']+")
_HAS_DIGIT = re.compile(r"\d")
_HAS_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
_DOTTED = re.compile(r"^\w+(?:[.\-/]\w+){2,}$")          # 1.02.11.024, П1-TRF-01-01
_GLUED = re.compile(r"^(?=.*[A-Za-zА-Яа-яЁё])(?=.*\d)[\w.\-/]{5,}$")  # O01163, С.П2.15.114
# Марка системы из двух частей: «В1-а», «П2-CAF», «ДВ1-PAR». Прежние шаблоны
# требовали трёх частей или пяти знаков подряд, и такая марка не опознавалась
# вовсе. Цифра обязана стоять в ПЕРВОЙ части — этим обычные слова с дефисом
# («во-первых», «из-за», «тепло-холодоснабжение») отсекаются целиком.
#
# Разделитель только дефис. С косой чертой шаблон совпадает с единицей
# измерения — «м3/ч» устроена ровно так же, — и «расход 60 м3/ч» превращался
# в поиск по шифру. Все марки в этом корпусе пишутся через дефис.
_SHORT_MARK = re.compile(r"^[A-Za-zА-Яа-яЁё]{1,4}\d{1,3}-[\w]{1,6}$")
_PURE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_LEXICAL_ALPHA = 0.25


def _looks_like_identifier(token: str) -> bool:
    token = token.strip(".,;:")
    if len(token) < 3 or not _HAS_DIGIT.search(token):
        return False
    if _PURE_NUMBER.match(token):
        return False
    if _DOTTED.match(token):
        return True
    if _SHORT_MARK.match(token):
        return True
    return bool(_GLUED.match(token) and _HAS_LETTER.search(token))


def exact_tokens(query: str) -> list[str]:
    """Identifiers in the query that must be matched verbatim, in order."""
    from rag_server.named_norms import extract_norm_designations

    found: list[str] = []
    for designation in extract_norm_designations(query):
        if designation not in found:
            found.append(designation)

    covered = " ".join(found).casefold()
    for token in _TOKEN_RE.findall(str(query or "")):
        cleaned = token.strip(".,;:")
        if not _looks_like_identifier(cleaned):
            continue
        if cleaned.casefold() in covered or cleaned in found:
            continue
        found.append(cleaned)
    return found


def is_exact_query(query: str) -> bool:
    """Is this a lookup by identifier rather than a question?

    A question that merely cites a norm — "кратность воздухообмена … СП 60.13330"
    — is still a question: the words carry it, and the citation only hints at
    scope. Treating it as a lookup would break the queries that work today. So
    the identifiers have to be most of what was typed.
    """
    identifiers = exact_tokens(query)
    if not identifiers:
        return False
    words = [t for t in _TOKEN_RE.findall(str(query or "")) if len(t) > 2]
    if not words:
        return False
    # Norm designations are two tokens ("СП 60.13330") but one identifier.
    identifier_tokens = sum(len(i.split()) for i in identifiers)
    return identifier_tokens >= max(1, len(words) // 2)


def lexical_alpha(query: str, default: float, explicit: bool = False) -> float:
    """Vector-channel weight for this query.

    `explicit` means the caller passed an alpha of their own; that is a
    decision, not a suggestion, and it stands.
    """
    if explicit or not is_exact_query(query):
        return default
    return min(default, _LEXICAL_ALPHA)


def exact_hits(query_identifiers, text: str) -> int:
    """How many of the query's identifiers appear verbatim in the text.

    A verbatim identifier is the strongest relevance signal available here —
    stronger than any heuristic about whether the surrounding text reads like
    prose. The scoring function otherwise prefers a norm's prose over a project
    sheet's table, which is how a code query ends up answered by a norm that
    does not contain the code.
    """
    if not query_identifiers or not text:
        return 0
    haystack = re.sub(r"\s+", " ", str(text)).casefold()
    return sum(1 for i in query_identifiers if _contains_whole(haystack, i.casefold()))


# Знак, который может оказаться продолжением шифра. Пробел границей не годится:
# «(А-01.2.14)», «У-02.8.1,» и «П1-TRF-01-01.» — это те же шифры, а вот
# «ZX-1000» уже другой, и «С.П2.15.1145» тоже.
_WORD_CHAR = re.compile(r"\w")
_SEPARATOR = ".-/"


def _contains_whole(haystack: str, needle: str) -> bool:
    """Есть ли шифр в тексте целиком, а не как начало другого шифра.

    Сравнение было подстрочным, и `ZX-100` засчитывался внутри `ZX-1000`. На
    этом корпусе коды помещений идут подряд и отличаются одной цифрой, а
    совпадение по шифру — первый тай-брейк ранжирования: ложное совпадение
    поднимает чужой лист на первое место.
    """
    if not needle:
        return False

    def continues(text: str, index: int, step: int) -> bool:
        """Продолжается ли шифр в эту сторону от границы."""
        if not 0 <= index < len(text):
            return False
        char = text[index]
        if _WORD_CHAR.match(char):
            return True
        if char not in _SEPARATOR:
            return False
        # Разделитель продолжает шифр, только если за ним снова знак шифра:
        # «А-01.2.14.» в конце фразы — это точка, а «А-01.2.14.1» — шифр длиннее.
        nxt = index + step
        return 0 <= nxt < len(text) and bool(_WORD_CHAR.match(text[nxt]))

    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        if not continues(haystack, start - 1, -1) and not continues(haystack, end, 1):
            return True
        start = haystack.find(needle, start + 1)
    return False
