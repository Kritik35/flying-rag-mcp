# -*- coding: utf-8 -*-
"""Что из объявленных папок не попало в индекс.

Отвечает одной командой на вопрос, который до сих пор требовал расследования.
Пробел я находил, идя от провалившихся заданий `reindex_path`, — но так видно
только то, по чему задание запускали и оно упало. Папка, по которой задание не
запускали вовсе, следа не оставляет ни в индексе, ни в журнале.

Сверять есть с чем: `config.yaml` объявляет `watched_folders` — корни, по
которым работает наблюдатель. Это заявление проекта о том, что должно быть
покрыто, и сверка его с таблицей `files` и есть ответ.

Только чтение: ничего не индексирует, Lemonade не трогает, базу открывает
в режиме `mode=ro`.

    python scripts\\corpus_gap.py                # сводка по корням
    python scripts\\corpus_gap.py --list         # плюс имена непокрытых файлов
    python scripts\\corpus_gap.py --out gap.txt  # пути для последующей доиндексации
    python scripts\\corpus_gap.py --ext .pdf .docx
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Форматы, которые корпус действительно держит как документы. В индексе сейчас
# pdf/docx/xlsx/txt плюс единичные py, json и dwg — последние попали случайно,
# и считать их пробелом было бы шумом.
DEFAULT_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm",
                      ".txt", ".rtf", ".csv"}


def is_indexable(path: Path, extensions: set[str] | None = None) -> bool:
    """Документ ли это, который имеет смысл искать в индексе."""
    if path.name.startswith("~$"):
        # Временный файл открытого Office: живёт, пока документ открыт.
        return False
    return path.suffix.lower() in (extensions or DEFAULT_EXTENSIONS)


def _norm(path: str | Path) -> str:
    """Путь в одной форме с обеих сторон сравнения.

    В базе путь мог лечь с другим регистром или через прямые слэши, и наивное
    сравнение строк объявляло бы такие файлы непокрытыми.
    """
    return os.path.normcase(os.path.normpath(str(path)))


def indexed_paths(db_path: Path) -> set[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {_norm(r[0]) for r in con.execute("SELECT source_path FROM files")
                if r[0]}
    finally:
        con.close()


def find_gap(roots: list[str], indexed: set[str],
             extensions: set[str] | None = None) -> list[dict]:
    """По каждому объявленному корню: сколько документов и каких нет в индексе."""
    known = {_norm(p) for p in indexed}
    report: list[dict] = []
    for root in roots:
        path = Path(root)
        if not path.is_dir():
            # Съёмный диск не подключён — это не пробел, а неизвестность.
            # Считать его недостачей значило бы каждый раз «терять» нормативы.
            report.append({"root": str(root), "unreachable": True,
                           "on_disk": 0, "missing": []})
            continue
        files = [f for f in path.rglob("*")
                 if f.is_file() and is_indexable(f, extensions)]
        missing = [str(f) for f in files if _norm(f) not in known]
        report.append({"root": str(root), "unreachable": False,
                       "on_disk": len(files), "missing": missing})
    return report


def _declared_roots() -> list[str]:
    from config_loader import load_config
    return list((load_config() or {}).get("watched_folders", []) or [])


def _meta_db() -> Path:
    from config_loader import load_config
    cfg = load_config() or {}
    return ROOT / cfg.get("storage", {}).get("metadata_db", "data/metadata.db")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="показать имена непокрытых файлов")
    parser.add_argument("--out", metavar="ФАЙЛ",
                        help="записать пути непокрытых файлов, по одному в строке")
    parser.add_argument("--ext", nargs="*", metavar=".pdf",
                        help="какие расширения считать документами")
    args = parser.parse_args()

    roots = _declared_roots()
    if not roots:
        print("в конфигурации нет watched_folders — сверять не с чем")
        return 1

    db = _meta_db()
    if not db.exists():
        print(f"нет базы {db}")
        return 1

    extensions = {e.lower() if e.startswith(".") else f".{e.lower()}"
                  for e in args.ext} if args.ext else None
    report = find_gap(roots, indexed_paths(db), extensions)

    total_disk = sum(r["on_disk"] for r in report)
    total_missing = sum(len(r["missing"]) for r in report)
    print(f"объявлено корней: {len(report)}; документов на диске {total_disk}; "
          f"не в индексе {total_missing}\n")

    for r in report:
        name = r["root"]
        if r["unreachable"]:
            print(f"  [нет доступа]  {name}")
            continue
        share = f"{len(r['missing'])}/{r['on_disk']}"
        mark = "ок " if not r["missing"] else "ПРОБЕЛ"
        print(f"  {mark} {share:>12}  {name}")
        if args.list:
            for f in r["missing"][:20]:
                print(f"             {Path(f).name[:72]}")
            if len(r["missing"]) > 20:
                print(f"             … ещё {len(r['missing']) - 20}")

    if args.out:
        out = Path(args.out)
        out.write_text("\n".join(f for r in report for f in r["missing"]),
                       encoding="utf-8")
        print(f"\nпути записаны: {out} ({total_missing} шт.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
