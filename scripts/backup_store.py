# -*- coding: utf-8 -*-
"""Снимок хранилища и восстановление из него.

Снимок — это пара, снятая под общей блокировкой записи, то есть между
коммитами индексатора, а не посреди:

* `metadata.db` — через online-backup SQLite (файлы, родительские фрагменты,
  правила, кэш, задания);
* каталог LanceDB целиком (векторы, полнотекстовый и ANN-индексы, манифест).

После копирования снимок проверяется: открывается, число строк и файлов
совпадает с оригиналом. Кэш таблиц (parquet) и визуальное хранилище ColPali не
копируются — первое пересобирается, второе выключено.

    python scripts\\backup_store.py backup [--dest D:\\backups] [--keep 3]
    python scripts\\backup_store.py list   [--dest D:\\backups]
    python scripts\\backup_store.py restore --from D:\\backups\\store-20261003-1530 --yes

Восстановление требует остановленных MCP-серверов и наблюдателя: они держат
файлы хранилища открытыми. Текущее состояние не удаляется, а отодвигается в
`<имя>.pre-restore-<время>` рядом с оригиналом. Подробно — docs/BACKUP_RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PREFIX = "store-"
MANIFEST = "backup.json"


def _paths() -> tuple[Path, Path]:
    from config_loader import load_config, resolve

    storage = (load_config() or {}).get("storage") or {}
    return (resolve(storage.get("lancedb_path", "data/lancedb")),
            resolve(storage.get("metadata_db", "data/metadata.db")))


def _default_dest() -> Path:
    from config_loader import data_dir

    return data_dir() / "backups"


def _measure(lance: Path, meta: Path) -> dict:
    import lancedb

    db = lancedb.connect(str(lance))
    names = list(db.list_tables().tables) if hasattr(db, "list_tables") else db.table_names()
    tables = {n: db.open_table(n).count_rows() for n in names}
    with closing(sqlite3.connect(f"file:{meta.as_posix()}?mode=ro", uri=True)) as con:
        files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        rules = con.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0]
        check = con.execute("PRAGMA quick_check").fetchone()[0]
    return {"tables": tables, "files": files, "rules": rules, "sqlite_check": check}


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def backup(dest: Path, keep: int, lock_wait: float) -> int:
    from storage.write_lock import WriterBusy, writer_lock

    lance, meta = _paths()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = dest / f"{PREFIX}{stamp}"
    target.mkdir(parents=True)
    try:
        with writer_lock(lance, owner="backup_store", wait=lock_wait):
            source = _measure(lance, meta)
            with closing(sqlite3.connect(meta)) as src, \
                    closing(sqlite3.connect(target / meta.name)) as dst:
                src.backup(dst)
            shutil.copytree(lance, target / lance.name)
    except WriterBusy as busy:
        shutil.rmtree(target, ignore_errors=True)
        print(f"хранилище занято — снимок не сделан: {busy}")
        return 2

    copy = _measure(target / lance.name, target / meta.name)
    ok = copy == source and copy["sqlite_check"] == "ok"
    record = {"created": stamp, "source": {"lancedb": str(lance), "metadata": str(meta)},
              "counts": source, "verified": ok, "bytes": _size(target)}
    (target / MANIFEST).write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    if not ok:
        print(f"СБОЙ проверки снимка: оригинал {source}, копия {copy}")
        return 3
    print(f"снимок {target} — {record['bytes'] / 1024 ** 3:.2f} ГБ, "
          f"строк {sum(source['tables'].values()):,}, файлов {source['files']:,}, "
          f"правил {source['rules']:,}; проверен")
    _rotate(dest, keep)
    return 0


def _snapshots(dest: Path) -> list[Path]:
    if not dest.exists():
        return []
    return sorted(p for p in dest.iterdir()
                  if p.is_dir() and p.name.startswith(PREFIX) and (p / MANIFEST).exists())


def _rotate(dest: Path, keep: int) -> None:
    if keep <= 0:
        return
    for old in _snapshots(dest)[:-keep]:
        shutil.rmtree(old)
        print(f"удалён старый снимок {old.name} (хранится {keep})")


def list_snapshots(dest: Path) -> int:
    snaps = _snapshots(dest)
    if not snaps:
        print(f"в {dest} снимков нет")
        return 0
    for snap in snaps:
        rec = json.loads((snap / MANIFEST).read_text(encoding="utf-8"))
        rows = sum(rec["counts"]["tables"].values())
        print(f"{snap.name}  {rec['bytes'] / 1024 ** 3:6.2f} ГБ  строк {rows:,}  "
              f"файлов {rec['counts']['files']:,}  проверен: {rec['verified']}")
    return 0


def _servers_running() -> list[str]:
    import psutil

    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        cmd = " ".join(proc.info.get("cmdline") or [])
        if "main.py" in cmd and "python" in cmd.lower():
            found.append(f"{proc.info['pid']}: {cmd[-80:]}")
    return found


def restore(source: Path, yes: bool, lock_wait: float) -> int:
    from storage.write_lock import WriterBusy, writer_lock

    lance, meta = _paths()
    manifest = source / MANIFEST
    if not manifest.exists():
        print(f"{source} — не снимок (нет {MANIFEST})")
        return 1
    rec = json.loads(manifest.read_text(encoding="utf-8"))
    if not rec.get("verified"):
        print("снимок не прошёл проверку при создании — восстанавливать не буду")
        return 1
    running = _servers_running()
    if running:
        print("запущены серверы, которые держат хранилище открытым — остановите их:")
        for r in running:
            print("   ", r)
        return 2
    if not yes:
        print(f"будет восстановлен снимок {rec['created']} "
              f"(строк {sum(rec['counts']['tables'].values()):,}); текущее состояние "
              f"отодвигается в сторону. Подтвердите флагом --yes.")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        with writer_lock(lance, owner="backup_store restore", wait=lock_wait):
            for current in (lance, meta):
                if current.exists():
                    current.rename(current.with_name(f"{current.name}.pre-restore-{stamp}"))
            for leftover in (meta.with_name(meta.name + "-wal"), meta.with_name(meta.name + "-shm")):
                if leftover.exists():
                    leftover.rename(leftover.with_name(f"{leftover.name}.pre-restore-{stamp}"))
            shutil.copytree(source / lance.name, lance)
            shutil.copy2(source / meta.name, meta)
    except WriterBusy as busy:
        print(f"хранилище занято — ничего не изменено: {busy}")
        return 2

    now = _measure(lance, meta)
    ok = now == rec["counts"]
    print(("восстановлено и проверено: " if ok else "СБОЙ проверки после восстановления: ")
          + json.dumps(now, ensure_ascii=False))
    print(f"прежнее состояние: *.pre-restore-{stamp} рядом с хранилищем")
    return 0 if ok else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--dest", type=Path)
    b.add_argument("--keep", type=int, default=3, help="сколько снимков хранить (0 — все)")
    b.add_argument("--lock-wait", type=float, default=600.0)
    ls = sub.add_parser("list")
    ls.add_argument("--dest", type=Path)
    r = sub.add_parser("restore")
    r.add_argument("--from", dest="source", type=Path, required=True)
    r.add_argument("--yes", action="store_true")
    r.add_argument("--lock-wait", type=float, default=600.0)
    args = parser.parse_args(argv)

    if args.cmd == "backup":
        return backup(args.dest or _default_dest(), args.keep, args.lock_wait)
    if args.cmd == "list":
        return list_snapshots(args.dest or _default_dest())
    return restore(args.source, args.yes, args.lock_wait)


if __name__ == "__main__":
    raise SystemExit(main())
