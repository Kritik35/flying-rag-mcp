# -*- coding: utf-8 -*-
"""Deterministic table aggregation (sum/count) over engineering tables.

Ported from Л.Е.С. table_query (ADR-11: LLM decides WHAT to count, Python counts
HOW MUCH — the model never touches arithmetic). Difference: flying-rag does not
keep a per-row Parquet store (raw_tables is unused), so we re-parse the SOURCE
file (xlsx/pdf/docx) on demand and aggregate over ALL rows — not top-k text
chunks. Summing top-k retrieved text is exactly why plain RAG miscounts (it sees
only part of the rows). Here the total is VERIFIED against the full table.

Public entrypoint: sum_table_values(subject, ...).
"""
from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent

# header text -> unified field (deterministic, order matters: name before amount_mat)
_COLUMN_PATTERNS = [
    ("pos", ("№", "номер", "поз", "п/п")),
    ("name", ("наименование", "наимен", "работ", "оборудован", "материал", "ресурс", "объект")),
    ("section", ("раздел", "глава", "этап")),
    ("amount_mat", ("стоимость материал", "материалы, руб", "сумма материал")),
    ("amount_work", ("оплата труда", "стоимость работ", "зп", "сумма работ")),
    ("work_done", ("выполнено", "отчёт", "отчет")),
    ("price", ("цена", "стоимость ед", "единичная", "расцен")),
    ("amount", ("сумма", "итого", "всего", "стоимость")),
    ("qty_per_unit", ("расход", "на единицу")),
    ("qty", ("кол-во", "колич", "количество", "объем", "объём", "масса", "площад", "qty")),
    ("unit", ("ед.изм", "ед. изм", "единица", "изм.", "ед.")),
    ("code", ("шифр", "код", "артикул")),
    ("mark", ("марка", "тип", "модель")),
]

_NUMERIC_FIELDS = {
    "amount": ("сумм", "стоимост", "итого", "руб", "затрат"),
    "qty": ("колич", "кол-во", "объем", "объём", "сколько", "метр", "погон", "масса", "вес", "площад"),
    "price": ("цен", "расцен"),
    "amount_mat": ("материал",),
    "amount_work": ("работ", "труд"),
    "work_done": ("выполнено",),
}

_QUERY_TOKENS = ("сумм", "итого", "посчитай", "сколько", "колич", "кол-во",
                 "объем", "объём", "стоимост", "цена", "всего", "общая", "общий",
                 "общее", "метраж", "масса", "сосчитай", "подсчитай")

_STOPWORDS = {
    "сумма", "сумму", "суммарно", "итого", "посчитай", "сосчитай", "подсчитай",
    "сколько", "какая", "какой", "какие", "найди", "покажи", "общая", "общую",
    "общий", "общее", "общие", "всего", "все", "всех", "по", "для", "про", "в",
    "на", "из", "и", "или", "руб", "рублей", "штук", "шт", "метров", "метраж",
    "стоимость", "стоимости", "количество", "кол-во", "объем", "объём", "цена",
    "площадь", "площади", "площадью", "суммарная", "суммарный", "суммарное",
    "масса", "массы", "вес", "веса", "погонных", "погонный",
}


def _to_number(value: Any) -> Optional[float]:
    """Russian-aware numeric coercion: '15 030,72' / '1 234.56' / '1.234,5' -> float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if math.isnan(f) else f
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("\xa0", " ").replace(" ", " ")
    # keep first numeric token (allow spaces as thousands, . and , as separators)
    m = re.search(r"-?\d[\d \.,]*\d|-?\d", s)
    if not m:
        return None
    tok = m.group(0).replace(" ", "")
    if "." in tok and "," in tok:
        # last separator is the decimal one
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif "," in tok:
        tok = tok.replace(",", ".")
    elif tok.count(".") > 1:                     # 1.234.567 -> thousands
        tok = tok.replace(".", "")
    try:
        return float(tok)
    except ValueError:
        return None


# Заголовок в ведомости по ГОСТ 21.110 переносится по слогам: «Обозна-\nчение»,
# «Наимено-\nвание». Склейка переноса обязана произойти до сопоставления, иначе
# от заголовка остаётся половина слова.
def _normalise_header(text: Any) -> str:
    s = re.sub(r"-\s*\n\s*", "", str(text if text is not None else ""))
    return re.sub(r"\s+", " ", s).strip().casefold()


# Точные соответствия проверяются ДО подстрочных: сокращения ГОСТ коротки и
# многозначны. «Обозначение» в ведомости — это позиция, а в спецификации
# заголовок «Тип, марка, обозначение документа, опросного листа» — это марка;
# подстрочное правило спутало бы их и сломало разбор .xlsx, который работает.
_EXACT_HEADERS = {
    "кол.": "qty",
    "кол": "qty",
    "кол-во": "qty",
    "количество": "qty",
    "обозначение": "pos",
    "обозначение системы": "pos",
    "поз.": "pos",
    "поз": "pos",
    "позиция": "pos",
    "марка": "mark",
    "тип": "mark",
    # «Тип (наименование)» в ведомости — это модель оборудования. Подстрочное
    # правило видит в нём «наимен» и отдаёт колонке name, где уже лежит
    # обслуживаемое помещение, — марка теряется, а вместе с ней возможность
    # найти позицию по модели.
    "тип (наименование)": "mark",
    "тип (наименование) оборудования": "mark",
    "примечание": "skip",
    "масса ед., кг": "skip",
}


def _map_columns(headers: list[str]) -> dict[int, str]:
    """Map column index -> unified field."""
    mapping: dict[int, str] = {}
    for idx, header in enumerate(headers):
        norm = _normalise_header(header)
        if norm in _EXACT_HEADERS:
            mapping[idx] = _EXACT_HEADERS[norm]
            continue
        field = "skip"
        for candidate, hints in _COLUMN_PATTERNS:
            if any(hint in norm for hint in hints):
                field = candidate
                break
        mapping[idx] = field
    return mapping


def _is_blank_row(row: list) -> bool:
    return not any(v is not None and str(v).strip() for v in row)


def _filled(row: list) -> list:
    return [v for v in row if v is not None and str(v).strip()]


def _is_section_title(row: list) -> bool:
    """Одна заполненная ячейка на широкой строке — заголовок раздела ведомости.

    В ведомости по ГОСТ 21.110 разделы («Отопительные агрегаты», «Воздушно-
    тепловые завесы») идут объединённой ячейкой во всю ширину. Считая их
    обычной строкой, разбор склеивает разные разделы в один и теряет то
    единственное место, где написано, что это за оборудование: в самих строках
    стоят «КЭВ-200П512W» и «У-02.8.1», слова «завеса» там нет.
    """
    if len(row) < 3:
        return False
    filled = _filled(row)
    if len(filled) != 1:
        return False
    title = str(filled[0]).strip()
    # Заголовок раздела — короткая строка в одну строку. Штамп листа тоже
    # состоит из одиночных широких ячеек, но там адрес объекта на три строки и
    # реквизиты заказчика; приняв их за раздел, разбор съедал весь лист.
    return 4 <= len(title) <= 80 and chr(10) not in title


def _is_numbering_row(row: list) -> bool:
    """Строка «1 | 2 | 3 | …» — требование ГОСТ к оформлению, а не данные.

    Она же служит надёжной границей: всё выше неё до заголовка — ярусы шапки,
    всё ниже — позиции.
    """
    values = [str(v).strip() for v in _filled(row)]
    if len(values) < 3 or not all(v.isdigit() for v in values):
        return False
    return [int(v) for v in values] == list(range(1, len(values) + 1))


def _merge_header_tiers(tiers: list[list]) -> list[str]:
    """Склеить ярусы шапки в одно имя на колонку.

    «Вентилятор» + «L м3/ч» -> «Вентилятор L м3/ч». Без склейки нижний ярус
    теряется, а именно в нём стоят единицы и величины.
    """
    width = max((len(t) for t in tiers), default=0)
    headers = []
    for c in range(width):
        parts = []
        for tier in tiers:
            if c < len(tier) and tier[c] is not None and str(tier[c]).strip():
                part = _normalise_header(tier[c])
                if part and part not in parts:
                    parts.append(part)
        headers.append(" ".join(parts) if parts else f"col_{c}")
    return headers


def _find_header_row(grid: list[list], max_scan: int = 25) -> int:
    """Pick the row that most looks like a header (many short text cells)."""
    best_row, best_score = 0, 0
    for i in range(min(max_scan, len(grid))):
        row = grid[i]
        non_empty = sum(1 for v in row if v is not None and str(v).strip())
        text_cells = sum(1 for v in row if isinstance(v, str) and len(str(v).strip()) > 1)
        score = text_cells * 2 + non_empty
        if score > best_score:
            best_score, best_row = score, i
    return best_row


def _rows_from_grid(grid: list[list]) -> list[dict[str, Any]]:
    """Разобрать сетку в строки, разделяя её на разделы.

    Раньше сетка считалась одной таблицей с одной строкой-шапкой. На листе по
    ГОСТ это давало мусор: `sum_table_values(subject='КЭВ', op='count')`
    отвечал 17 при тринадцати позициях и возвращал строки без единого поля —
    со статусом VERIFIED. Разбор .xlsx с одной шапкой не меняется: там нет ни
    заголовков разделов, ни строки нумерации, и ветка остаётся прежней.
    """
    if not grid:
        return []

    out: list[dict[str, Any]] = []
    section: str | None = None
    headers: list[str] | None = None
    colmap: dict[int, str] = {}
    i, n = 0, len(grid)

    while i < n:
        if _is_blank_row(grid[i]):
            i += 1
            continue
        if _is_section_title(grid[i]):
            section = str(_filled(grid[i])[0]).strip()
            i += 1
            continue

        # Строка нумерации колонок, требуемая ГОСТ, — надёжная граница шапки:
        # всё от начала блока до неё есть ярусы заголовка, всё ниже — позиции.
        # Искать шапку «лучшей строкой» здесь нельзя: строка данных с длинными
        # названиями набирает больше очков, чем настоящий заголовок, и разбор
        # уезжает в середину таблицы.
        numbering = None
        for k in range(i, min(i + 8, n)):
            if _is_numbering_row(grid[k]):
                numbering = k
                break

        if numbering is not None and numbering > i:
            headers = _merge_header_tiers(
                [r for r in grid[i:numbering] if not _is_blank_row(r)]
            )
            colmap = _map_columns(headers)
            data_start = numbering + 1
        elif headers is None:
            hdr_start = i + _find_header_row(grid[i:])
            headers = [str(v).strip() if v is not None else f"col_{c}"
                       for c, v in enumerate(grid[hdr_start])]
            colmap = _map_columns(headers)
            data_start = hdr_start + 1
        else:
            # Шапка уже известна и повторять её незачем. В спецификации .xlsx
            # заголовок один на всю таблицу, а разделы («Воздухозабор ВЗ-2-1»)
            # идут ниже него: выводя шапку заново в каждом разделе, разбор брал
            # за заголовок первую попавшуюся строку данных и терял всё —
            # 13 060 строк превращались в две.
            data_start = i
        j = data_start
        while j < n and not _is_section_title(grid[j]):
            row = grid[j]
            j += 1
            if _is_blank_row(row) or _is_numbering_row(row):
                continue
            rec: dict[str, Any] = {"raw_row": {}}
            if section:
                rec["section"] = section
            for c, val in enumerate(row):
                header = headers[c] if c < len(headers) else f"col_{c}"
                rec["raw_row"][header] = val
                field = colmap.get(c, "skip")
                if field == "skip":
                    continue
                if field in ("name", "unit", "pos", "code", "mark", "section"):
                    if val is not None and str(val).strip():
                        rec.setdefault(field, str(val).strip())
                else:
                    num = _to_number(val)
                    if num is not None:
                        rec.setdefault(field, num)
            # Строка, из которой не удалось достать ни одного поля, — это не
            # позиция ведомости. Возвращать её со статусом VERIFIED опаснее,
            # чем не возвращать вовсе.
            if [k for k in rec if k not in ("raw_row", "section")]:
                out.append(rec)
        i = j

    return out

def _tables_from_xlsx(path: Path, max_rows_per_sheet: int = 100000) -> list[list[list]]:
    import openpyxl
    grids = []
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    for ws in wb.worksheets:
        grid = []
        for row in ws.iter_rows(values_only=True):   # fast streaming read
            grid.append(list(row))
            if len(grid) >= max_rows_per_sheet:
                break
        if len(grid) >= 2:
            grids.append(grid)
    wb.close()
    return grids


def _tables_from_pdf(path: Path, max_pages: int = 400, max_tables: int = 4000) -> list[list[list]]:
    # PyMuPDF (fitz) find_tables first — fast & robust enough for 100-180MB
    # engineering PDFs where pdfplumber stalls/OOMs. Fallback to pdfplumber.
    grids: list[list[list]] = []
    try:
        import fitz
        doc = fitz.open(str(path))
        try:
            for i, page in enumerate(doc):
                if i >= max_pages or len(grids) >= max_tables:
                    break
                try:
                    finder = page.find_tables()
                except Exception:
                    continue
                for t in getattr(finder, "tables", []):
                    try:
                        grid = t.extract()
                    except Exception:
                        continue
                    if grid and len(grid) >= 2:
                        grids.append(grid)
        finally:
            doc.close()
        if grids:
            return grids
    except Exception:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:min(max_pages, 60)]:
                for tbl in page.extract_tables() or []:
                    if tbl and len(tbl) >= 2:
                        grids.append(tbl)
    except Exception:
        pass
    return grids


def _tables_from_docx(path: Path) -> list[list[list]]:
    import docx
    grids = []
    for t in docx.Document(str(path)).tables:
        grid = [[cell.text for cell in row.cells] for row in t.rows]
        if len(grid) >= 2:
            grids.append(grid)
    return grids


def _tables_from_csv(path: Path) -> list[list[list]]:
    import csv as _csv

    # sniff delimiter (ru CSV often uses ';'); tolerant decode
    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            text = path.read_text(encoding=enc)
            break
        except Exception:
            text = None
    if text is None:
        return []
    sample = text[:4096]
    try:
        dialect = _csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delim = dialect.delimiter
    except Exception:
        delim = ";" if sample.count(";") >= sample.count(",") else ","
    grid = [row for row in _csv.reader(text.splitlines(), delimiter=delim)]
    return [grid] if len(grid) >= 2 else []


def _extract_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xlsm", ".xls"):
            grids = _tables_from_xlsx(path)
        elif suffix == ".pdf":
            grids = _tables_from_pdf(path)
        elif suffix in (".docx",):
            grids = _tables_from_docx(path)
        elif suffix in (".csv", ".tsv"):
            grids = _tables_from_csv(path)
        else:
            return []
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for grid in grids:
        rows.extend(_rows_from_grid(grid))
    return rows


# ── file resolution via metadata.db ────────────────────────────────────────

def _meta_db() -> Path:
    import yaml
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return ROOT / cfg["storage"]["metadata_db"]


_TABLE_EXT = (".xlsx", ".xlsm", ".xls", ".pdf", ".docx", ".csv", ".tsv")


def _resolve_files(subject: str, source_like: Optional[str], dataset: Optional[str],
                   max_files: int) -> list[str]:
    db = _meta_db()
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        dataset_where = " AND dataset = ?" if dataset else ""
        dataset_params = [dataset] if dataset else []
        if source_like:
            base_params = [f"%{source_like}%"] + dataset_params
            rows = con.execute(
                f"SELECT source_path FROM files WHERE source_path LIKE ?{dataset_where} "
                "ORDER BY source_path",
                base_params,
            ).fetchall()
            all_files = [r[0] for r in rows]
            files = []
            kws = _keywords(subject)
            if kws:
                like = " OR ".join("pc.parent_text LIKE ?" for _ in kws)
                params = [f"%{source_like}%"] + dataset_params + [f"%{k}%" for k in kws]
                q = (
                    "SELECT DISTINCT f.source_path "
                    "FROM files f "
                    "JOIN parent_chunks pc ON pc.source_path = f.source_path "
                    f"WHERE f.source_path LIKE ?{dataset_where} AND ({like})"
                    " ORDER BY f.source_path"
                )
                files = [r[0] for r in con.execute(q, params).fetchall()]
            seen = set(files)
            files.extend(f for f in all_files if f not in seen)
        else:
            kws = _keywords(subject)
            files = []
            if kws:
                # files whose table text mentions the subject (target the right doc)
                like = " OR ".join("parent_text LIKE ?" for _ in kws)
                params = [f"%{k}%" for k in kws]
                if dataset:
                    q = (
                        "SELECT DISTINCT pc.source_path "
                        "FROM parent_chunks pc "
                        "JOIN files f ON f.source_path = pc.source_path "
                        f"WHERE ({like}) AND f.dataset = ?"
                    )
                    params.append(dataset)
                else:
                    q = (
                        f"SELECT DISTINCT source_path FROM parent_chunks WHERE {like} "
                        "ORDER BY source_path"
                    )
                files = [r[0] for r in con.execute(q, params).fetchall()]
            if not files:
                if dataset:
                    rows = con.execute(
                        "SELECT source_path FROM files WHERE dataset = ? ORDER BY source_path",
                        (dataset,),
                    ).fetchall()
                else:
                    rows = con.execute("SELECT source_path FROM files ORDER BY source_path").fetchall()
                files = [r[0] for r in rows]
    finally:
        con.close()
    out = [f for f in files if str(f).lower().endswith(_TABLE_EXT)]
    return _one_file_per_document(out)[:max_files]


# Спецификация лежит в корпусе и как .xlsx, и как .pdf одного и того же
# документа. Складывая обе, инструмент удваивал ответ: по ОВ2-С-00-СО выходило
# 169 214 при верных 81 511 — и удваивал молча, показывая оба файла в
# `sources`. Из копий берётся одна, и предпочтение у формата, где таблица
# хранится ячейками: в .xlsx разбор совпал с независимым подсчётом до копейки
# (4149 строк, 81 511.01), в .pdf те же данные разъезжаются на 4863 строки.
_FORMAT_RANK = {".xlsx": 0, ".xlsm": 1, ".xls": 2, ".csv": 3, ".tsv": 4,
                ".docx": 5, ".pdf": 6}
_COPY_SUFFIX = __import__("re").compile(r"[\s_]*\(\d+\)$")


def _document_key(path: str) -> str:
    name = Path(path).stem.strip().casefold()
    return _COPY_SUFFIX.sub("", name).strip()


def _one_file_per_document(files: list[str]) -> list[str]:
    best: dict[str, str] = {}
    order: list[str] = []
    for f in files:
        key = _document_key(f)
        if key not in best:
            best[key] = f
            order.append(key)
            continue
        rank_new = _FORMAT_RANK.get(Path(f).suffix.lower(), 99)
        rank_old = _FORMAT_RANK.get(Path(best[key]).suffix.lower(), 99)
        if rank_new < rank_old:
            best[key] = f
    return [best[k] for k in order]


# ── selection / filtering (ported) ─────────────────────────────────────────

# Inline parse cap: a query must never hang on a huge PDF. Giants past this size
# are only populated by the offline build_table_parquet runner (per-file isolated).
_INLINE_PDF_MAX_MB = 30.0


def _rows_for_file(fp: str) -> list[dict[str, Any]]:
    """Parquet-first: read pre-parsed rows if present (fast), else parse the
    source once and lazily persist for next time. Huge un-backfilled PDFs are
    skipped inline (return []) so an MCP query can never hang on a giant."""
    try:
        from rag_server import table_parquet as tp
        if tp.has_parquet(fp):
            return tp.read_parquet_rows(fp)
        p = Path(fp)
        if p.suffix.lower() == ".pdf":
            try:
                if p.stat().st_size / (1024 * 1024) > _INLINE_PDF_MAX_MB:
                    return []  # giant — must be pre-backfilled offline
            except OSError:
                pass
        rows = _extract_rows(p)
        if rows and tp.is_enabled():
            try:
                tp.write_parquet(fp, rows)
            except Exception:
                pass
        return rows
    except Exception:
        return _extract_rows(Path(fp))


def _looks_like_table_query(q: str) -> bool:
    ql = q.casefold()
    return any(t in ql for t in _QUERY_TOKENS)


def _select_field(question: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    q = question.casefold()
    # measures/counts win first (avoids 'суммарная' falsely scoring the amount col)
    if re.search(r"площад|объ[ёе]м|метр|погон|масс|вес|колич|кол-во|сколько", q):
        return "qty"
    if "материал" in q:
        return "amount_mat"
    if re.search(r"работ|труд", q) and re.search(r"стоимост|сумм|руб", q):
        return "amount_work"
    if re.search(r"стоимост|цен|расцен|затрат|руб", q):
        return "amount"
    if re.search(r"\bсумм", q) and "суммарн" not in q:
        return "amount"
    return "qty"


def _keywords(question: str) -> list[str]:
    toks = re.findall(r"[0-9A-Za-zА-Яа-яЁё][0-9A-Za-zА-Яа-яЁё.\-х/]{1,}", question.casefold())
    kept = [t for t in toks if t not in _STOPWORDS and not t.isdigit() and len(t) >= 2]
    # Предмет запроса склоняется, строки ведомости — нет. Срезается окончание
    # только у запроса: «завеса» -> «завес» находит «завесы» в заголовке
    # раздела, а «воздуховод» и «клапан» не меняются и дают прежние итоги.
    return [_subject_stem(t) for t in kept]


def _row_text(row: dict[str, Any]) -> str:
    """Текст строки для сопоставления с предметом запроса.

    Метка раздела сюда НЕ входит. На листе 10.02 извлекатель теряет второй
    заголовок: сорок отопительных агрегатов и семнадцать завес идут подряд без
    разделителя, и весь блок получает метку «Воздушно-тепловые завесы».
    Считая по ней, инструмент отвечал на «сколько завес» числом 57 при
    семнадцати — уверенно и неверно. Метка остаётся в возвращаемых строках,
    чтобы её было видно, но решения по ней не принимаются.
    """
    parts = []
    for k, v in row.items():
        if k == "section":
            continue
        if k == "raw_row" and isinstance(v, dict):
            parts.extend(str(x) for x in v.values() if x is not None)
        elif not isinstance(v, (int, float)):
            parts.append(str(v))
    return " ".join(parts).casefold()


# Окончания, которые можно снять со слова из запроса, не задев корень.
# Список намеренно короткий: срезать больше — значит начать ловить чужие слова,
# а цена ложного совпадения в ведомости выше, чем цена ненайденной формы.
_SUBJECT_ENDINGS = ("ами", "ями", "ов", "ев", "ей", "ам", "ям", "ах", "ях",
                    "ой", "ей", "ы", "и", "а", "я", "у", "ю", "е", "о")
_SUBJECT_MIN_STEM = 5


def _subject_stem(word: str) -> str:
    """Слово из запроса без окончания.

    В русском окончание дописывается справа, поэтому корень запроса уже
    является началом словоформы в тексте: «воздуховод» находит «воздуховоды»
    сам. Обратное не работает — «завеса» не входит в «завесы», и раздел
    «Воздушно-тепловые завесы» не находился вовсе.

    Срезается только запрос; текст строки не трогается. Слова, которые и так
    работали, при этом не меняются, поэтому сверенные итоги остаются прежними.
    """
    low = str(word or "").strip().casefold()
    if not low or not all(ch.isalpha() or ch == "-" for ch in low):
        return low
    for ending in _SUBJECT_ENDINGS:
        if low.endswith(ending) and len(low) - len(ending) >= _SUBJECT_MIN_STEM:
            return low[: -len(ending)]
    return low


def _row_matches(row: dict[str, Any], keywords: list[str]) -> bool:
    text = _row_text(row)
    return all(k in text for k in keywords)


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return f"{round(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def sum_table_values(
    subject: str,
    source_like: Optional[str] = None,
    field: Optional[str] = None,
    op: str = "sum",
    dataset: Optional[str] = None,
    max_files: int = 20,
    max_rows: int = 50,
) -> dict[str, Any]:
    """Deterministically aggregate a numeric column over ALL matching table rows.

    LLM/caller supplies the subject (WHAT); this function computes the total
    (HOW MUCH) in pure Python over the full source table — VERIFIED, no model
    arithmetic. Returns total/count/sources/sample rows.
    """
    subject = (subject or "").strip()
    if not subject:
        return {"error": "subject is required"}

    files = _resolve_files(subject, source_like, dataset, max_files)
    if not files:
        return {"matched": False, "reason": "no candidate table files found",
                "hint": "pass source_like to point at a specific xlsx/pdf/docx"}

    sel_field = _select_field(subject, field)
    keywords = _keywords(subject) if not source_like else _keywords(subject)
    matched_rows: list[dict[str, Any]] = []
    sources: list[str] = []
    scanned_files = 0

    for fp in files:
        rows = _rows_for_file(fp)
        if not rows:
            continue
        scanned_files += 1
        hit_in_file = False
        for row in rows:
            if keywords and not _row_matches(row, keywords):
                continue
            enriched = dict(row)
            enriched["_source"] = fp
            matched_rows.append(enriched)
            hit_in_file = True
        if hit_in_file and fp not in sources:
            sources.append(fp)

    if not matched_rows:
        return {"matched": False, "field": sel_field,
                "reason": "no rows matched the subject keywords",
                "keywords": keywords, "scanned_files": scanned_files,
                "candidate_files": [Path(f).name for f in files[:10]]}

    if op == "count":
        return {"matched": True, "operation": "count", "count": len(matched_rows),
                "sources": [Path(s).name for s in sources],
                "status": "VERIFIED",
                "rows": [_row_preview(r) for r in matched_rows[:max_rows]]}

    # sum with data-aware fallback (e.g. ВОР with amount=0 -> use qty)
    def _collect(f):
        return [v for v in (_as_num(r.get(f)) for r in matched_rows) if v is not None]

    numbers = _collect(sel_field)
    used_field = sel_field
    if (not numbers or sum(numbers) == 0) and sel_field != "qty":
        alt = _collect("qty")
        if alt and sum(alt) != 0:
            numbers, used_field = alt, "qty"

    if not numbers:
        return {"matched": True, "operation": "list", "field": sel_field,
                "reason": f"matched rows have no numeric '{sel_field}'",
                "count": len(matched_rows),
                "sources": [Path(s).name for s in sources],
                "rows": [_row_preview(r) for r in matched_rows[:max_rows]]}

    total = sum(numbers)
    return {
        "matched": True,
        "operation": "sum",
        "field": used_field,
        "total": total,
        "total_formatted": _fmt(total),
        "count": len(numbers),
        "rows_matched": len(matched_rows),
        "sources": [Path(s).name for s in sources],
        "keywords": keywords,
        "status": "VERIFIED",
        "note": "Sum computed in Python over ALL matching source-table rows "
                "(not top-k text). Verify critical totals against the source file.",
        "rows": [_row_preview(r) for r in matched_rows[:max_rows]],
    }


def _as_num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        return float(v)
    return _to_number(v)


def _row_preview(row: dict[str, Any]) -> dict[str, Any]:
    keep = {k: row.get(k) for k in ("pos", "name", "unit", "qty", "amount",
                                    "amount_mat", "amount_work", "price")
            if row.get(k) not in (None, "")}
    keep["_source"] = Path(str(row.get("_source", ""))).name
    return keep
