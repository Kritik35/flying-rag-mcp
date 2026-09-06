# -*- coding: utf-8 -*-
"""Снять и сверить эталон сумм по таблицам.

Прежде чем править разбор таблиц, надо знать, что он сейчас считает верно.
Скрипт прогоняет набор запросов через `sum_table_values`, записывает итоги в
JSON и при повторном запуске сверяет с записанным.

    python scripts\\table_baseline.py --save   # снять эталон
    python scripts\\table_baseline.py          # сверить с эталоном

Эталон привязан к корпусу оператора и живёт в data/ (не в git).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASELINE = ROOT / "data" / "table_baseline.json"

# Запросы, для которых разбор таблиц сегодня даёт осмысленный результат:
# спецификации в .xlsx с одной шапкой и одной секцией.
CASES = [
    {"subject": "воздуховод", "op": "sum", "field": "qty", "source_like": "ОВ2-С-00-СО"},
    {"subject": "воздуховод", "op": "count", "source_like": "ОВ2-С-00-СО"},
    {"subject": "отвод", "op": "sum", "field": "qty", "source_like": "ОВ2-С-00-СО"},
    {"subject": "клапан", "op": "count", "source_like": "ОВ2-С-00-СО"},
    {"subject": "шумоглушитель", "op": "count", "source_like": "ОВ2-С-00-СО"},
    {"subject": "переход", "op": "sum", "field": "qty", "source_like": "ОВ2-С-00-СО"},
    # ГОСТ-ведомость в PDF: сейчас разбирается неверно, записываем как есть,
    # чтобы увидеть, что именно изменится после правки разбора.
    {"subject": "КЭВ", "op": "count", "source_like": "ОВ3-С-00-10.02"},
    {"subject": "Volcano", "op": "count", "source_like": "ОВ3-С-00-10.02"},
]


def key(case: dict) -> str:
    return f"{case['subject']}|{case['op']}|{case.get('field') or ''}|{case['source_like']}"


def run() -> dict:
    from rag_server.tools import sum_table_values

    out = {}
    for case in CASES:
        try:
            result = sum_table_values(**case)
        except Exception as e:
            out[key(case)] = {"error": f"{type(e).__name__}: {e}"}
            continue
        out[key(case)] = {
            "matched": result.get("matched"),
            "operation": result.get("operation"),
            "total": result.get("total"),
            "count": result.get("count"),
            "rows_matched": result.get("rows_matched"),
            "sources": sorted(result.get("sources") or []),
            "reason": result.get("reason"),
            # Сколько строк вернулось с содержимым, а не пустыми: пустая строка
            # со статусом VERIFIED — это уверенно поданный мусор.
            "rows_with_content": sum(
                1 for r in (result.get("rows") or [])
                if [k for k in r if k != "_source"]
            ),
            "rows_returned": len(result.get("rows") or []),
        }
    return out


def show(name: str, value: dict) -> str:
    if value.get("error"):
        return f"ошибка {value['error']}"
    if not value.get("matched"):
        return f"не найдено ({value.get('reason')})"
    head = f"{value['operation']}="
    head += f"{value['total']}" if value.get("total") is not None else f"{value['count']}"
    return (f"{head}  строк={value.get('rows_matched') or value.get('count')}"
            f"  с содержимым {value['rows_with_content']}/{value['rows_returned']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", action="store_true", help="записать текущее как эталон")
    args = ap.parse_args(argv)

    current = run()
    if args.save:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"эталон записан: {BASELINE}\n")
        for name, value in current.items():
            print(f"  {name}\n      {show(name, value)}")
        return 0

    if not BASELINE.exists():
        print(f"эталона нет: {BASELINE}\nснимите его: python scripts\\table_baseline.py --save")
        return 2

    saved = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = []
    for name, value in current.items():
        before = saved.get(name)
        if before is None:
            print(f"  НОВЫЙ   {name}\n      {show(name, value)}")
            continue
        if before == value:
            print(f"  ок      {name}: {show(name, value)}")
        else:
            changed.append(name)
            print(f"  ИЗМЕНИЛОСЬ {name}")
            print(f"      было:  {show(name, before)}")
            print(f"      стало: {show(name, value)}")
    print(f"\nизменилось: {len(changed)} из {len(current)}")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
