# -*- coding: utf-8 -*-
"""Report duplicate / multi-version files in the index.

Two kinds of redundancy are detected (read-only, safe during backfill):

  1. EXACT duplicates  -> identical SHA256 indexed under >1 source_path.
     Pure waste: the same bytes occupy vectors twice. Safe to dedupe.

  2. VERSION families  -> same logical document indexed under different
     revisions (filename differs only by revision tokens like -06, _partN,
     (1), .NN). Useful for "before/after" and versioning tests; NOT waste.

Output: data/duplicates_report.md  (under data/, which is gitignored).
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "metadata.db"
OUT = ROOT / "data" / "duplicates_report.md"

_REV = re.compile(r"\s*\(\d+\)|_part\d+|-\d{2}$|\.\d{2}$", re.IGNORECASE)


def family_key(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0].lower()
    prev = None
    while prev != name:  # strip stacked revision tokens
        prev = name
        name = _REV.sub("", name).strip()
    return re.sub(r"\s+", " ", name)


def main() -> int:
    if not DB.exists():
        print(f"DB not found: {DB}")
        return 2
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True, timeout=10)
    rows = con.execute(
        "SELECT source_path, sha256, chunk_count, dataset FROM files"
    ).fetchall()
    con.close()

    by_sha: dict[str, list] = defaultdict(list)
    by_family: dict[str, list] = defaultdict(list)
    for path, sha, cc, ds in rows:
        by_sha[sha].append((path, cc, ds))
        by_family[family_key(path)].append((path, sha, cc, ds))

    exact = {s: v for s, v in by_sha.items() if len(v) > 1}
    families = {f: v for f, v in by_family.items()
                if len({p[1] for p in v}) > 1 or len(v) > 1}

    lines: list[str] = []
    lines.append("# Duplicate & version report")
    lines.append("")
    lines.append(f"Total indexed files: **{len(rows)}**")
    lines.append(f"Exact-duplicate SHA groups (same bytes, >1 path): **{len(exact)}**")
    wasted = sum(len(v) - 1 for v in exact.values())
    lines.append(f"Redundant copies that could be removed: **{wasted}**")
    lines.append("")

    lines.append("## 1. Exact duplicates (identical SHA256 under several paths)")
    lines.append("")
    lines.append("Pure redundancy — same content vectorized more than once. Safe to dedupe (keep one path).")
    lines.append("")
    for sha, items in sorted(exact.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"### SHA `{sha[:16]}` × {len(items)}")
        for path, cc, ds in sorted(items):
            lines.append(f"- [{ds}] {cc:>6} chunks — `{path}`")
        lines.append("")

    lines.append("## 2. Version families (same document, different revisions)")
    lines.append("")
    lines.append("Kept on purpose for before/after & versioning tests. NOT waste. "
                 "Different SHA within a family = a genuine revision; identical SHA = exact dup (also listed above).")
    lines.append("")
    multi = {f: v for f, v in families.items() if len(v) > 1}
    for fam, items in sorted(multi.items()):
        shas = {p[1] for p in items}
        tag = "revisions differ" if len(shas) > 1 else "identical bytes"
        lines.append(f"### `{fam}` — {len(items)} files ({tag})")
        for path, sha, cc, ds in sorted(items):
            lines.append(f"- [{ds}] {cc:>6} chunks  sha=`{sha[:12]}` — `{os.path.basename(path)}`")
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}  ({len(exact)} exact-dup groups, {wasted} redundant copies, "
          f"{len(multi)} version families)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
