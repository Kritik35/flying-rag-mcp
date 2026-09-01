# -*- coding: utf-8 -*-
"""Remove duplicate copies of a document from the index.

WHY THIS EXISTS
---------------
The corpus holds the same norm twice: once converted from .docx and once from
the .pdf of the same document. They land under different paths and different
doc_ids, so every per-document guard in retrieval treats them as two documents:

  * `max_per_doc` in retrieval_quality gave a document one budget per copy, so
    the more copies a document had, the more of the answer it took;
  * `concentrate_sources(max_docs=3)` could spend all three slots on copies of
    one document and drop the norm that actually answered the question.

The ranking side is fixed in code (retrieval now keys on document identity, not
on the file path). This script deals with the other half: ~20% of the stored
chunks are a second, dirtier copy of text already in the index.

WHICH COPY IS DROPPED
---------------------
The .pdf twin, measured rather than assumed. Sampling 120 chunks from each copy
of СП 7.13130 and СП 60.13330:

    docx   ConsultantPlus page furniture in   0.0% of chunks, 6.7 newlines/1k
    pdf    ConsultantPlus page furniture in  13.7% of chunks, 19.2 newlines/1k

The PDF conversion carries page headers, footers and column breaks into the
chunk text; the DOCX conversion does not.

SAFETY
------
Only a group that is exactly one .docx plus one .pdf of the same name is
touched. Mixed groups (pdf+xlsx, pdf+txt, same-format copies) are left alone —
an .xlsx is not a duplicate of a .pdf, it is what `sum_table_values` reads.

Deletion is reversible at the cost of re-embedding: the source files stay on
disk and `reindex_path` rebuilds any of them. The plan written by `--report`
lists every path removed. Rules are unaffected in practice (all engineering
rules sit on the .docx copies), but run `backup_rules.py dump` first anyway.

USAGE
-----
  python scripts\\dedup_sources.py                 # dry run, prints the plan
  python scripts\\dedup_sources.py --report p.json # dry run + write the plan
  python scripts\\dedup_sources.py --apply         # delete
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COPY_SUFFIX_RE = re.compile(r"[\s_]*\(\d+\)$")
BATCH = 40


def document_stem(file_name: str) -> str:
    stem = os.path.splitext(file_name or "")[0]
    return COPY_SUFFIX_RE.sub("", stem.strip().casefold()).strip()


def build_plan(meta_path: Path) -> tuple[list[dict], list[dict]]:
    import sqlite3

    conn = sqlite3.connect(meta_path)
    try:
        files = conn.execute(
            "SELECT source_path, file_name, format, chunk_count FROM files"
        ).fetchall()
        rules = dict(
            conn.execute(
                "SELECT source_path, COUNT(*) FROM engineering_rules GROUP BY source_path"
            ).fetchall()
        )
    finally:
        conn.close()

    groups: defaultdict[str, list[dict]] = defaultdict(list)
    for source_path, file_name, fmt, chunk_count in files:
        groups[document_stem(file_name)].append({
            "source_path": source_path,
            "format": (fmt or "").lower(),
            "chunks": chunk_count or 0,
            "rules": rules.get(source_path, 0),
        })

    plan, skipped = [], []
    for stem, members in groups.items():
        if len(members) < 2:
            continue
        formats = {m["format"] for m in members}
        if len(members) == 2 and formats == {"docx", "pdf"}:
            keep = next(m for m in members if m["format"] == "docx")
            drop = next(m for m in members if m["format"] == "pdf")
            plan.append({"document": stem, "keep": keep, "drop": drop})
        else:
            skipped.append({"document": stem, "formats": sorted(formats),
                            "copies": len(members)})
    plan.sort(key=lambda p: -p["drop"]["chunks"])
    return plan, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually delete")
    ap.add_argument("--report", help="write the plan as JSON")
    args = ap.parse_args(argv)

    from rag_server.tools import _db_paths

    lance_path, meta_path = _db_paths()
    plan, skipped = build_plan(Path(meta_path))

    chunks = sum(p["drop"]["chunks"] for p in plan)
    lost_rules = sum(p["drop"]["rules"] for p in plan)
    only_on_dropped = sum(
        1 for p in plan if p["drop"]["rules"] and not p["keep"]["rules"]
    )
    missing = [p for p in plan if not os.path.exists(p["drop"]["source_path"])]

    print(f"duplicate .docx/.pdf pairs : {len(plan)}")
    print(f"chunks to remove           : {chunks}")
    print(f"rules on the dropped copies: {lost_rules}"
          f" (documents whose rules live only there: {only_on_dropped})")
    print(f"dropped files missing on disk (not restorable): {len(missing)}")
    print(f"groups left alone (not a clean docx+pdf pair) : {len(skipped)}")
    print("\nlargest removals:")
    for p in plan[:8]:
        print(f"   {p['drop']['chunks']:7d}  {Path(p['drop']['source_path']).name[:70]}")

    if args.report:
        Path(args.report).write_text(
            json.dumps({"plan": plan, "skipped": skipped}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nplan written to {args.report}")

    if not args.apply:
        print("\ndry run — nothing deleted. Re-run with --apply.")
        return 0

    if only_on_dropped:
        print("\nrefusing: some documents keep their rules only on the copy that "
              "would be dropped. Resolve those first.")
        return 2

    from storage.metadata_db import delete_file
    from storage.vector_store import _get_table
    from embedder.client import _DEFAULT_PROVIDER

    _db, table = _get_table(Path(lance_path), _DEFAULT_PROVIDER.get_dimension())
    paths = [p["drop"]["source_path"] for p in plan]
    started = time.time()
    for i in range(0, len(paths), BATCH):
        batch = paths[i:i + BATCH]
        quoted = ", ".join("'" + p.replace("'", "''") + "'" for p in batch)
        table.delete(f"source_path IN ({quoted})")
        for path in batch:
            delete_file(Path(meta_path), path)
        print(f"   [{min(i + BATCH, len(paths)):4d}/{len(paths)}] "
              f"{time.time() - started:.0f}s", flush=True)

    from storage.vector_store import count_chunks

    print(f"\ndone in {time.time() - started:.0f}s; chunks now: "
          f"{count_chunks(Path(lance_path))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
