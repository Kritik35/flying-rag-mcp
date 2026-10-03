# -*- coding: utf-8 -*-
"""Найти и убрать то, что оставила прерванная запись.

Индексатор теперь коммитит документ атомарно (векторы — одним merge-insert,
метаданные — одной транзакцией), но хранилище, записанное прежним кодом, и
любые ручные операции могли оставить рассогласование. Скрипт сверяет три
части хранилища между собой:

1. `files.status = 'reindexing'` — коммит начался и не закончился. Такой файл
   индексатор переделает сам при следующем проходе по его папке; здесь он
   только показан.
2. `parent_chunks` и строки LanceDB, у `source_path` которых нет записи в
   `files`. Если файла нет и на диске — это остатки удалённого документа
   (так выглядели «призраки» ПД_PDF): их можно убрать. Если файл на месте —
   это документ, потерявший метаданные; удалить его векторы значит убрать
   его из поиска, поэтому он только показывается: индексатор, не найдя
   записи в `files`, переделает его при следующем проходе по папке
   (`reindex_path` по этому пути — сразу).
3. Записи `files` с ненулевым `chunk_count`, у которых в LanceDB нет ни одной
   строки — документ числится проиндексированным, но не ищется.

Без `--apply` только показывает. С `--apply`: удаляет остатки документов,
которых нет на диске, помечает (3) как `reindexing`, чтобы индексатор их
переделал; всё — под общей блокировкой записи. Правила (`engineering_rules`)
не трогаются никогда.

    python scripts\\store_recovery.py
    python scripts\\store_recovery.py --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def lance_sources(table) -> dict[str, int]:
    import pyarrow.compute as pc

    col = table.search().select(["source_path"]).limit(table.count_rows() + 1).to_arrow()
    counts = pc.value_counts(col.column("source_path").combine_chunks())
    return {str(v["values"]): int(v["counts"]) for v in counts.to_pylist()}


def inspect(meta: Path, table) -> dict:
    with closing(sqlite3.connect(f"file:{meta}?mode=ro", uri=True)) as con:
        files = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT source_path, status, chunk_count FROM files")}
        parent_sources = {r[0]: r[1] for r in con.execute(
            "SELECT source_path, COUNT(*) FROM parent_chunks GROUP BY source_path")}
    in_lance = lance_sources(table)
    orphans = {p for p in list(parent_sources) + list(in_lance) if p not in files}
    gone = {p for p in orphans if not Path(p).exists()}
    return {
        "reindexing": sorted(p for p, (status, _) in files.items() if status == "reindexing"),
        "orphan_parents": {p: n for p, n in parent_sources.items() if p in gone},
        "orphan_vectors": {p: n for p, n in in_lance.items() if p in gone},
        "unrecorded": sorted(orphans - gone),
        "missing_vectors": sorted(p for p, (_, n) in files.items()
                                  if (n or 0) > 0 and p not in in_lance),
        "files": len(files),
        "lance_sources": len(in_lance),
    }


def show(report: dict) -> None:
    print(f"files: {report['files']}, источников в LanceDB: {report['lance_sources']}")
    groups = [
        ("незавершённый коммит (переделает индексатор)", report["reindexing"]),
        ("остатки удалённых документов: parent_chunks", report["orphan_parents"]),
        ("остатки удалённых документов: векторы", report["orphan_vectors"]),
        ("файл на диске, записи в files нет (переиндексировать)", report["unrecorded"]),
        ("файл без векторов", report["missing_vectors"]),
    ]
    for title, items in groups:
        rows = f", {sum(items.values())} строк" if isinstance(items, dict) else ""
        print(f"  {title}: {len(items)} источников{rows}")
        for p in list(items)[:10]:
            print(f"      {p[-100:]}")
        if len(items) > 10:
            print(f"      … ещё {len(items) - 10}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="исправить, а не показать")
    parser.add_argument("--lock-wait", type=float, default=300.0)
    args = parser.parse_args(argv)

    import lancedb
    from config_loader import load_config, resolve
    from storage.metadata_db import REINDEXING, _connect
    from storage.write_lock import WriterBusy, writer_lock

    cfg = load_config() or {}
    meta = resolve(cfg.get("storage", {}).get("metadata_db", "data/metadata.db"))
    store = resolve(cfg.get("storage", {}).get("lancedb_path", "data/lancedb"))
    db = lancedb.connect(str(store))
    names = list(db.list_tables().tables) if hasattr(db, "list_tables") else db.table_names()
    table_name = next((n for n in names if n.startswith("documents_")), None)
    if table_name is None or not meta.exists():
        print(f"нет хранилища: {store} / {meta}")
        return 1

    report = inspect(meta, db.open_table(table_name))
    show(report)
    dirty = report["orphan_parents"] or report["orphan_vectors"] or report["missing_vectors"]
    if not args.apply:
        if dirty:
            print("\nсухой прогон; для исправления добавьте --apply")
        return 0
    if not dirty:
        print("\nисправлять нечего")
        return 0

    try:
        with writer_lock(store, owner="store_recovery", wait=args.lock_wait):
            # Пересчитать под блокировкой: пока ждали, кто-то мог закоммитить.
            table = db.open_table(table_name)
            report = inspect(meta, table)
            for source in report["orphan_vectors"]:
                table.delete("source_path = '" + source.replace("'", "''") + "'")
            with _connect(meta) as conn:
                for source in report["orphan_parents"]:
                    conn.execute("DELETE FROM parent_chunks WHERE source_path = ?", (source,))
                for source in report["missing_vectors"]:
                    conn.execute("UPDATE files SET status = ? WHERE source_path = ?",
                                 (REINDEXING, source))
    except WriterBusy as busy:
        print(f"\nхранилище занято — ничего не изменено: {busy}")
        return 2

    print(f"\nудалено: векторов без файла — {sum(report['orphan_vectors'].values())} строк, "
          f"parent_chunks без файла — {sum(report['orphan_parents'].values())}; "
          f"помечено к переиндексации: {len(report['missing_vectors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
