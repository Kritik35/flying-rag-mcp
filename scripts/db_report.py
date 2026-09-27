# -*- coding: utf-8 -*-
"""Что лежит на диске под данными: размеры, даты, и что чем защищено.

Отвечает на вопрос «можно ли это удалить», не удаляя ничего. Только чтение:
ни один вызов здесь не меняет ни LanceDB, ни SQLite.

    python scripts\\db_report.py            # инвентаризация
    python scripts\\db_report.py --rows     # плюс число строк на старой версии

`--rows` открывает старейшую доступную версию LanceDB, чтобы показать, к какому
состоянию корпуса ведёт откат. Это единственная медленная часть (десятки секунд
на 1.2 млн строк), поэтому по умолчанию выключена.
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GB = 1024 ** 3

# Таблицы, по которым видно назначение копии metadata.db: файлы корпуса,
# родительские чанки, извлечённые правила и кэш разбора.
SQLITE_TABLES = ("files", "parent_chunks", "engineering_rules", "chunk_cache",
                 "raw_tables", "search_cache")


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def when(path: Path) -> str:
    return datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def human(size: int) -> str:
    if size >= GB:
        return f"{size / GB:.2f} ГБ"
    if size >= 1024 ** 2:
        return f"{size / 1024 ** 2:.0f} МБ"
    return f"{size / 1024:.0f} КБ"


def sqlite_summary(path: Path) -> dict[str, int]:
    """Сколько строк в значимых таблицах. Копия открывается только на чтение."""
    out: dict[str, int] = {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        present = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in SQLITE_TABLES:
            if table in present:
                try:
                    out[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    pass
    finally:
        con.close()
    return out


def lance_stores() -> list[Path]:
    return sorted(p for p in DATA.glob("lancedb*") if p.is_dir())


def report_lance(store: Path, with_rows: bool) -> None:
    print(f"\n  {store.name}   {human(size_of(store))}")
    tables = [p for p in store.iterdir() if p.is_dir() and p.suffix == ".lance"]
    if not tables:
        files = list(store.glob("*"))
        print(f"     не хранилище LanceDB: {len(files)} файлов")
        return

    for table in tables:
        if table.name == "__manifest":
            continue
        parts = {}
        for sub in ("data", "_versions", "_indices", "_transactions"):
            d = table / sub
            if d.is_dir():
                entries = list(d.iterdir())
                parts[sub] = (len(entries), sum(size_of(e) for e in entries))
        print(f"     таблица {table.name}")
        for sub, (count, size) in parts.items():
            print(f"        {sub:14s} {count:>5} шт  {human(size):>9}")

        if with_rows:
            _report_versions(store, table)


def _report_versions(store: Path, table: Path) -> None:
    """К какому состоянию корпуса ведёт откат на старейшую версию."""
    try:
        import lancedb
    except ImportError:
        print("        версии: lancedb не установлен")
        return
    try:
        handle = lancedb.connect(str(store)).open_table(table.stem)
        versions = handle.list_versions()
    except Exception as exc:  # хранилище может быть другого формата
        print(f"        версии: не прочитались — {exc}")
        return

    def stamp(v) -> str:
        ts = v.get("timestamp")
        if isinstance(ts, (int, float)):
            ts = datetime.datetime.fromtimestamp(ts / 1e9 if ts > 1e12 else ts)
        return str(ts)[:19]

    print(f"        версий {len(versions)}: "
          f"v{versions[0]['version']} ({stamp(versions[0])}) .. "
          f"v{versions[-1]['version']} ({stamp(versions[-1])})")
    try:
        handle.checkout(versions[0]["version"])
        oldest_rows = handle.count_rows()
        handle.checkout_latest()
        newest_rows = handle.count_rows()
        print(f"        строк: сейчас {newest_rows:,}, "
              f"на старейшей версии {oldest_rows:,}")
    except Exception as exc:
        print(f"        строк: не посчитались — {exc}")
    finally:
        try:
            handle.checkout_latest()
        except Exception:
            pass

    try:
        print(f"        живые индексы: "
              f"{', '.join(str(i) for i in handle.list_indices())}")
    except Exception:
        pass


def report_sqlite() -> None:
    dbs = sorted(DATA.glob("*.db")) + sorted(DATA.glob("*.db.bak"))
    for path in dbs:
        counts = sqlite_summary(path)
        print(f"\n  {path.name}   {human(size_of(path))}   {when(path)}")
        if not counts:
            print("     пусто или не SQLite")
            continue
        for table, n in counts.items():
            print(f"     {table:20s} {n:>10,}")


def report_empty() -> None:
    """Пустые файлы БД вне data/ — следы запусков с неверным путём."""
    stray = []
    for pattern in ("*.db", "storage/*.db"):
        for path in ROOT.glob(pattern):
            if path.stat().st_size == 0:
                stray.append(path)
    if stray:
        print("\n  пустые файлы БД (0 байт), следы запусков с неверным путём:")
        for path in sorted(stray):
            print(f"     {path.relative_to(ROOT)}   {when(path)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", action="store_true",
                        help="посчитать строки и версии в LanceDB (медленно)")
    args = parser.parse_args()

    if not DATA.is_dir():
        print(f"нет каталога {DATA}")
        return 1

    print(f"=== {DATA} — {human(size_of(DATA))} ===")

    print("\n--- хранилища LanceDB ---")
    for store in lance_stores():
        report_lance(store, args.rows)

    print("\n--- SQLite ---")
    report_sqlite()
    report_empty()

    parquet = DATA / "table_parquet"
    if parquet.is_dir():
        print(f"\n--- кэш разбора таблиц ---\n  {parquet.name}   "
              f"{human(size_of(parquet))}   {len(list(parquet.iterdir()))} файлов")

    return 0


if __name__ == "__main__":
    sys.exit(main())
