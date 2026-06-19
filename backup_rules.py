# -*- coding: utf-8 -*-
"""Backup & restore engineering_rules (the backfill output).

WHY THIS EXISTS
---------------
indexer.py calls delete_file() for EVERY reprocessed file, and delete_file()
runs `DELETE FROM engineering_rules WHERE source_path = ?`. So:

  * SHA-incremental reindex (no --force) of unchanged files -> file is skipped,
    rules SURVIVE.
  * reindex with --force -> delete_file() runs for all -> rules are WIPED and
    are NOT re-created automatically (backfill is a separate offline pass).

Rules are keyed by (source_path, chunk_id). chunk_id is deterministic from the
chunk text, so for UNCHANGED file content the rules re-associate perfectly.
Therefore `restore` only refills rules for files whose current SHA matches the
backup snapshot AND that currently have zero rules (idempotent, never dupes).

Run `dump` regularly (it is read-only, safe to run while backfill is active),
and ALWAYS run `dump` right before any `--force` reindex. After the reindex,
run `restore` to put the rules back for every file whose bytes did not change.

USAGE
-----
  python backup_rules.py dump      [--db data/metadata.db] [--out data/rules_backup.db]
  python backup_rules.py restore   [--db data/metadata.db] [--in  data/rules_backup.db]
  python backup_rules.py status    [--db data/metadata.db] [--in  data/rules_backup.db]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
DEFAULT_DB = ROOT / "data" / "metadata.db"
DEFAULT_BACKUP = ROOT / "data" / "rules_backup.db"

RULE_COLS = (
    "source_path", "chunk_id", "rule_text", "subject", "parameter",
    "operator", "value", "unit", "condition", "created_at",
)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _ro(path: Path) -> sqlite3.Connection:
    """Read-only connection (safe against the live backfill writer)."""
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True, timeout=10)


def dump(db: Path, out: Path) -> int:
    if not db.exists():
        _log(f"[backup] ERROR: source DB not found: {db}")
        return 2
    src = _ro(db)
    try:
        n_rules = src.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0]
        rules = src.execute(
            f"SELECT {', '.join(RULE_COLS)} FROM engineering_rules"
        ).fetchall()
        files = src.execute(
            "SELECT source_path, sha256, chunk_count FROM files"
        ).fetchall()
    finally:
        src.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    dst = sqlite3.connect(out)
    try:
        dst.execute(
            f"CREATE TABLE engineering_rules ({', '.join(c + ' TEXT' for c in RULE_COLS)})"
        )
        dst.execute(
            "CREATE TABLE files_snapshot (source_path TEXT PRIMARY KEY, "
            "sha256 TEXT, chunk_count INTEGER)"
        )
        dst.execute(
            "CREATE TABLE backup_meta (created_at TEXT, source_db TEXT, "
            "n_rules INTEGER, n_files INTEGER)"
        )
        dst.executemany(
            f"INSERT INTO engineering_rules ({', '.join(RULE_COLS)}) "
            f"VALUES ({', '.join('?' for _ in RULE_COLS)})",
            rules,
        )
        dst.executemany(
            "INSERT OR REPLACE INTO files_snapshot VALUES (?, ?, ?)", files
        )
        dst.execute(
            "INSERT INTO backup_meta VALUES (?, ?, ?, ?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), str(db), n_rules, len(files)),
        )
        dst.execute("CREATE INDEX idx_rules_src ON engineering_rules(source_path)")
        dst.commit()
    finally:
        dst.close()

    _log(f"[backup] dumped {n_rules} rules over {len(files)} file snapshots -> {out}")
    return 0


def restore(db: Path, backup: Path) -> int:
    if not backup.exists():
        _log(f"[backup] ERROR: backup not found: {backup}")
        return 2
    if not db.exists():
        _log(f"[backup] ERROR: target DB not found: {db}")
        return 2

    bk = _ro(backup)
    try:
        snap = dict(
            (r[0], r[1]) for r in bk.execute("SELECT source_path, sha256 FROM files_snapshot")
        )
        rules_by_path: dict[str, list] = {}
        for row in bk.execute(
            f"SELECT {', '.join(RULE_COLS)} FROM engineering_rules"
        ):
            rules_by_path.setdefault(row[0], []).append(row)
    finally:
        bk.close()

    tgt = sqlite3.connect(db, timeout=30)
    restored_files = restored_rules = 0
    skipped_changed = skipped_haverules = skipped_missing = 0
    try:
        for path, bk_sha in snap.items():
            cur = tgt.execute(
                "SELECT sha256 FROM files WHERE source_path = ?", (path,)
            ).fetchone()
            if not cur:
                skipped_missing += 1
                continue
            if cur[0] != bk_sha:
                skipped_changed += 1  # content changed -> backup rules are stale
                continue
            have = tgt.execute(
                "SELECT COUNT(*) FROM engineering_rules WHERE source_path = ?", (path,)
            ).fetchone()[0]
            if have > 0:
                skipped_haverules += 1  # already present -> never duplicate
                continue
            payload = rules_by_path.get(path, [])
            if not payload:
                continue
            tgt.executemany(
                f"INSERT INTO engineering_rules ({', '.join(RULE_COLS)}) "
                f"VALUES ({', '.join('?' for _ in RULE_COLS)})",
                payload,
            )
            restored_files += 1
            restored_rules += len(payload)
        tgt.commit()
    finally:
        tgt.close()

    _log(
        f"[backup] restored {restored_rules} rules across {restored_files} files | "
        f"skip changed={skipped_changed} have-rules={skipped_haverules} "
        f"missing={skipped_missing}"
    )
    return 0


def status(db: Path, backup: Path) -> int:
    if db.exists():
        src = _ro(db)
        try:
            live = src.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0]
            live_files = src.execute(
                "SELECT COUNT(DISTINCT source_path) FROM engineering_rules"
            ).fetchone()[0]
        finally:
            src.close()
        _log(f"[backup] live DB:    {live} rules / {live_files} files")
    else:
        _log(f"[backup] live DB:    (missing {db})")

    if backup.exists():
        bk = _ro(backup)
        try:
            meta = bk.execute("SELECT * FROM backup_meta").fetchone()
            bn = bk.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0]
        finally:
            bk.close()
        _log(f"[backup] backup:     {bn} rules | meta={meta}")
    else:
        _log(f"[backup] backup:     (none at {backup})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backup/restore engineering_rules.")
    p.add_argument("mode", choices=("dump", "restore", "status"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_BACKUP)
    p.add_argument("--in", dest="infile", type=Path, default=DEFAULT_BACKUP)
    args = p.parse_args(argv)

    if args.mode == "dump":
        return dump(args.db, args.out)
    if args.mode == "restore":
        return restore(args.db, args.infile)
    return status(args.db, args.infile)


if __name__ == "__main__":
    raise SystemExit(main())
