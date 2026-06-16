from __future__ import annotations
"""
parsers/office.py — DOCX and XLSX parser with real colspan/rowspan extraction.

DOCX tables:
  - Reads gridSpan (colspan) from <w:gridSpan> XML attribute
  - Handles vMerge (rowspan): restart cells set rowspan by lookahead;
    continuation cells are placed as "" to preserve column positions

XLSX tables:
  - Uses openpyxl merged_cells to get real colspan/rowspan for master cells;
    slave (non-top-left) merged cells are skipped/placeholder

Both formats feed into parsers/table_normalizer.normalize_matrix()
for header detection and textualization.
"""
import os
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
    ctime = os.path.getctime(path)
    mtime = os.path.getmtime(path)
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return fmt(ctime), fmt(mtime)


# ─── DOCX ─────────────────────────────────────────────────────────────────────

def _docx_cell_text(tc, qn) -> str:
    """Extract plain text from a <w:tc> element."""
    return "".join(t.text or "" for t in tc.iter(qn("w:t"))).strip()


def _docx_cell_props(tc, qn) -> tuple[int, str | None]:
    """Return (colspan, vmerge) for a <w:tc> element.
    vmerge: None | 'restart' | 'continue'
    """
    tcPr = tc.find(qn("w:tcPr"))
    colspan = 1
    vmerge = None
    if tcPr is not None:
        gs = tcPr.find(qn("w:gridSpan"))
        if gs is not None:
            try:
                colspan = int(gs.get(qn("w:val"), "1"))
            except (TypeError, ValueError):
                colspan = 1
        vm = tcPr.find(qn("w:vMerge"))
        if vm is not None:
            v = vm.get(qn("w:val"))
            vmerge = "restart" if v == "restart" else "continue"
    return colspan, vmerge


def _docx_table_to_matrix(table) -> list[list[dict]]:
    """Convert a python-docx Table to raw_matrix with colspan/rowspan.

    Strategy:
    - vMerge='restart' → compute rowspan by counting consecutive 'continue'
      cells in the same column in rows below.
    - vMerge='continue' → include as {"text": "", colspan, rowspan=1}
      so column positions are preserved for the normalizer.
    - gridSpan → colspan.
    """
    try:
        from docx.oxml.ns import qn
    except ImportError:
        return []

    rows_tcs = [row._tr.tc_lst for row in table.rows]
    n_rows = len(rows_tcs)
    if n_rows == 0:
        return []

    # Compute grid width = max sum of colspan across any row
    def _row_width(tcs):
        return sum(_docx_cell_props(tc, qn)[0] for tc in tcs)

    grid_width = max((_row_width(tcs) for tcs in rows_tcs), default=0)
    if grid_width == 0:
        return []

    # Pre-compute (colspan, vmerge) for every tc
    rows_props = [
        [_docx_cell_props(tc, qn) for tc in tcs]
        for tcs in rows_tcs
    ]
    rows_texts = [
        [_docx_cell_text(tc, qn) for tc in tcs]
        for tcs in rows_tcs
    ]

    # Map each (row, grid_col) to its tc index in that row (accounting for colspan)
    # col_map[r_idx][grid_c] = (tc_index, colspan, vmerge)
    col_map: list[dict[int, tuple[int, int, str | None]]] = []
    for r_idx in range(n_rows):
        cmap: dict[int, tuple[int, int, str | None]] = {}
        g_col = 0
        for tc_i, (cs, vm) in enumerate(rows_props[r_idx]):
            for offset in range(cs):
                if g_col + offset < grid_width:
                    cmap[g_col + offset] = (tc_i, cs, vm)
            g_col += cs
        col_map.append(cmap)

    raw_matrix: list[list[dict]] = []

    for r_idx in range(n_rows):
        row_data: list[dict] = []
        visited_tc_indices: set[int] = set()
        g_col = 0

        while g_col < grid_width:
            info = col_map[r_idx].get(g_col)
            if info is None:
                g_col += 1
                continue

            tc_i, cs, vm = info
            if tc_i in visited_tc_indices:
                g_col += cs
                continue
            visited_tc_indices.add(tc_i)

            text = rows_texts[r_idx][tc_i]

            if vm == "continue":
                # Continuation of vertical merge: keep as "" to preserve column
                row_data.append({"text": "", "colspan": cs, "rowspan": 1})
            elif vm == "restart":
                # Count rowspan by looking ahead for 'continue' cells in same grid col
                rowspan = 1
                for look_r in range(r_idx + 1, n_rows):
                    look_info = col_map[look_r].get(g_col)
                    if look_info is None:
                        break
                    _, _, look_vm = look_info
                    if look_vm == "continue":
                        rowspan += 1
                    else:
                        break
                row_data.append({"text": text, "colspan": cs, "rowspan": rowspan})
            else:
                row_data.append({"text": text, "colspan": cs, "rowspan": 1})

            g_col += cs

        if row_data:
            raw_matrix.append(row_data)

    return raw_matrix


def _parse_docx(path: Path) -> tuple[str, dict]:
    import docx
    from parsers.table_normalizer import normalize_matrix, enrich_and_validate

    doc = docx.Document(path)

    # Extract paragraph text and headings
    lines: list[str] = []
    headings: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            lines.append(para.text)
        style_name = para.style.name if para.style else ""
        if style_name.startswith("Heading") and para.text.strip():
            headings.append(para.text)

    # Extract and textualize tables
    text_chunks: list[str] = []
    tables_count = len(doc.tables)
    for table in doc.tables:
        raw_matrix = _docx_table_to_matrix(table)
        if not raw_matrix:
            continue
        norm_rows = normalize_matrix({"raw_matrix": raw_matrix})
        enriched = enrich_and_validate(norm_rows)
        for row in enriched:
            t = row["textualization"].strip()
            if t:
                text_chunks.append(t)

    final_text = "\n".join(lines)
    if text_chunks:
        final_text += "\n\n" + "\n\n".join(text_chunks)

    return final_text, {
        "headings": headings,
        "tables": tables_count,
        "method": "native_docx_xml",
    }


# ─── XLSX ─────────────────────────────────────────────────────────────────────

def _xlsx_sheet_to_matrix(ws) -> list[list[dict]]:
    """Convert an openpyxl Worksheet to raw_matrix with colspan/rowspan.

    Uses ws.merged_cells to detect merge ranges. Master cells (top-left of
    merged range) carry colspan/rowspan. Slave cells (other positions) are
    included as "" to preserve column positions for the normalizer.
    """
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    if max_row == 0 or max_col == 0:
        return []

    # Build merge info maps
    # master_info[(r, c)] = (colspan, rowspan)
    # slave_info[(r, c)] = None  (just presence = "this is a slave cell")
    master_info: dict[tuple[int, int], tuple[int, int]] = {}
    slave_positions: set[tuple[int, int]] = set()

    for merge_range in ws.merged_cells.ranges:
        min_r = merge_range.min_row
        min_c = merge_range.min_col
        max_r = merge_range.max_row
        max_c = merge_range.max_col
        cs = max_c - min_c + 1
        rs = max_r - min_r + 1
        master_info[(min_r, min_c)] = (cs, rs)
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                if not (r == min_r and c == min_c):
                    slave_positions.add((r, c))

    raw_matrix: list[list[dict]] = []
    for r_idx in range(1, max_row + 1):
        row_data: list[dict] = []
        c_idx = 1
        while c_idx <= max_col:
            pos = (r_idx, c_idx)
            if pos in slave_positions:
                # Non-master merge cell: include as "" to preserve column position
                # For colspan slaves we skip (master's colspan covers them)
                # For rowspan slaves we insert "" placeholder
                # Determine if horizontal slave (same row as master) → skip
                # Determine if vertical slave (different row) → "" placeholder
                # A cell is a horizontal slave if its column master is in the same row
                is_horiz_slave = any(
                    r_idx == mr and mc < c_idx and (r_idx, mc) in master_info
                    and master_info[(r_idx, mc)][0] > (c_idx - mc)
                    for mr, mc in [(r_idx, mc) for mc in range(1, c_idx)]
                )
                if not is_horiz_slave:
                    # Vertical slave → insert "" to keep column position
                    row_data.append({"text": "", "colspan": 1, "rowspan": 1})
                c_idx += 1
                continue

            cell_val = ws.cell(r_idx, c_idx).value
            text = str(cell_val).strip() if cell_val is not None else ""

            if pos in master_info:
                cs, rs = master_info[pos]
                row_data.append({"text": text, "colspan": cs, "rowspan": rs})
                c_idx += cs  # skip columns covered by colspan
            else:
                row_data.append({"text": text, "colspan": 1, "rowspan": 1})
                c_idx += 1

        if any(r.get("text") for r in row_data):
            raw_matrix.append(row_data)

    return raw_matrix


def _parse_xlsx(path: Path) -> tuple[str, dict]:
    import zipfile
    import xml.etree.ElementTree as ET
    from parsers.table_normalizer import normalize_matrix, enrich_and_validate

    shared_strings = []
    sheet_files = []
    sheet_names = {}
    rel_map = {}

    with zipfile.ZipFile(path, 'r') as z:
        # Load workbook relations to find sheet names
        try:
            wb_data = z.read('xl/workbook.xml')
            root = ET.fromstring(wb_data)
            ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for s in root.findall('.//ns:sheet', ns):
                name = s.attrib.get('name')
                sheet_id = s.attrib.get('sheetId')
                r_id = s.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                sheet_names[r_id] = name
        except Exception:
            pass
            
        try:
            rels_data = z.read('xl/_rels/workbook.xml.rels')
            rels_root = ET.fromstring(rels_data)
            r_ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
            for rel in rels_root.findall('.//r:Relationship', r_ns):
                rid = rel.attrib.get('Id')
                target = rel.attrib.get('Target')
                rel_map[rid] = target
        except Exception:
            pass
            
        if 'xl/sharedStrings.xml' in z.namelist():
            try:
                ss_data = z.read('xl/sharedStrings.xml')
                root = ET.fromstring(ss_data)
                ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for t in root.findall('.//ns:t', ns):
                    shared_strings.append(t.text if t.text else "")
            except Exception:
                pass
                
        # List sheet files
        for name in z.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                sheet_files.append(name)
                
        sheet_files.sort()
        
        # Build sheet name mapping to file
        file_to_name = {}
        for rid, target in rel_map.items():
            if 'sheet' in target:
                fname = target.split('/')[-1]
                for sf in sheet_files:
                    if sf.endswith(fname):
                        file_to_name[sf] = sheet_names.get(rid, fname)
                        
        text_chunks = []
        total_rows = 0
        
        for sf in sheet_files:
            sname = file_to_name.get(sf, sf.split('/')[-1])
            text_chunks.append(f"Лист: {sname}")
            
            try:
                sheet_data = z.read(sf)
                root = ET.fromstring(sheet_data)
                ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                
                # Parse merged cells
                master_info = {}
                slave_positions = set()
                
                for mc in root.findall('.//ns:mergeCell', ns):
                    ref = mc.attrib.get('ref')
                    if not ref or ':' not in ref:
                        continue
                    start, end = ref.split(':')
                    
                    def ref_to_rc(cell_ref):
                        col_let = ''.join([c for c in cell_ref if c.isalpha()])
                        row_num = int(''.join([c for c in cell_ref if c.isdigit()]))
                        num = 0
                        for c in col_let:
                            num = num * 26 + (ord(c.upper()) - ord('A') + 1)
                        return row_num, num
                        
                    start_r, start_c = ref_to_rc(start)
                    end_r, end_c = ref_to_rc(end)
                    
                    cs = end_c - start_c + 1
                    rs = end_r - start_r + 1
                    master_info[(start_r, start_c)] = (cs, rs)
                    for r in range(start_r, end_r + 1):
                        for c in range(start_c, end_c + 1):
                            if not (r == start_r and c == start_c):
                                slave_positions.add((r, c))
                                
                # Parse cell values
                cells_data = {}
                max_r = 0
                max_c = 0
                
                for row in root.findall('.//ns:row', ns):
                    r_num_str = row.attrib.get('r')
                    if not r_num_str:
                        continue
                    r_num = int(r_num_str)
                    max_r = max(max_r, r_num)
                    
                    for cell in row.findall('./ns:c', ns):
                        ref = cell.attrib.get('r')
                        if not ref:
                            continue
                        col_let = ''.join([c for c in ref if c.isalpha()])
                        c_num = 0
                        for c in col_let:
                            c_num = c_num * 26 + (ord(c.upper()) - ord('A') + 1)
                        max_c = max(max_c, c_num)
                        
                        t_type = cell.attrib.get('t')
                        v_el = cell.find('ns:v', ns)
                        val = v_el.text if v_el is not None else None
                        
                        if val is not None:
                            if t_type == 's':
                                try:
                                    val = shared_strings[int(val)]
                                except Exception:
                                    pass
                            cells_data[(r_num, c_num)] = str(val)
                            
                total_rows += max_r
                
                # Construct raw_matrix
                raw_matrix = []
                for r in range(1, max_r + 1):
                    row_data = []
                    c = 1
                    while c <= max_c:
                        pos = (r, c)
                        if pos in slave_positions:
                            is_horiz_slave = False
                            for mc_col in range(1, c):
                                if (r, mc_col) in master_info:
                                    cs_width, rs_height = master_info[(r, mc_col)]
                                    if cs_width > (c - mc_col):
                                        is_horiz_slave = True
                                        break
                            if not is_horiz_slave:
                                row_data.append({"text": "", "colspan": 1, "rowspan": 1})
                            c += 1
                            continue
                            
                        val = cells_data.get(pos, "")
                        if pos in master_info:
                            cs, rs = master_info[pos]
                            row_data.append({"text": val, "colspan": cs, "rowspan": rs})
                            c += cs
                        else:
                            row_data.append({"text": val, "colspan": 1, "rowspan": 1})
                            c += 1
                            
                    if any(item.get("text") for item in row_data):
                        raw_matrix.append(row_data)
                        
                if not raw_matrix:
                    continue
                    
                norm_rows = normalize_matrix({"raw_matrix": raw_matrix})
                enriched = enrich_and_validate(norm_rows)
                for row_dict in enriched:
                    t = row_dict["textualization"].strip()
                    if t:
                        text_chunks.append(t)
            except Exception as e:
                text_chunks.append(f"Ошибка парсинга листа {sf}: {e}")
                
        text = "\n\n".join(text_chunks)
        return text, {"sheets": list(file_to_name.values()), "rows": total_rows, "method": "zipfile_xml_merged"}


# ─── main entry point ─────────────────────────────────────────────────────────

def parse(path: Path) -> ParsedDocument:
    try:
        created_at, modified_at = _timestamps(path)
    except Exception as e:
        return ParsedDocument(
            source_path=str(path), file_name=path.name,
            format=path.suffix.lower().strip("."),
            text="", created_at="", modified_at="", extra={"error": str(e)},
        )

    fmt = path.suffix.lower().strip(".")
    try:
        if fmt == "docx":
            text, extra = _parse_docx(path)
        elif fmt in ("xls", "xlsx"):
            text, extra = _parse_xlsx(path)
        else:
            text, extra = "", {"error": f"Unsupported format: {fmt}"}
    except Exception as e:
        text, extra = "", {"error": str(e)}

    return ParsedDocument(
        source_path=str(path), file_name=path.name, format=fmt,
        text=text, created_at=created_at, modified_at=modified_at, extra=extra,
    )
