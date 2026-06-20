# -*- coding: utf-8 -*-
"""Backfill the table Parquet store for ALREADY-indexed files.

Populates structured table rows for every table-bearing file in metadata.db
WITHOUT re-vectorizing anything (read-only on the DB; writes only Parquet under
data/table_parquet/). Run once so sum_table_values works "out of the box" on the
existing corpus; new files get Parquet automatically at index time.

  python build_table_parquet.py                 # all table files, skip existing
  python build_table_parquet.py --force         # rewrite even if parquet exists
  python build_table_parquet.py --like SPEC-01     # only matching source paths
  python build_table_parquet.py --ext xlsx pdf   # restrict extensions
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

DEFAULT_EXT = ("xlsx", "xlsm", "xls", "csv", "tsv", "docx", "pdf")


def _meta_db() -> Path:
    import yaml
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return ROOT / cfg["storage"]["metadata_db"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rewrite existing parquet")
    ap.add_argument("--like", type=str, default=None, help="only source_path containing this substring")
    ap.add_argument("--ext", nargs="*", default=list(DEFAULT_EXT), help="extensions to include")
    ap.add_argument("--max-mb", type=float, default=0.0,
                    help="skip files larger than this many MB (0 = no limit; pdfplumber stalls on giants)")
    args = ap.parse_args(argv)

    from rag_server import table_parquet as tp

    db = _meta_db()
    if not db.exists():
        print(f"metadata.db not found: {db}", file=sys.stderr)
        return 2
    exts = tuple("." + e.lower().lstrip(".") for e in args.ext)

    con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True, timeout=10)
    if args.like:
        rows = con.execute("SELECT source_path FROM files WHERE source_path LIKE ?",
                           (f"%{args.like}%",)).fetchall()
    else:
        rows = con.execute("SELECT source_path FROM files").fetchall()
    con.close()

    targets = [r[0] for r in rows if str(r[0]).lower().endswith(exts)]
    print(f"[parquet-backfill] {len(targets)} table files to consider", file=sys.stderr)

    done = skipped = empty = errors = 0
    total_rows = 0
    t0 = time.time()
    for i, src in enumerate(targets, 1):
        if not args.force and tp.has_parquet(src):
            skipped += 1
            continue
        sp = Path(src)
        if not sp.exists():
            errors += 1
            continue
        if args.max_mb and sp.stat().st_size / (1024 * 1024) > args.max_mb:
            skipped += 1
            continue
        try:
            n = tp.write_parquet(src)
        except Exception as e:
            print(f"[parquet-backfill] ERR {os.path.basename(src)[:50]}: {e}", file=sys.stderr)
            errors += 1
            continue
        if n:
            done += 1
            total_rows += n
            print(f"[parquet-backfill] [{i}/{len(targets)}] {n:>6} rows  {os.path.basename(src)[:60]}",
                  file=sys.stderr)
        else:
            empty += 1

    dt = int(time.time() - t0)
    print(f"[parquet-backfill] DONE written={done} ({total_rows} rows) skipped={skipped} "
          f"empty={empty} errors={errors} time={dt}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
