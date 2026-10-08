# -*- coding: utf-8 -*-
"""Сжатие хранилища и удаление старых версий LanceDB — с проверками до и после.

Без `--apply` ничего не меняет: показывает состояние и что будет сделано.

    python scripts\\db_maintenance.py            # сухой прогон
    python scripts\\db_maintenance.py --apply    # выполнить

Что делает `--apply`: `optimize()` — склейка фрагментов (уходят строки,
помеченные удалёнными при дедупе), дообучение индексов на строках, которые в
ANN ещё не попали, и удаление всех версий, кроме текущей.

Необратимо в одном: исчезает возможность откатиться на прежние версии
таблицы. Всё остальное — строки, индексы, текущее содержимое — остаётся.

Три условия, без которых скрипт отказывается работать:

1. Никто не пишет в хранилище в этот момент. Сжатие идёт под общей
   блокировкой записи (storage/write_lock.py) — той же, под которой
   индексатор делает свой короткий коммит, — так что оно встаёт между
   коммитами, а не посреди. Плюс `delete_unverified=False`: файлы моложе семи
   дней, на которые не ссылается ни одна версия, не трогаются. Места это
   почти не стоит, а незакоммиченную запись не сотрёт.
2. После операции строк ровно столько же, сколько до. Сжатие не должно
   менять содержимое — если число разошлось, это сообщается как сбой.
3. Индексы на месте: вектор и полнотекстовый.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WRITER_MARKERS = ("indexer.py", "run_sequential_indexer", "reindex_all",
                  "backfill_rules", "build_table_parquet")
GB = 1024 ** 3


def running_writers() -> list[str]:
    """Процессы, которые пишут в хранилище прямо сейчас."""
    import psutil

    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.Error, TypeError):
            continue
        if any(m in cmd for m in WRITER_MARKERS):
            found.append(f"{proc.info['pid']}: {cmd[-90:]}")
    return found


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def snapshot(table, table_dir: Path) -> dict:
    snap = {
        "version": table.version,
        "versions": len(table.list_versions()),
        "rows": table.count_rows(),
        "bytes": dir_size(table_dir),
        "index_dirs": sum(1 for _ in (table_dir / "_indices").iterdir())
        if (table_dir / "_indices").is_dir() else 0,
        "indices": {},
    }
    for idx in table.list_indices():
        try:
            stats = table.index_stats(idx.name)
            snap["indices"][idx.name] = {
                "indexed": getattr(stats, "num_indexed_rows", None),
                "unindexed": getattr(stats, "num_unindexed_rows", None),
            }
        except Exception as exc:
            snap["indices"][idx.name] = {"error": str(exc)}
    return snap


def show(title: str, snap: dict) -> None:
    print(f"\n{title}")
    print(f"   версия {snap['version']} (всего версий {snap['versions']}), "
          f"строк {snap['rows']:,}")
    print(f"   на диске {snap['bytes'] / GB:.2f} ГБ, каталогов индекса {snap['index_dirs']}")
    for name, st in snap["indices"].items():
        if "error" in st:
            print(f"   индекс {name}: {st['error']}")
        else:
            print(f"   индекс {name}: в индексе {st['indexed']:,}, вне индекса {st['unindexed']:,}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="выполнить, а не показать")
    parser.add_argument("--lock-wait", type=float, default=300.0,
                        help="сколько секунд ждать блокировку записи (по умолчанию 300)")
    args = parser.parse_args()

    from config_loader import load_config
    import lancedb

    cfg = load_config() or {}
    from config_loader import resolve
    store = resolve(cfg.get("storage", {}).get("lancedb_path", "data/lancedb"))
    db = lancedb.connect(str(store))
    names = list(db.list_tables().tables) if hasattr(db, "list_tables") else db.table_names()
    table_name = next((n for n in names if n.startswith("documents_")), None)
    if table_name is None:
        print(f"в {store} нет таблицы documents_*")
        return 1
    table = db.open_table(table_name)
    table_dir = store / f"{table_name}.lance"

    # Индексатор пишет только под общей блокировкой и только в момент
    # коммита, поэтому запущенный процесс сам по себе не помеха: optimize
    # берёт ту же блокировку и встаёт в очередь между коммитами.
    writers = running_writers()
    if writers:
        print("запущены процессы, которые пишут в хранилище (коммиты будут ждать):")
        for w in writers:
            print("   ", w)

    before = snapshot(table, table_dir)
    show("ДО", before)

    if not args.apply:
        print("\nсухой прогон: будет выполнено optimize(cleanup_older_than=0, "
              "delete_unverified=False) и удалены папки индексов, на которые не "
              "ссылается ни одна версия. Для выполнения добавьте --apply.")
        return 0

    from storage.write_lock import WriterBusy, writer_lock
    try:
        with writer_lock(store, owner="db_maintenance", wait=args.lock_wait):
            t0 = time.time()
            table.optimize(cleanup_older_than=dt.timedelta(0), delete_unverified=False)
            # optimize deletes the files of pruned versions (66 GB on
            # 2026-10-08) but leaves their index directories, empty; they go
            # here once they are an hour old.
            from storage.vector_store import remove_orphan_indices
            orphans = remove_orphan_indices(table_dir)
            print(f"удалено неиспользуемых папок индексов: {orphans['removed']} "
                  f"({orphans['bytes'] / GB:.2f} ГБ)")
            took = time.time() - t0
    except WriterBusy as busy:
        print(f"хранилище занято другим писателем — отказываюсь: {busy}")
        return 2

    table = db.open_table(table_name)
    after = snapshot(table, table_dir)
    show(f"ПОСЛЕ ({took:.0f} с)", after)

    freed = (before["bytes"] - after["bytes"]) / GB
    print(f"\nосвобождено {freed:.2f} ГБ; версий {before['versions']} → {after['versions']}")

    ok = after["rows"] == before["rows"]
    print("строк столько же, сколько было" if ok
          else f"СБОЙ: строк было {before['rows']:,}, стало {after['rows']:,}")
    missing = set(before["indices"]) - set(after["indices"])
    if missing:
        print(f"СБОЙ: пропали индексы {sorted(missing)}")
        ok = False

    from config_loader import data_dir
    log = data_dir() / "db_maintenance_log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"),
                            "seconds": round(took), "before": before,
                            "after": after, "ok": ok}, ensure_ascii=False) + "\n")
    print(f"запись добавлена в {log}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
