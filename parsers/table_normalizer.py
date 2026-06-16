from __future__ import annotations
"""
parsers/table_normalizer.py

Real colspan/rowspan expansion + textualization for table chunks.
Replaces the prototype stub with a working implementation.

normalize_matrix(raw_json) -> list[dict]
    raw_json schema: {"raw_matrix": [[{"text":"", "colspan":1, "rowspan":1}]], ...}
    Returns list of dicts: {header_path: cell_value}

enrich_and_validate(rows) -> list[dict]
    Returns list of dicts: {"textualization": str, "abbreviations": [], "data_type": str}
"""

import re
from typing import Any


# ─── colspan/rowspan grid expansion ──────────────────────────────────────────

def _expand_grid(raw_matrix: list[list[dict]]) -> list[list[str]]:
    """
    Expand a sparse matrix with colspan/rowspan into a full dense grid.

    Each cell dict must have: {"text": str, "colspan": int, "rowspan": int}.
    Missing keys default to 1.
    """
    if not raw_matrix:
        return []

    # First pass: compute actual column count
    col_count = max(
        sum(max(1, int(cell.get("colspan", 1) or 1)) for cell in row)
        for row in raw_matrix
    )
    row_count = len(raw_matrix)

    # Allocate dense grid
    grid: list[list[str]] = [[""] * col_count for _ in range(row_count)]
    # Track cells already filled by rowspan from above
    occupied: set[tuple[int, int]] = set()

    for r_idx, row in enumerate(raw_matrix):
        c_cursor = 0
        for cell in row:
            # Skip columns occupied by rowspan from previous rows
            while (r_idx, c_cursor) in occupied:
                c_cursor += 1
            if c_cursor >= col_count:
                break

            text = str(cell.get("text") or "").strip()
            colspan = max(1, int(cell.get("colspan", 1) or 1))
            rowspan = max(1, int(cell.get("rowspan", 1) or 1))

            # Fill all cells covered by this cell
            for dr in range(rowspan):
                for dc in range(colspan):
                    rr = r_idx + dr
                    cc = c_cursor + dc
                    if rr < row_count and cc < col_count:
                        grid[rr][cc] = text
                        if dr > 0 or dc > 0:
                            occupied.add((rr, cc))

            c_cursor += colspan

    return grid


def _detect_header_depth(grid: list[list[str]]) -> int:
    """
    Detect how many top rows are header rows.
    Heuristic: a row is a header if it has more text cells than numeric cells.
    Returns depth in [1, min(3, len(grid)-1)].
    """
    if len(grid) < 2:
        return 1

    _num_re = re.compile(r"^-?\d[\d\s.,]*$")

    def _is_numeric(s: str) -> bool:
        return bool(_num_re.match(s.replace("\xa0", "").strip()))

    depth = 1
    for idx in range(min(3, len(grid) - 1)):
        row = grid[idx]
        if not any(row):
            continue
        text_count = sum(1 for c in row if c and not _is_numeric(c))
        num_count  = sum(1 for c in row if c and _is_numeric(c))
        if text_count > num_count:
            depth = idx + 1
        else:
            break
    return depth


def _build_column_paths(header_rows: list[list[str]]) -> list[str]:
    """
    Combine multi-level headers into hierarchical paths.
    E.g. [["Раздел", ""], ["Параметр", "Значение"]] → ["Раздел | Параметр", "Раздел | Значение"]
    """
    if not header_rows:
        return []

    col_count = len(header_rows[0])
    paths: list[list[str]] = [[] for _ in range(col_count)]

    for row in header_rows:
        prev = ""
        for c_idx in range(col_count):
            cell = row[c_idx].strip() if c_idx < len(row) else ""
            # If empty, inherit from left (merged cell carry-forward)
            if not cell:
                cell = prev
            else:
                prev = cell
            if cell:
                paths[c_idx].append(cell)

    return [
        " | ".join(dict.fromkeys(parts)) if parts else f"col_{i + 1}"
        for i, parts in enumerate(paths)
    ]


def normalize_matrix(raw_json: dict) -> list[dict]:
    """
    Expand raw_matrix (with colspan/rowspan) into list of row dicts.

    Returns: [{"header_path": cell_value, ...}, ...]
    """
    raw_matrix = raw_json.get("raw_matrix", [])
    if not raw_matrix:
        return []

    grid = _expand_grid(raw_matrix)
    if not grid:
        return []

    depth = _detect_header_depth(grid)
    col_paths = _build_column_paths(grid[:depth])
    data_rows = grid[depth:]

    result = []
    for row in data_rows:
        if not any(row):
            continue
        row_dict: dict[str, Any] = {}
        for c_idx, header in enumerate(col_paths):
            val = row[c_idx] if c_idx < len(row) else ""
            row_dict[header] = val
        result.append(row_dict)

    return result


# ─── enrich_and_validate ────────────────────────────────────────────────────

# Common construction/engineering abbreviations
_ABBREV_DICT: dict[str, str] = {
    "ПДК": "Предельно допустимая концентрация",
    "ВПУ": "Водоподготовительная установка",
    "ИТП": "Индивидуальный тепловой пункт",
    "ЦТП": "Центральный тепловой пункт",
    "АУП": "Автоматическая установка пожаротушения",
    "АУПС": "Автоматическая установка пожарной сигнализации",
    "ОВ": "Отопление и вентиляция",
    "ВК": "Водоснабжение и канализация",
    "ЭМ": "Электромонтаж",
    "КЖ": "Конструкции железобетонные",
    "КМ": "Конструкции металлические",
    "АР": "Архитектурные решения",
    "ГП": "Генеральный план",
    "ТМ": "Теплоснабжение и механика",
    "ПОС": "Проект организации строительства",
    "ПЗ": "Пояснительная записка",
    "ТЗ": "Техническое задание",
    "НТД": "Нормативно-техническая документация",
    "ТР": "Технический регламент",
    "ГОСТ": "Государственный стандарт",
    "СП": "Свод правил",
    "СНиП": "Строительные нормы и правила",
}

_NUM_RE = re.compile(r"^-?\d[\d\s.,]*$")


def _classify_data_type(row: dict) -> str:
    """Guess data type from cell values."""
    values = [str(v) for v in row.values() if v]
    numeric = sum(1 for v in values if _NUM_RE.match(v.replace("\xa0", "").strip()))
    if numeric / max(len(values), 1) > 0.5:
        return "numeric"
    return "text"


def enrich_and_validate(normalized_rows: list[dict]) -> list[dict]:
    """
    Convert normalized row dicts into chunk-ready records.

    Each output record has:
        textualization: str   — human-readable text for embedding
        abbreviations:  list  — decoded abbreviations found in text
        data_type:      str   — "numeric" | "text"
    """
    enriched = []
    for row in normalized_rows:
        # Build textualization: "Header: value. Header: value." format
        parts = []
        for key, val in row.items():
            v = str(val).strip() if val is not None else ""
            if v and v != "None":
                parts.append(f"{key}: {v}")

        textualization = ". ".join(parts) if parts else ""

        # Find abbreviations
        abbrevs = []
        for term, decoded in _ABBREV_DICT.items():
            if term in textualization:
                abbrevs.append({"term": term, "decoded": decoded, "confidence": 0.95})

        enriched.append({
            "textualization": textualization,
            "abbreviations": abbrevs,
            "data_type": _classify_data_type(row),
        })

    return enriched


# ─── self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test 1: 2-level header with rowspan and colspan (no placeholder cells in sub-rows)
    # Row 1 has only 2 sub-headers since col 0 is covered by rowspan from row 0.
    raw = {
        "raw_matrix": [
            [
                {"text": "Система", "colspan": 1, "rowspan": 2},
                {"text": "Вентилятор", "colspan": 2, "rowspan": 1},
            ],
            [
                # No placeholder for col 0 (covered by rowspan above)
                {"text": "L, м3/ч", "colspan": 1, "rowspan": 1},
                {"text": "P, Па",   "colspan": 1, "rowspan": 1},
            ],
            [
                {"text": "П1",    "colspan": 1, "rowspan": 1},
                {"text": "5000",  "colspan": 1, "rowspan": 1},
                {"text": "350",   "colspan": 1, "rowspan": 1},
            ],
            [
                {"text": "В1",    "colspan": 1, "rowspan": 1},
                {"text": "3000",  "colspan": 1, "rowspan": 1},
                {"text": "200",   "colspan": 1, "rowspan": 1},
            ],
        ],
        "units": [],
        "footnotes": [],
    }

    rows = normalize_matrix(raw)
    assert len(rows) == 2, f"Expected 2 data rows, got {len(rows)}"
    assert "Система" in rows[0], f"Missing 'Система': {list(rows[0].keys())}"
    assert "Вентилятор | L, м3/ч" in rows[0], f"Missing merged header: {list(rows[0].keys())}"
    assert "Вентилятор | P, Па" in rows[0], f"Missing merged header: {list(rows[0].keys())}"
    print(f"Test 1 OK: {len(rows)} rows, cols={list(rows[0].keys())}")

    enriched = enrich_and_validate(rows)
    assert len(enriched) == 2
    assert "Система: П1" in enriched[0]["textualization"]
    print(f"Test 2 OK: textualization = '{enriched[0]['textualization'][:80]}'")

    # Test 2: empty matrix
    assert normalize_matrix({"raw_matrix": []}) == []
    print("Test 3 OK: empty matrix -> []")

    # Test 3: single-level header (no colspan/rowspan)
    flat = {
        "raw_matrix": [
            [{"text": "Наименование", "colspan": 1, "rowspan": 1},
             {"text": "Ед.изм",       "colspan": 1, "rowspan": 1},
             {"text": "Кол-во",       "colspan": 1, "rowspan": 1}],
            [{"text": "Труба Ø25",    "colspan": 1, "rowspan": 1},
             {"text": "м.п.",         "colspan": 1, "rowspan": 1},
             {"text": "120",          "colspan": 1, "rowspan": 1}],
        ]
    }
    flat_rows = normalize_matrix(flat)
    assert flat_rows[0].get("Наименование") == "Труба Ø25"
    assert flat_rows[0].get("Кол-во") == "120"
    print(f"Test 4 OK: flat table parsed correctly")

    print("ALL TESTS PASSED")
