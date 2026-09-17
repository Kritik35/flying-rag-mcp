# -*- coding: utf-8 -*-
"""Persistent per-file Parquet store of normalized table rows.

Populated at index time (and by build_table_parquet.py for the existing corpus)
so sum_table_values reads pre-parsed structured rows instead of re-parsing the
source on every query. One Parquet per source file, fixed columnar schema, so
aggregation is a fast deterministic Python sum over typed columns.

Layout: data/table_parquet/<sha16(source_path)>.parquet  (under data/, gitignored)
Each parquet also carries source_path + row_index + raw_row(JSON) for traceability.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent

# Версия разбора таблиц. Кэш, записанный другой версией, считается
# отсутствующим и переразбирается при первом же обращении к файлу.
#
# Без этого правка разбора не доходит до данных: `sum_table_values` читает
# parquet, если он есть, и на живом корпусе 2192 таких файла. Лист
# АТ-РД-ОВ3-С-00-10.02-02.pdf отдавал 87 строк штампа, разобранных прежним
# кодом, — исправленный разбор к нему просто не вызывался.
#
# Поднимать при любом изменении _rows_from_grid / _map_columns / _extract_rows.
PARSER_VERSION = 6

STR_FIELDS = ["pos", "name", "unit", "section", "code", "mark"]
NUM_FIELDS = ["qty", "amount", "amount_mat", "amount_work", "price",
              "qty_per_unit", "work_done", "weight_total"]


def _cfg() -> dict:
    try:
        import yaml
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("tables", {}) or {}
    except Exception:
        return {}


def is_enabled() -> bool:
    return bool(_cfg().get("parquet_enabled", True))


def _store_dir() -> Path:
    return ROOT / _cfg().get("parquet_dir", "data/table_parquet")


def parquet_path(source_path: str) -> Path:
    h = hashlib.sha1(str(source_path).encode("utf-8")).hexdigest()[:16]
    return _store_dir() / f"{h}.parquet"


def _read_version(source_path: str) -> Optional[int]:
    """Версия разбора, которой записан кэш; None — если её там нет."""
    p = parquet_path(source_path)
    if not p.exists():
        return None
    try:
        import pyarrow.parquet as pq

        meta = pq.read_schema(p).metadata or {}
        raw = meta.get(b"parser_version")
        return int(raw) if raw is not None else None
    except Exception:
        return None


def parquet_version(source_path: str) -> Optional[int]:
    return _read_version(source_path)


def has_parquet(source_path: str) -> bool:
    """Есть ли ПРИГОДНЫЙ кэш: существующий и разобранный текущей версией."""
    if not parquet_path(source_path).exists():
        return False
    return _read_version(source_path) == PARSER_VERSION


def write_parquet(source_path: str, rows: Optional[list[dict[str, Any]]] = None) -> int:
    """Extract (if rows not given), normalize and persist a file's table rows.
    Returns the number of rows written (0 = no tables / skipped)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from rag_server.table_query import _extract_rows

    src = Path(source_path)
    if rows is None:
        rows = _extract_rows(src)
    if not rows:
        return 0

    cols: dict[str, list] = {"source_path": [], "row_index": [], "raw_row": []}
    for f in STR_FIELDS + NUM_FIELDS:
        cols[f] = []
    for i, r in enumerate(rows):
        cols["source_path"].append(str(source_path))
        cols["row_index"].append(i)
        cols["raw_row"].append(json.dumps(r.get("raw_row", {}), ensure_ascii=False, default=str))
        for f in STR_FIELDS:
            v = r.get(f)
            cols[f].append(str(v) if v not in (None, "") else None)
        for f in NUM_FIELDS:
            v = r.get(f)
            cols[f].append(float(v) if isinstance(v, (int, float)) else None)

    schema = pa.schema(
        [("source_path", pa.string()), ("row_index", pa.int32()), ("raw_row", pa.string())]
        + [(f, pa.string()) for f in STR_FIELDS]
        + [(f, pa.float64()) for f in NUM_FIELDS]
    )
    table = pa.table(cols, schema=schema)
    table = table.replace_schema_metadata({
        **(table.schema.metadata or {}),
        b"parser_version": str(PARSER_VERSION).encode("ascii"),
    })
    out = parquet_path(source_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    return len(rows)


def read_parquet_rows(source_path: str) -> list[dict[str, Any]]:
    """Read a file's stored rows back as dicts (raw_row parsed to dict),
    shaped like table_query._extract_rows output. [] if no parquet."""
    p = parquet_path(source_path)
    if not p.exists() or _read_version(source_path) != PARSER_VERSION:
        return []
    import pyarrow.parquet as pq

    tbl = pq.read_table(p)
    data = tbl.to_pylist()
    out: list[dict[str, Any]] = []
    for rec in data:
        row: dict[str, Any] = {}
        for f in STR_FIELDS:
            if rec.get(f) not in (None, ""):
                row[f] = rec[f]
        for f in NUM_FIELDS:
            if rec.get(f) is not None:
                row[f] = rec[f]
        raw = rec.get("raw_row")
        if raw:
            try:
                row["raw_row"] = json.loads(raw)
            except Exception:
                row["raw_row"] = {}
        out.append(row)
    return out


def maybe_write_for_indexer(source_path: str) -> int:
    """Indexer hook: persist table rows for a freshly indexed file.
    No-op (0) when disabled or the file has no tables. Never raises."""
    if not is_enabled():
        return 0
    try:
        if Path(source_path).suffix.lower() not in (
            ".xlsx", ".xlsm", ".xls", ".pdf", ".docx", ".csv", ".tsv"
        ):
            return 0
        return write_parquet(source_path)
    except Exception:
        return 0
