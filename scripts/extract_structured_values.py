from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from structured_values.extractor import extract_labeled_values
from structured_values.report import build_markdown_report, rows_to_csv


def fetch_parent_texts(db_path: Path, labels: list[str], source_like: str | None, limit: int) -> list[tuple[str, str]]:
    where = []
    params: list[str | int] = []
    label_parts = []
    for label in labels:
        label_parts.append("parent_text LIKE ?")
        params.append(f"%{label}%")
    where.append("(" + " OR ".join(label_parts) + ")")
    if source_like:
        where.append("source_path LIKE ?")
        params.append(f"%{source_like}%")
    params.append(limit)

    sql = f"""
        SELECT source_path, parent_text
        FROM parent_chunks
        WHERE {' AND '.join(where)}
        LIMIT ?
    """
    with sqlite3.connect(db_path) as conn:
        return [(str(source), str(text)) for source, text in conn.execute(sql, params).fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured label/value pairs from indexed parent chunks.")
    parser.add_argument("--db", default="data/metadata.db", help="SQLite metadata DB path")
    parser.add_argument("--label", action="append", required=True, help="Label to extract; repeat for several labels")
    parser.add_argument("--source-like", default=None, help="Optional source_path substring filter")
    parser.add_argument("--limit", type=int, default=500, help="Max parent chunks to scan")
    parser.add_argument("--out-dir", default="scratch/structured_values", help="Output directory")
    parser.add_argument("--name", default=None, help="Output file basename")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Metadata DB not found: {db_path}")

    rows = []
    for source_path, text in fetch_parent_texts(db_path, args.label, args.source_like, args.limit):
        for row in extract_labeled_values(text, labels=args.label):
            rows.append(row)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = args.name or "_".join(label.casefold().replace(" ", "_") for label in args.label)
    csv_path = out_dir / f"{base}.csv"
    md_path = out_dir / f"{base}.md"

    csv_path.write_text("\ufeff" + rows_to_csv(rows), encoding="utf-8")
    md_path.write_text(
        build_markdown_report(
            rows,
            title=f"Structured extraction: {', '.join(args.label)}",
            source_note=f"{db_path}; source_like={args.source_like or '*'}; scanned_limit={args.limit}",
        ),
        encoding="utf-8",
    )
    print(f"Extracted rows: {len(rows)}")
    print(f"CSV: {csv_path}")
    print(f"Report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
