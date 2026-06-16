from __future__ import annotations

import csv
from io import StringIO

from .extractor import ExtractedValue


def rows_to_csv(rows: list[ExtractedValue]) -> str:
    buf = StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(["record", "label", "value", "unit", "confidence", "evidence"])
    for row in rows:
        writer.writerow([row.record, row.label, row.value, row.unit, row.confidence, row.evidence])
    return buf.getvalue()


def build_markdown_report(
    rows: list[ExtractedValue],
    title: str,
    source_note: str,
    high_threshold: float = 300.0,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Source: {source_note}",
        "",
        "> Values are extracted heuristically from indexed text. Verify critical rows against source documents.",
        "",
    ]

    zero_rows = [row for row in rows if row.value == 0]
    high_rows = [row for row in rows if row.value >= high_threshold]

    lines.append("## 0 Па")
    if zero_rows:
        for row in zero_rows:
            lines.append(f"- {row.record}: {row.value:g} {row.unit} ({row.label})")
    else:
        lines.append("- No rows")

    lines.extend(["", f"## >= {high_threshold:g} Па"])
    if high_rows:
        for row in high_rows:
            lines.append(f"- {row.record}: {row.value:g} {row.unit} ({row.label})")
    else:
        lines.append("- No rows")

    lines.extend(["", "## Extracted Rows", "", "| Record | Label | Value | Evidence |", "|---|---|---:|---|"])
    for row in rows:
        value = f"{row.value:g} {row.unit}".strip()
        evidence = row.evidence.replace("|", "\\|")
        lines.append(f"| {row.record} | {row.label} | {value} | {evidence} |")

    return "\n".join(lines) + "\n"
