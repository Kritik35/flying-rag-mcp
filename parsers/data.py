from __future__ import annotations
import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ParsedDocument:
    source_path: str
    file_name: str
    format: str
    text: str
    created_at: str
    modified_at: str
    extra: dict = field(default_factory=dict)


def _timestamps(path: Path) -> tuple[str, str]:
    stat = path.stat()
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return fmt(stat.st_ctime), fmt(stat.st_mtime)


def _parse_json(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    data = json.loads(raw)
    if isinstance(data, list):
        lines = [f"[{i}] {json.dumps(item, ensure_ascii=False)}" for i, item in enumerate(data)]
        text = "\n".join(lines)
        extra = {"type": "list", "keys": list(data[0].keys()) if data and isinstance(data[0], dict) else []}
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        extra = {"type": "dict", "keys": list(data.keys()) if isinstance(data, dict) else []}
    return text, extra


def _parse_csv(path: Path) -> tuple[str, dict]:
    for enc in ("utf-8", "cp1251", "utf-8-sig"):
        try:
            text_raw = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text_raw = path.read_text(encoding="utf-8", errors="replace")

    reader = csv.DictReader(text_raw.splitlines())
    columns = reader.fieldnames or []
    lines = [f"Колонки: {', '.join(columns)}"]
    rows = 0
    for i, row in enumerate(reader):
        lines.append(f"[{i}] " + " | ".join(str(v) for v in row.values()))
        rows += 1
    return "\n".join(lines), {"rows": rows, "columns": list(columns)}


def parse(path: Path) -> ParsedDocument:
    try:
        created_at, modified_at = _timestamps(path)
    except Exception as e:
        return ParsedDocument(
            source_path=str(path), file_name=path.name,
            format=path.suffix.lstrip("."),
            text="", created_at="", modified_at="", extra={"error": str(e)},
        )
    fmt = path.suffix.lower().lstrip(".")
    try:
        if fmt == "json":
            text, extra = _parse_json(path)
        elif fmt == "csv":
            text, extra = _parse_csv(path)
        else:
            text, extra = "", {"error": f"Unsupported: {fmt}"}
    except Exception as e:
        text, extra = "", {"error": str(e)}
    return ParsedDocument(
        source_path=str(path), file_name=path.name, format=fmt,
        text=text, created_at=created_at, modified_at=modified_at, extra=extra,
    )
