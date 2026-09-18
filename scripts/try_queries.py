# -*- coding: utf-8 -*-
"""Прогнать несколько запросов и показать, куда они попали.

Отвечает на вопрос «работает ли поиск так, как я ожидаю» без MCP-клиента:
читает боевой индекс напрямую, ничего не меняет.

    python scripts\\try_queries.py            # набор проверочных пар
    python scripts\\try_queries.py "мой запрос" "и ещё один"

Пары подобраны так, что различаются только областью, названной вслух, —
по ним видно, слушается ли система указания «в проекте» / «в нормативах».
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CHECKS = [
    ("код помещения", "R.L2.15.114"),
    ("коды помещений", "1.02.11.024 1.02.11.025 1.02.11.026"),
    ("без области", "завеса воздушная водяная количество спецификация"),
    ("в проекте", "в проекте завеса воздушная водяная количество спецификация"),
    ("в проекте", "в проекте резервирование вентиляции"),
    ("в нормативах", "в нормативах резервирование вентиляции"),
    ("вопрос по норме", "в каких случаях нужно предусматривать удаление дыма из коридоров"),
]

NORM_PREFIXES = ("СП ", "ГОСТ", "СНиП", "СанПиН", "Федеральный", "Приказ", "РНП")


def kind(file_name: str) -> str:
    return "норматив" if file_name.startswith(NORM_PREFIXES) else "проект  "


def main(argv: list[str]) -> int:
    from rag_server.tools import search_documents

    checks = [("запрос", q) for q in argv] if argv else CHECKS
    for label, query in checks:
        out = search_documents(query, top_k=5, use_cache=False, debug=True)
        results = out.get("results", []) if isinstance(out, dict) else out
        debug = out.get("debug", {}) if isinstance(out, dict) else {}
        codes = [t for t in re.findall(r"\S*\d\S*", query) if len(t) > 3]
        with_code = sum(
            1 for r in results
            if any(c.casefold() in f"{r.get('text','')}{r.get('child_text','')}".casefold()
                   for c in codes)
        ) if codes else None

        scope = debug.get("applied_dataset") or "не задана"
        print(f"\n[{label}] «{query}»")
        line = f"   область: {scope}   результатов: {len(results)}"
        if with_code is not None:
            line += f"   с искомым кодом в тексте: {with_code}"
        rerank = (debug.get("rerank") or {}).get("status")
        if rerank:
            line += f"   реранк: {rerank}"
        print(line)
        for i, r in enumerate(results, 1):
            print(f"     {i}. [{kind(r.get('file_name',''))}] {r.get('file_name','')[:64]}")
    print("\nЧего ждать: код помещения -> проектные листы, содержащие сам код;")
    print("«в проекте» -> только проектные; «в нормативах» -> только нормативы.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
