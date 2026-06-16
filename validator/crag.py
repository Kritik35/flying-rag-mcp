from __future__ import annotations
import json
import re

_RU_MARKERS = re.compile(
    r'(СП|ГОСТ|ФЗ|СНиП|СанПиН|п\.|пп\.|разд\.|таб[лл]|рис\.)', re.IGNORECASE
)
_EN_MARKERS = re.compile(
    r'(section|clause|table|figure|GOST|SP\s*\d|standard|requirement)', re.IGNORECASE
)
_STRUCTURE = re.compile(r'(\|.*\||\d+\.\d+|\#{1,3}\s)', re.MULTILINE)


def validate_crag(text: str) -> tuple[bool, str]:
    """
    Проверить качество текста перед индексацией.
    Возвращает (is_valid, reason).
    """
    if len(text) < 200:
        return False, "too_short"
    if not (_RU_MARKERS.search(text) or _EN_MARKERS.search(text)):
        return False, "no_markers"
    if not _STRUCTURE.search(text):
        return False, "no_structure"
    return True, "pass"


def wrap_meta_header(source_name: str, is_valid: bool, doc_type: str = "document") -> str:
    """RAG-META заголовок для вставки в начало текста."""
    meta = json.dumps(
        {"source": source_name, "crag_valid": is_valid, "type": doc_type},
        ensure_ascii=False,
    )
    status = "✅ OK" if is_valid else "⚠️ NEEDS REVIEW"
    return f"<!-- RAG-META: {meta} -->\n⚠️ SAFE-RAG: {status}\n"


if __name__ == "__main__":
    good_text = """
    # СП 50.13330.2012 Тепловая защита зданий
    ## 5.1 Общие требования
    5.1.1 Теплозащита здания должна обеспечивать:
    | Показатель | Значение |
    |------------|----------|
    | R0, м²·°С/Вт | не менее 3.5 |
    5.1.2 Класс энергетической эффективности.
    """
    ok, reason = validate_crag(good_text)
    assert ok == True, f"Expected True: {reason}"
    print(f"OK valid: {reason}")
    ok, reason = validate_crag("короткий")
    assert ok == False and reason == "too_short"
    print(f"OK short: {reason}")
    ok, reason = validate_crag("A" * 300)
    assert ok == False
    print(f"OK no-markers: {reason}")
    header = wrap_meta_header("SP_50.pdf", True)
    assert "RAG-META" in header and "crag_valid" in header
    print(f"OK header: {header.splitlines()[0]}")
    print("ALL TESTS PASSED")
