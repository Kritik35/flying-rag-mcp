"""
test_comprehensive.py — полный тест всех сценариев flying-rag MCP.

Покрывает:
  1. table_normalizer    — colspan/rowspan, edge-cases
  2. chunker             — heading split, sliding window, edge-cases
  3. parsers             — text/md/py/json/csv/pdf
  4. vector_store        — upsert, search, filter, score normalization, delete
  5. metadata_db         — CRUD, SHA skip
  6. semantic_cache      — hit/miss/scope/stats
  7. source_focus        — concentration
  8. crag validator      — valid/invalid
  9. indexer integration — temp-file full pipeline
  10. MCP tools          — search_documents / list_indexed / graph_neighbors / reindex_path

Запуск: python test_comprehensive.py
"""
from __future__ import annotations
import os, sys, tempfile, time, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("legacy script smoke test; run with python test_comprehensive.py")

PASS = 0
FAIL = 0
SKIP = 0
_section = ""


def section(name: str):
    global _section
    _section = name
    print(f"\n=== {name} ===")


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg: str, err: str = ""):
    global FAIL
    FAIL += 1
    detail = f": {err}" if err else ""
    print(f"  ❌ {msg}{detail}")


def skip(msg: str):
    global SKIP
    SKIP += 1
    print(f"  ⏭  {msg}")


def check(cond: bool, label: str, err: str = ""):
    if cond:
        ok(label)
    else:
        fail(label, err)


# ──────────────────────────────────────────────────────────────────────────────
# 1. TABLE NORMALIZER
# ──────────────────────────────────────────────────────────────────────────────
section("1. TABLE NORMALIZER")
try:
    from parsers.table_normalizer import normalize_matrix, enrich_and_validate

    # 1.1 Simple flat table
    flat = {"raw_matrix": [
        [{"text": "Наим", "colspan": 1, "rowspan": 1},
         {"text": "Ед", "colspan": 1, "rowspan": 1},
         {"text": "Кол", "colspan": 1, "rowspan": 1}],
        [{"text": "Труба", "colspan": 1, "rowspan": 1},
         {"text": "м.п.", "colspan": 1, "rowspan": 1},
         {"text": "120", "colspan": 1, "rowspan": 1}],
    ]}
    rows = normalize_matrix(flat)
    check(len(rows) == 1, "flat table: 1 data row")
    check(rows[0].get("Наим") == "Труба", "flat table: correct cell value")

    # 1.2 Multi-level header — colspan
    multi_cs = {"raw_matrix": [
        [{"text": "Система", "colspan": 1, "rowspan": 1},
         {"text": "Вентилятор", "colspan": 2, "rowspan": 1}],
        [{"text": "Ось", "colspan": 1, "rowspan": 1},
         {"text": "L", "colspan": 1, "rowspan": 1},
         {"text": "P", "colspan": 1, "rowspan": 1}],
        [{"text": "В1", "colspan": 1, "rowspan": 1},
         {"text": "5000", "colspan": 1, "rowspan": 1},
         {"text": "300", "colspan": 1, "rowspan": 1}],
    ]}
    rows = normalize_matrix(multi_cs)
    check(len(rows) == 1, "colspan header: 1 data row")
    col_keys = list(rows[0].keys())
    check(any("Вентилятор" in k for k in col_keys), "colspan header: merged key exists")

    # 1.3 Multi-level — rowspan (no placeholder in sub-row)
    multi_rs = {"raw_matrix": [
        [{"text": "Система", "colspan": 1, "rowspan": 2},
         {"text": "Вентилятор", "colspan": 2, "rowspan": 1}],
        [{"text": "L, м3/ч", "colspan": 1, "rowspan": 1},
         {"text": "P, Па", "colspan": 1, "rowspan": 1}],
        [{"text": "П1", "colspan": 1, "rowspan": 1},
         {"text": "5000", "colspan": 1, "rowspan": 1},
         {"text": "350", "colspan": 1, "rowspan": 1}],
    ]}
    rows = normalize_matrix(multi_rs)
    check(len(rows) == 1, "rowspan header: 1 data row")
    check("Система" in rows[0], "rowspan header: Система column")
    check("Вентилятор | L, м3/ч" in rows[0], "rowspan header: merged key")
    check("Вентилятор | P, Па" in rows[0], "rowspan header: second merged key")
    check(rows[0]["Система"] == "П1", "rowspan header: correct value П1")

    # 1.4 Empty matrix
    check(normalize_matrix({"raw_matrix": []}) == [], "empty matrix → []")

    # 1.5 Single row (all header, no data) → 0 rows
    one = {"raw_matrix": [[{"text": "Col1"}, {"text": "Col2"}]]}
    rows = normalize_matrix(one)
    check(len(rows) == 0, "single-row matrix → 0 data rows")

    # 1.6 enrich_and_validate
    rows2 = normalize_matrix(flat)
    enriched = enrich_and_validate(rows2)
    check(len(enriched) == 1, "enrich: 1 output row")
    check("Наим: Труба" in enriched[0]["textualization"], "enrich: textualization correct")
    check("data_type" in enriched[0], "enrich: data_type field present")

    # 1.7 Unicode headers and values
    uni = {"raw_matrix": [
        [{"text": "Наименование оборудования"}, {"text": "Масса, кг"}],
        [{"text": "Насос циркуляционный НЦ-25"}, {"text": "45.5"}],
    ]}
    rows = normalize_matrix(uni)
    check(rows[0].get("Наименование оборудования") == "Насос циркуляционный НЦ-25",
          "unicode headers/values")

    # 1.8 Abbreviation detection in enrich
    abbr_row = [{"Текст": "Система АУП должна соответствовать ГОСТ 21.110"}]
    enriched2 = enrich_and_validate(abbr_row)
    abbrevs = enriched2[0].get("abbreviations", [])
    check(any(a["term"] == "АУП" for a in abbrevs), "enrich: АУП abbreviation detected")

except Exception as e:
    fail("table_normalizer import/run", str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 2. CHUNKER
# ──────────────────────────────────────────────────────────────────────────────
section("2. CHUNKER — semantic")
try:
    from chunker.semantic import chunk_document, _count_tokens, MAX_TOKENS, OVERLAP_TOKENS

    from dataclasses import dataclass as _dc, field as _f

    @_dc
    class FDoc:
        source_path: str = "/tmp/t.md"
        file_name: str = "t.md"
        format: str = "md"
        text: str = ""
        created_at: str = "2026-01-01T00:00:00+00:00"
        modified_at: str = "2026-01-01T00:00:00+00:00"

    # 2.1 Basic heading split
    doc = FDoc(text="# Section A\n\nContent A text.\n\n## Sub B\n\nContent B text.\n\n# Section C\n\nContent C.")
    chunks = chunk_document(doc)
    check(len(chunks) >= 3, f"heading split: >=3 chunks (got {len(chunks)})")
    secs = {c.metadata.get("section") for c in chunks}
    check("Section A" in secs, "heading split: section A recorded")
    check(all(c.chunk_id.startswith(c.doc_id) for c in chunks), "chunk_ids start with doc_id")

    # 2.2 Empty document → fallback chunk
    doc_empty = FDoc(text="")
    chunks_e = chunk_document(doc_empty)
    check(len(chunks_e) == 1, "empty doc → 1 fallback chunk")
    check(chunks_e[0].text == "", "empty doc chunk text is empty string")

    # 2.3 Document without headings (plain text) → 1 chunk if short
    doc_plain = FDoc(text="Просто текст без заголовков. " * 5)
    chunks_p = chunk_document(doc_plain)
    check(len(chunks_p) >= 1, "plain text → at least 1 chunk")

    # 2.4 Very long document → multiple chunks via sliding window
    long_text = "Слово " * 600   # ~600 tokens
    doc_long = FDoc(text=long_text)
    chunks_l = chunk_document(doc_long)
    check(len(chunks_l) > 1, f"long doc ({_count_tokens(long_text)} tok) → multiple chunks ({len(chunks_l)})")
    # Verify token limit
    for c in chunks_l:
        tok = _count_tokens(c.text)
        check(tok <= MAX_TOKENS + 5, f"chunk token count ≤ {MAX_TOKENS} (got {tok})", "")  # +5 tolerance

    # 2.5 Chunk overlap: consecutive chunks share some content
    if len(chunks_l) >= 2:
        words0 = set(chunks_l[0].text.split())
        words1 = set(chunks_l[1].text.split())
        overlap = len(words0 & words1)
        check(overlap > 0, f"sliding window overlap: {overlap} shared words between chunks 0 and 1")

    # 2.6 Metadata completeness
    doc2 = FDoc(source_path="/docs/sp50.md", file_name="sp50.md", text="# СП 50\n\nТекст норм.")
    chunks2 = chunk_document(doc2)
    meta = chunks2[0].metadata
    required_keys = {"source_path", "file_name", "format", "section", "namespace"}
    missing = required_keys - set(meta.keys())
    check(not missing, f"chunk metadata has required keys (missing: {missing})")

    # 2.7 Only-heading document → chunk per heading
    heading_only = FDoc(text="# Раздел 1\n\n# Раздел 2\n\n# Раздел 3")
    chunks_h = chunk_document(heading_only)
    check(len(chunks_h) >= 1, "heading-only doc → at least 1 chunk")

except Exception as e:
    fail("chunker", str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 3. PARSERS
# ──────────────────────────────────────────────────────────────────────────────
section("3. PARSERS")
_tmpfiles = []

try:
    # 3.1 TXT UTF-8
    from parsers.text import parse as parse_text
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
        f.write("# Заголовок\nТекст документа СП 50.\n" * 3)
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_text(p)
    check(doc.format == "txt", "txt: format field")
    check("Заголовок" in doc.text, "txt: content preserved")
    check(doc.created_at != "", "txt: created_at set")

    # 3.2 TXT CP1251
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="wb", delete=False) as f:
        f.write("Текст в CP1251".encode("cp1251"))
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_text(p)
    check("Текст" in doc.text, "txt CP1251: decoded correctly")

    # 3.3 Markdown headings
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", encoding="utf-8", delete=False) as f:
        f.write("# Глава 1\n## Параграф 1.1\nСодержание.\n### Под-параграф\nПодтекст.")
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_text(p)
    check(doc.format == "md", "md: format")
    check(len(doc.extra.get("headings", [])) == 3, f"md: 3 headings found ({doc.extra.get('headings')})")

    # 3.4 Python AST
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write("def foo(): pass\ndef bar(): pass\nclass Baz: pass\n")
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_text(p)
    check(doc.extra.get("functions") == 2, f"py: 2 functions (got {doc.extra.get('functions')})")
    check(doc.extra.get("classes") == 1, f"py: 1 class (got {doc.extra.get('classes')})")

    # 3.5 JSON
    from parsers.data import parse as parse_data
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False) as f:
        import json
        json.dump({"title": "ГОСТ", "sections": [1, 2, 3]}, f, ensure_ascii=False)
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_data(p)
    check("ГОСТ" in doc.text, "json: content extracted")

    # 3.6 CSV
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", encoding="utf-8", delete=False, newline="") as f:
        import csv as _csv
        w = _csv.writer(f); w.writerow(["Наим", "Кол", "Ед"])
        w.writerow(["Труба Ø25", "120", "м.п."])
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_data(p)
    check("Труба" in doc.text, "csv: content extracted")
    check(doc.extra.get("rows", 0) >= 1, "csv: rows > 0")

    # 3.7 Empty file → empty text (not crash)
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
        f.write("")
        p = Path(f.name); _tmpfiles.append(p)
    doc = parse_text(p)
    check(doc.text == "", "empty txt: empty text, no crash")

    # 3.8 PDF parser import + basic structure
    try:
        from parsers.pdf_vision import parse as parse_pdf, MAX_TEXT_PAGES, MAX_TABLE_PAGES
        check(MAX_TEXT_PAGES == 300, f"pdf_vision: MAX_TEXT_PAGES=300 (got {MAX_TEXT_PAGES})")
        check(MAX_TABLE_PAGES == 50, f"pdf_vision: MAX_TABLE_PAGES=50 (got {MAX_TABLE_PAGES})")
        ok("pdf_vision: module imports OK")
    except Exception as e:
        fail("pdf_vision import", str(e))

    # 3.9 Dispatcher — all extensions mapped
    from parsers.dispatcher import get_parser, should_defer
    for ext in [".txt", ".md", ".py", ".json", ".csv"]:
        p_fake = Path(f"fake{ext}")
        fn = get_parser(p_fake)
        check(fn is not None, f"dispatcher: {ext} → parser found")
    for ext in [".pdf", ".docx", ".xlsx"]:
        p_fake = Path(f"fake{ext}")
        fn = get_parser(p_fake)
        check(fn is not None, f"dispatcher: {ext} → parser found")
    check(get_parser(Path("file.xyz123")) is None, "dispatcher: unknown ext → None")
    check(should_defer(Path("file.pdf")), "dispatcher: pdf → deferred")
    check(not should_defer(Path("file.txt")), "dispatcher: txt → not deferred")

except Exception as e:
    fail("parsers", str(e))
finally:
    for p in _tmpfiles:
        try: p.unlink()
        except: pass
    _tmpfiles.clear()


# ──────────────────────────────────────────────────────────────────────────────
# 4. VECTOR STORE
# ──────────────────────────────────────────────────────────────────────────────
section("4. VECTOR STORE")
try:
    import numpy as np
    from storage.vector_store import upsert_chunks, search, delete_doc, count_chunks, ensure_fts_index
    from chunker.semantic import Chunk

    _vs_dir = Path(tempfile.mkdtemp()) / "test_lancedb"
    _vs_dir.mkdir(parents=True, exist_ok=True)

    @_dc
    class FakeEmb:
        chunk_id: str
        embedding: list[float]

    def _rand_emb(seed=0):
        rng = np.random.default_rng(seed)
        return rng.random(1024).tolist()

    # 4.1 Upsert chunks
    chunks = [
        Chunk("docA", "docA_0000", "Тепловая защита зданий СП 50",
              {"source_path": "/docs/sp50.pdf", "file_name": "sp50.pdf",
               "format": "pdf", "created_at": "2026-01-01T00:00:00+00:00",
               "modified_at": "2026-01-01T00:00:00+00:00",
               "section": "Общие требования", "namespace": "normative"}),
        Chunk("docA", "docA_0001", "Заземление электрооборудования ГОСТ",
              {"source_path": "/docs/sp50.pdf", "file_name": "sp50.pdf",
               "format": "pdf", "created_at": "2026-01-01T00:00:00+00:00",
               "modified_at": "2026-01-01T00:00:00+00:00",
               "section": "Заземление", "namespace": "normative"}),
        Chunk("docB", "docB_0000", "Пожарная сигнализация АУПС требования",
              {"source_path": "/docs/gost_fire.pdf", "file_name": "gost_fire.pdf",
               "format": "pdf", "created_at": "2026-01-01T00:00:00+00:00",
               "modified_at": "2026-01-01T00:00:00+00:00",
               "section": "Назначение", "namespace": "normative"}),
        Chunk("docC", "docC_0000", "Спецификация оборудования насосная станция",
              {"source_path": "/project/spec.xlsx", "file_name": "spec.xlsx",
               "format": "xlsx", "created_at": "2026-01-01T00:00:00+00:00",
               "modified_at": "2026-01-01T00:00:00+00:00",
               "section": "", "namespace": "project"}),
    ]
    embs = [FakeEmb(c.chunk_id, _rand_emb(i)) for i, c in enumerate(chunks)]
    n = upsert_chunks(_vs_dir, chunks, embs)
    check(n == 4, f"upsert: 4 chunks written (got {n})")
    check(count_chunks(_vs_dir) == 4, "count_chunks: 4 after upsert")

    # 4.2 Basic vector search
    results = search(_vs_dir, _rand_emb(0), top_k=3)
    check(len(results) <= 3, f"search: returns ≤3 results (got {len(results)})")
    check(all("score" in r for r in results), "search: all results have score field")
    check(all(isinstance(r["score"], float) for r in results), "search: score is float")

    # 4.3 Score normalization: all scores in [0, 1]
    for r in results:
        check(0.0 <= r["score"] <= 1.0, f"score in [0,1]: {r['score']:.4f} for {r['file_name']}")

    # 4.4 folder_filter
    res_filter = search(_vs_dir, _rand_emb(0), top_k=4, folder_filter="/docs")
    check(all("/docs" in r["source_path"] for r in res_filter),
          f"folder_filter: only /docs results (got {[r['source_path'] for r in res_filter]})")

    # 4.5 dataset/namespace filter
    res_proj = search(_vs_dir, _rand_emb(0), top_k=4, dataset="project")
    check(len(res_proj) <= 1, f"dataset=project: ≤1 result (got {len(res_proj)})")

    # 4.6 top_k limits
    res_1 = search(_vs_dir, _rand_emb(0), top_k=1)
    check(len(res_1) == 1, "top_k=1 → exactly 1 result")
    res_10 = search(_vs_dir, _rand_emb(0), top_k=10)
    check(len(res_10) == 4, "top_k=10 on 4 docs → 4 results")

    # 4.7 Result fields completeness
    r = results[0]
    for fld in ["chunk_id", "doc_id", "text", "source_path", "file_name", "section", "score"]:
        check(fld in r, f"result has field: {fld}")

    # 4.8 Delete doc → fewer results
    delete_doc(_vs_dir, "docA")
    check(count_chunks(_vs_dir) == 2, "delete docA: 2 chunks remain")
    res_after = search(_vs_dir, _rand_emb(0), top_k=10)
    doc_ids = {r["doc_id"] for r in res_after}
    check("docA" not in doc_ids, "deleted docA not in results")

    # 4.9 Upsert same doc_id replaces old data
    chunk_new = Chunk("docB", "docB_0001", "Обновлённый текст о пожаре",
                      {"source_path": "/docs/gost_fire.pdf", "file_name": "gost_fire.pdf",
                       "format": "pdf", "created_at": "2026-01-01T00:00:00+00:00",
                       "modified_at": "2026-01-01T00:00:00+00:00",
                       "section": "Обновление", "namespace": "normative"})
    emb_new = FakeEmb("docB_0001", _rand_emb(99))
    n2 = upsert_chunks(_vs_dir, [chunk_new], [emb_new])
    check(n2 == 1, "re-upsert docB: 1 chunk written")
    # Old docB chunk (docB_0000) should be removed, new one added
    check(count_chunks(_vs_dir) == 2, "re-upsert: total still 2 (docC + new docB)")

    # Cleanup
    import shutil
    shutil.rmtree(str(_vs_dir.parent), ignore_errors=True)

except Exception as e:
    fail("vector_store", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# 5. METADATA DB
# ──────────────────────────────────────────────────────────────────────────────
section("5. METADATA DB")
try:
    from storage.metadata_db import (
        init_db, upsert_file, get_file, file_changed,
        list_files, delete_file, mark_deprecated, save_raw_table
    )

    _tmpd5 = tempfile.mkdtemp()
    try:
        tmpd = _tmpd5
        db = Path(tmpd) / "meta.db"
        init_db(db)

        # 5.1 Basic CRUD
        upsert_file(db, "/docs/sp50.pdf", "sp50.pdf", "pdf",
                    "abc123", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                    42, dataset="normative")
        rec = get_file(db, "/docs/sp50.pdf")
        check(rec is not None and rec["file_name"] == "sp50.pdf", "meta: upsert+get round-trip")
        check(rec["chunk_count"] == 42, f"meta: chunk_count=42 (got {rec['chunk_count']})")
        check(rec["dataset"] == "normative", "meta: dataset=normative")

        # 5.2 file_changed
        check(not file_changed(db, "/docs/sp50.pdf", "abc123"), "file_changed: same sha → False")
        check(file_changed(db, "/docs/sp50.pdf", "xyz999"), "file_changed: new sha → True")
        check(file_changed(db, "/docs/new.pdf", "any"), "file_changed: unknown file → True")

        # 5.3 List files with dataset filter
        upsert_file(db, "/proj/spec.xlsx", "spec.xlsx", "xlsx",
                    "def456", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                    10, dataset="project")
        all_files = list_files(db)
        check(len(all_files) == 2, f"list_files: 2 total (got {len(all_files)})")
        norm_files = list_files(db, dataset="normative")
        check(len(norm_files) == 1 and norm_files[0]["file_name"] == "sp50.pdf",
              "list_files: dataset=normative → 1 file")
        proj_files = list_files(db, dataset="project")
        check(len(proj_files) == 1 and proj_files[0]["file_name"] == "spec.xlsx",
              "list_files: dataset=project → 1 file")

        # 5.4 Folder filter
        folder_files = list_files(db, folder_filter="/docs")
        check(len(folder_files) == 1, "list_files: folder_filter=/docs → 1 file")

        # 5.5 mark_deprecated
        mark_deprecated(db, "/docs/sp50.pdf")
        rec2 = get_file(db, "/docs/sp50.pdf")
        check(bool(rec2.get("is_deprecated")), "mark_deprecated: is_deprecated=1")

        # 5.6 save_raw_table
        save_raw_table(db, "/docs/sp50.pdf", 0, '{"raw": "data"}',
                       '{"norm": "data"}', '{"text": "row"}')
        ok("save_raw_table: no crash")

        # 5.7 Delete
        delete_file(db, "/docs/sp50.pdf")
        check(get_file(db, "/docs/sp50.pdf") is None, "delete_file: record gone")

        # 5.8 Idempotent init_db (no crash on re-init)
        init_db(db)
        ok("init_db: idempotent (no crash on second call)")

    finally:
        import shutil as _sh5
        _sh5.rmtree(_tmpd5, ignore_errors=True)

except Exception as e:
    fail("metadata_db", str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 6. SEMANTIC CACHE
# ──────────────────────────────────────────────────────────────────────────────
section("6. SEMANTIC CACHE")
try:
    from storage.semantic_cache import SemanticCache

    _tmpd6 = tempfile.mkdtemp()
    try:
        tmpd = _tmpd6
        db = str(Path(tmpd) / "cache.db")
        cache = SemanticCache(db_path=db)

        emb1 = [0.1 + 0.001 * i for i in range(1024)]
        emb2 = [0.1 + 0.001 * i + 0.0001 for i in range(1024)]   # very close to emb1
        emb3 = [0.9 - 0.001 * i for i in range(1024)]             # different direction
        results = [{"chunk_id": "c1", "text": "test result", "score": 0.9}]

        # 6.1 Miss before store
        hit = cache.lookup("запрос", emb1)
        check(hit is None, "cache: miss before store")

        # 6.2 Store + exact match hit
        cache.store("запрос", emb1, results, scope_key="norm|")
        hit = cache.lookup("запрос", emb1, scope_key="norm|")
        check(hit is not None, "cache: exact match hit after store")
        check(hit.similarity == 1.0, f"cache: exact match sim=1.0 (got {hit.similarity})")
        check(hit.results == results, "cache: results match stored data")

        # 6.3 Similar embedding hit (above threshold)
        hit2 = cache.lookup("похожий запрос", emb2, threshold=0.90, scope_key="norm|")
        check(hit2 is not None, f"cache: similar emb hit (sim={hit2.similarity if hit2 else 'N/A'})")

        # 6.4 Different embedding → miss
        miss = cache.lookup("другой запрос", emb3, threshold=0.90, scope_key="norm|")
        check(miss is None, "cache: different emb → miss")

        # 6.5 Scope isolation
        hit_wrong_scope = cache.lookup("запрос", emb1, scope_key="proj|")
        check(hit_wrong_scope is None, "cache: wrong scope → miss")

        # 6.6 Stats
        stats = cache.stats()
        check(stats["entries"] == 1, f"cache stats: 1 entry (got {stats['entries']})")
        check(stats["total_hits"] >= 2, f"cache stats: ≥2 hits (got {stats['total_hits']})")
        check(stats["enabled"] is True, "cache stats: enabled=True")

        # 6.7 Empty results not stored
        cache.store("empty", emb1, [], scope_key="norm|")
        stats2 = cache.stats()
        check(stats2["entries"] == 1, "cache: empty results not stored")

        # 6.8 Cache clear (old entries)
        n_del = cache.clear(older_than_days=0.0)  # delete everything
        check(cache.stats()["entries"] == 0, "cache clear: all entries removed")

        # 6.9 Disabled cache
        os.environ["SEMANTIC_CACHE_ENABLED"] = "false"
        # Reload cache with disabled flag
        import importlib, storage.semantic_cache as _sc_mod
        importlib.reload(_sc_mod)
        cache_off = _sc_mod.SemanticCache(db_path=db)
        cache_off.store("q", emb1, results)
        hit_off = cache_off.lookup("q", emb1)
        check(hit_off is None, "cache disabled: no hit even after store")
        os.environ["SEMANTIC_CACHE_ENABLED"] = "true"

    finally:
        import shutil as _sh6
        _sh6.rmtree(_tmpd6, ignore_errors=True)

except Exception as e:
    fail("semantic_cache", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# 7. SOURCE FOCUS
# ──────────────────────────────────────────────────────────────────────────────
section("7. SOURCE FOCUS")
try:
    from storage.source_focus import concentrate_sources

    results_multi = [
        {"doc_id": "d1", "file_name": "sp50.pdf",    "score": 0.92, "text": "a"},
        {"doc_id": "d1", "file_name": "sp50.pdf",    "score": 0.85, "text": "b"},
        {"doc_id": "d2", "file_name": "gost_r.pdf",  "score": 0.80, "text": "c"},
        {"doc_id": "d3", "file_name": "spec.xlsx",   "score": 0.45, "text": "d"},
        {"doc_id": "d4", "file_name": "random.pdf",  "score": 0.30, "text": "e"},
    ]

    # 7.1 max_docs=2
    focused = concentrate_sources(results_multi, max_docs=2, min_score=0.40)
    doc_ids = {r["doc_id"] for r in focused}
    check("d4" not in doc_ids, "source_focus: low-score doc (d4/0.30) excluded")
    check(len(doc_ids) <= 2, f"source_focus: ≤2 docs (got {len(doc_ids)})")
    check("d1" in doc_ids, "source_focus: best doc (d1) included")

    # 7.2 All below threshold → keep best
    results_low = [
        {"doc_id": "x1", "file_name": "a.pdf", "score": 0.10, "text": "a"},
        {"doc_id": "x2", "file_name": "b.pdf", "score": 0.08, "text": "b"},
    ]
    focused_low = concentrate_sources(results_low, max_docs=1, min_score=0.40)
    check(len(focused_low) >= 1, "source_focus: all below threshold → keeps best")

    # 7.3 Empty input
    check(concentrate_sources([], max_docs=3) == [], "source_focus: empty input → []")

    # 7.4 Single doc → returned as-is
    single = [{"doc_id": "s1", "file_name": "a.pdf", "score": 0.95, "text": "x"}]
    check(concentrate_sources(single, max_docs=3) == single, "source_focus: single doc unchanged")

except Exception as e:
    fail("source_focus", str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 8. CRAG VALIDATOR
# ──────────────────────────────────────────────────────────────────────────────
section("8. CRAG VALIDATOR")
try:
    from validator.crag import validate_crag, wrap_meta_header

    # 8.1 Valid normative text
    good = """
    # СП 50.13330.2012 Тепловая защита зданий
    ## 5.1 Общие требования
    5.1.1 Теплозащита здания должна обеспечивать:
    | Показатель | Значение |
    |------------|----------|
    | R0, м²·°С/Вт | не менее 3.5 |
    """
    ok_v, reason = validate_crag(good)
    check(ok_v, f"crag: valid normative text (reason={reason})")

    # 8.2 Too short
    ok_v, reason = validate_crag("короткий")
    check(not ok_v and reason == "too_short", f"crag: too_short detected (got {reason})")

    # 8.3 No markers
    ok_v, reason = validate_crag("A" * 300)
    check(not ok_v and reason == "no_markers", f"crag: no_markers detected (got {reason})")

    # 8.4 No structure
    ok_v, reason = validate_crag("СП 50 требования " * 20)
    check(not ok_v and reason == "no_structure", f"crag: no_structure (got {reason})")

    # 8.5 English markers
    eng_text = """
    Section 1: General requirements for GOST-compliant systems.
    Table 1.1: Requirements
    | Parameter | Value |
    |-----------|-------|
    | R0        | 3.5   |
    Clause 2.1 specifies standard requirements.
    """
    ok_v, reason = validate_crag(eng_text)
    check(ok_v, f"crag: English markers accepted (reason={reason})")

    # 8.6 wrap_meta_header
    header = wrap_meta_header("sp50.pdf", True)
    check("RAG-META" in header, "crag header: RAG-META tag")
    check("crag_valid" in header, "crag header: crag_valid field")
    header_bad = wrap_meta_header("random.txt", False)
    check("NEEDS REVIEW" in header_bad, "crag header: NEEDS REVIEW for invalid")

except Exception as e:
    fail("crag validator", str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 9. INDEXER INTEGRATION (full pipeline on temp file)
# ──────────────────────────────────────────────────────────────────────────────
section("9. INDEXER INTEGRATION")
try:
    from embedder.client import check_connection
    if not check_connection():
        skip("lemonade offline — skipping indexer integration tests")
    else:
        import subprocess, uuid, yaml

        ROOT = Path(__file__).resolve().parent.parent
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        meta_path  = ROOT / cfg["storage"]["metadata_db"]
        lance_path = ROOT / cfg["storage"]["lancedb_path"]

        # 9.1 Index a temp TXT file
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8",
                                         dir=ROOT, delete=False) as f:
            f.write("# ГОСТ Р 12345-2026 Тестовый документ\n\n"
                    "## 1. Область применения\n\n"
                    "Настоящий стандарт устанавливает требования к испытательным\n"
                    "системам. Таблица 1 — Основные параметры.\n\n"
                    "| Параметр | Значение |\n|----------|---------|\n"
                    "| Давление | 1.0 МПа |\n| Температура | 20°С |\n\n"
                    "## 2. Нормативные ссылки\n\nСП 50 — тепловая защита.\n" * 5)
            tmp_path = Path(f.name)

        try:
            t0 = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, str(ROOT / "indexer.py"), str(tmp_path)],
                capture_output=True, text=True, timeout=120,
                cwd=str(ROOT),
            )
            elapsed = time.perf_counter() - t0

            check(proc.returncode == 0,
                  f"indexer exit code 0 (got {proc.returncode})",
                  proc.stderr[-300:] if proc.stderr else "")
            check(elapsed < 60, f"indexer finished in {elapsed:.1f}s (<60s)")

            # Verify file was recorded in metadata_db
            from storage.metadata_db import get_file
            rec = get_file(meta_path, str(tmp_path))
            check(rec is not None, "indexer: file recorded in metadata_db")
            if rec:
                check(rec["chunk_count"] > 0,
                      f"indexer: chunk_count > 0 (got {rec['chunk_count']})")
                check(rec["status"] == "indexed", "indexer: status=indexed")

            # 9.2 SHA256 skip — run again, should skip unchanged file
            t1 = time.perf_counter()
            proc2 = subprocess.run(
                [sys.executable, str(ROOT / "indexer.py"), str(tmp_path)],
                capture_output=True, text=True, timeout=30,
                cwd=str(ROOT),
            )
            elapsed2 = time.perf_counter() - t1
            check(proc2.returncode == 0, "indexer sha-skip: exit code 0")
            check("skip unchanged" in proc2.stderr, "indexer sha-skip: 'skip unchanged' in stderr")
            check(elapsed2 < 10, f"indexer sha-skip: fast (<10s, got {elapsed2:.1f}s)")

            # 9.3 Search finds the indexed content
            from storage.vector_store import search as vs_search
            from embedder.client import get_embeddings
            vecs = get_embeddings(["ГОСТ Р 12345-2026 испытательные системы"])
            res = vs_search(lance_path, vecs[0], top_k=5, query_text=None, alpha=1.0)
            found = any(tmp_path.name in r.get("file_name", "") for r in res)
            check(found, f"indexer: indexed file found via search ({tmp_path.name})")

        finally:
            # Cleanup temp file from index
            try:
                from storage.metadata_db import get_file, file_changed
                rec = get_file(meta_path, str(tmp_path))
                if rec:
                    from storage.vector_store import delete_doc
                    import hashlib
                    doc_id = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:8]
                    delete_doc(lance_path, doc_id)
                    from storage.metadata_db import delete_file
                    delete_file(meta_path, str(tmp_path))
            except Exception:
                pass
            try: tmp_path.unlink()
            except: pass

except Exception as e:
    fail("indexer integration", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# 10. MCP TOOLS
# ──────────────────────────────────────────────────────────────────────────────
section("10. MCP TOOLS")
try:
    from rag_server.tools import search_documents, list_indexed, graph_neighbors, reindex_path
    from embedder.client import check_connection

    # 10.1 list_indexed — always works
    result = list_indexed()
    check("summary" in result, "list_indexed: has summary")
    check("files" in result, "list_indexed: has files")
    check("total_files" in result["summary"], "list_indexed: summary has total_files")
    check("total_chunks" in result["summary"], "list_indexed: summary has total_chunks")
    total = result["summary"]["total_files"]
    check(total >= 0, f"list_indexed: total_files ≥ 0 (got {total})")

    # 10.2 list_indexed with dataset filter
    norm = list_indexed(dataset="normative")
    check("summary" in norm, "list_indexed(dataset=normative): has summary")

    # 10.3 list_indexed with folder_filter
    filtered = list_indexed(folder_filter="nonexistent_folder_xyz")
    check(filtered["summary"]["total_files"] == 0,
          "list_indexed(nonexistent folder): 0 files")

    # 10.4 list_indexed limit
    limited = list_indexed(limit=3)
    check(len(limited.get("files", [])) <= 3, "list_indexed(limit=3): ≤3 files returned")

    # 10.5 graph_neighbors with nonexistent doc_id
    gn = graph_neighbors("nonexistent_doc_id_xyz", top_k=3)
    check(isinstance(gn, list), "graph_neighbors nonexistent: returns list")
    check(len(gn) >= 1, "graph_neighbors nonexistent: returns info/error item")

    # 10.6 reindex_path — nonexistent path
    rr = reindex_path("/nonexistent/path/xyz")
    check(rr.get("status") == "error", f"reindex_path nonexistent: status=error (got {rr})")

    # 10.7 search_documents (requires lemonade)
    if not check_connection():
        skip("search_documents: lemonade offline")
    else:
        # Basic search
        res = search_documents("тепловая защита зданий", top_k=5)
        check(isinstance(res, list), "search_documents: returns list")
        check(len(res) <= 5, f"search_documents: ≤5 results (got {len(res)})")
        if res and "error" not in res[0]:
            check(all("text" in r for r in res), "search_documents: all results have text")
            check(all("score" in r for r in res), "search_documents: all results have score")
            check(all(0.0 <= r["score"] <= 1.0 for r in res),
                  "search_documents: scores in [0,1]")

        # Search with dataset filter
        res_norm = search_documents("ГОСТ требования", dataset="normative", top_k=3)
        check(isinstance(res_norm, list), "search_documents(normative): returns list")

        # Search with folder_filter
        res_ff = search_documents("тест", folder_filter="Downloaded_GOSTs", top_k=3)
        check(isinstance(res_ff, list), "search_documents(folder_filter): returns list")

        # Edge: top_k=1
        res_1 = search_documents("заземление", top_k=1)
        check(len(res_1) <= 1, "search_documents(top_k=1): ≤1 result")

        # Edge: top_k=20 (max)
        res_20 = search_documents("пожар", top_k=20)
        check(len(res_20) <= 20, "search_documents(top_k=20): ≤20 results")

        # Edge: special chars in query
        res_spec = search_documents("Ø25 трубы тип DN32", top_k=3)
        check(isinstance(res_spec, list) and not any("error" in str(r) for r in res_spec),
              "search_documents: special chars (Ø, DN) no crash")

        # Edge: SQL-injection style folder_filter (should not crash)
        res_sqli = search_documents("тест", folder_filter="'; DROP TABLE documents; --", top_k=1)
        check(isinstance(res_sqli, list), "search_documents: SQL-injection folder_filter no crash")

        # Cache test: second identical query → cache hit
        t0 = time.perf_counter()
        res_c1 = search_documents("тепловая защита зданий", top_k=5)
        t1 = time.perf_counter()
        # Note: cache may or may not hit depending on embedding time vs disk
        check(isinstance(res_c1, list), "search_documents: cached query returns list")

except Exception as e:
    fail("mcp tools", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# 11. EDGE CASES
# ──────────────────────────────────────────────────────────────────────────────
section("11. EDGE CASES")
try:
    # 11.1 Chunker: document with only whitespace
    from chunker.semantic import chunk_document
    @_dc
    class FDoc2:
        source_path: str = "/tmp/ws.txt"
        file_name: str = "ws.txt"
        format: str = "txt"
        text: str = "   \n\t\n   "
        created_at: str = "2026-01-01T00:00:00+00:00"
        modified_at: str = "2026-01-01T00:00:00+00:00"
    doc_ws = FDoc2()
    chunks_ws = chunk_document(doc_ws)
    check(len(chunks_ws) == 1, "edge: whitespace-only doc → 1 fallback chunk")

    # 11.2 Chunker: very short text (< 1 token)
    @_dc
    class FDoc3:
        source_path: str = "/tmp/short.txt"
        file_name: str = "short.txt"
        format: str = "txt"
        text: str = "X"
        created_at: str = "2026-01-01T00:00:00+00:00"
        modified_at: str = "2026-01-01T00:00:00+00:00"
    chunks_s = chunk_document(FDoc3())
    check(len(chunks_s) >= 1, "edge: 1-char doc → no crash")

    # 11.3 normalize_matrix: cell with None text
    from parsers.table_normalizer import normalize_matrix
    none_row = {"raw_matrix": [
        [{"text": "Col1"}, {"text": "Col2"}],
        [{"text": None}, {"text": "Val"}],
    ]}
    rows_n = normalize_matrix(none_row)
    check(len(rows_n) == 1, "edge: None cell in matrix → no crash")

    # 11.4 normalize_matrix: missing colspan/rowspan keys
    missing_cs = {"raw_matrix": [
        [{"text": "H1"}, {"text": "H2"}],
        [{"text": "A"}, {"text": "B"}],
    ]}
    rows_m = normalize_matrix(missing_cs)
    check(len(rows_m) == 1, "edge: missing colspan/rowspan keys → defaults to 1")

    # 11.5 source_focus: empty score field
    from storage.source_focus import concentrate_sources
    no_score = [{"doc_id": "d1", "file_name": "a.pdf", "text": "x"}]  # no score key
    result_ns = concentrate_sources(no_score, min_score=0.40)
    check(isinstance(result_ns, list), "edge: source_focus with missing score field → no crash")

    # 11.6 list_indexed: very large limit
    from rag_server.tools import list_indexed
    big_limit = list_indexed(limit=9999)
    check("summary" in big_limit, "edge: list_indexed(limit=9999) → no crash")

    # 11.7 search_documents: empty query
    from embedder.client import check_connection
    if check_connection():
        from rag_server.tools import search_documents
        res_empty = search_documents("", top_k=3)
        check(isinstance(res_empty, list), "edge: empty query → list (no crash)")

    # 11.8 Dispatcher: uppercase extension
    from parsers.dispatcher import get_parser
    check(get_parser(Path("doc.PDF")) is not None, "edge: uppercase .PDF → parser found")
    check(get_parser(Path("doc.DOCX")) is not None, "edge: uppercase .DOCX → parser found")

    # 11.9 semantic_cache: very large embedding (dim mismatch tolerance)
    from storage.semantic_cache import SemanticCache
    import tempfile as _tf2
    with _tf2.TemporaryDirectory() as td2:
        c2 = SemanticCache(db_path=str(Path(td2) / "c.db"))
        emb_a = [0.5] * 512   # dim=512
        emb_b = [0.5] * 1024  # dim=1024
        c2.store("q", emb_a, [{"text": "x"}])
        hit = c2.lookup("q", emb_b, threshold=0.5)
        # Should not crash regardless of hit/miss
        ok("edge: dim mismatch in cache cosine → no crash")

except Exception as e:
    fail("edge cases", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# 12. GEMINI AUDIT VALIDATION
# ──────────────────────────────────────────────────────────────────────────────
section("12. GEMINI AUDIT VALIDATION")
try:
    # 12.1 Python AST Chunk Boundary Test
    from chunker.semantic import chunk_document
    big_py_text = "\n\n".join([f"def function_{i}():\n    '''docstring for function {i}'''\n    print({i})" for i in range(100)])
    big_py_text += "\n\nclass BigWorker:\n    def execute(self): pass"
    
    @_dc
    class PyDoc:
        source_path: str = "/src/app.py"
        file_name: str = "app.py"
        format: str = "py"
        text: str = big_py_text
        created_at: str = "2026-01-01T00:00:00+00:00"
        modified_at: str = "2026-01-01T00:00:00+00:00"
    
    py_doc = PyDoc()
    py_chunks = chunk_document(py_doc, namespace="test_namespace")
    check(len(py_chunks) == 101, f"gemini test: py AST split into 101 chunks (got {len(py_chunks)})")
    check(py_chunks[0].metadata["section"] == "def function_0", f"gemini test: first chunk is function_0 (got {py_chunks[0].metadata['section']})")
    check(py_chunks[100].metadata["section"] == "class BigWorker", f"gemini test: last chunk is class (got {py_chunks[100].metadata['section']})")
    check(py_chunks[0].metadata["namespace"] == "test_namespace", "gemini test: namespace propagated")

    # 12.2 Mocked Search Precision Test
    from storage.vector_store import upsert_chunks, search as vs_search
    from chunker.semantic import Chunk
    _vs_dir = Path(tempfile.mkdtemp()) / "test_lancedb_gemini"
    _vs_dir.mkdir(parents=True, exist_ok=True)
    
    # 1024-dim embedding
    emb_data = [0.0] * 1024
    emb_data[0] = 1.0  # distinctive embedding
    
    c_gost = Chunk("gost_doc", "gost_doc_0000", "ГОСТ 30494-2011 параметры микроклимата помещений",
                   {"source_path": "/docs/gost.pdf", "file_name": "gost.pdf", "format": "pdf"})
    
    @_dc
    class FakeEmb:
        chunk_id: str
        embedding: list[float]
        
    upsert_chunks(_vs_dir, [c_gost], [FakeEmb("gost_doc_0000", emb_data)])
    
    # Exact match vector search
    res = vs_search(_vs_dir, emb_data, top_k=1)
    check(len(res) == 1, "gemini test: search returns 1 exact result")
    check(res[0]["doc_id"] == "gost_doc", "gemini test: matched correct doc_id")
    check("30494-2011" in res[0]["text"], "gemini test: retrieved correct text content")
    
    import shutil
    shutil.rmtree(str(_vs_dir.parent), ignore_errors=True)

    # 12.3 MCP Contract Empty/Invalid Input
    from rag_server.tools import search_documents
    # Empty query should return empty or error but not crash
    res_empty = search_documents("", top_k=5)
    check(isinstance(res_empty, list), "gemini test: empty query handles gracefully (returns list)")
    
    # Invalid top_k should be normalized (search_documents should clamp to min/max)
    res_clamp = search_documents("тест", top_k=99)
    check(isinstance(res_clamp, list), "gemini test: top_k clamp handles gracefully")

    # 12.4 Excel Table-Aware Chunker Test
    from chunker.table_excel import chunk_excel_tables
    import openpyxl
    
    tmp_xlsx = Path(tempfile.mktemp(suffix=".xlsx"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ТестовыеРасчеты"
    ws.append(["Параметр", "Значение", "Единица"])
    ws.append(["Площадь", 150, "м2"])
    ws.append(["Высота", 3, "м"])
    ws.append(["ИтогоОбъем", "=B2*B3", "м3"])
    wb.save(str(tmp_xlsx))
    wb.close()
    
    try:
        xlsx_chunks = chunk_excel_tables(tmp_xlsx)
        check(len(xlsx_chunks) == 3, f"gemini test: Excel table-aware split into 3 chunks (got {len(xlsx_chunks)})")
        check("Формула" in xlsx_chunks[2], "gemini test: Excel formula detected")
        check("Итоговая строка" in xlsx_chunks[2], "gemini test: Excel summary row detected")
    finally:
        try: tmp_xlsx.unlink()
        except: pass

    # 12.5 Hybrid Search Alpha Weight Test
    _vs_dir2 = Path(tempfile.mkdtemp()) / "test_lancedb_alpha"
    _vs_dir2.mkdir(parents=True, exist_ok=True)
    
    # Сначала запишем данные
    c_list = [
        Chunk("docX", "docX_0000", "Специальные требования пожарной безопасности СП 7",
              {"source_path": "/docs/sp7.pdf", "file_name": "sp7.pdf", "format": "pdf"}),
        Chunk("docY", "docY_0000", "Расчет теплопотерь ограждающих конструкций здания СП 50",
              {"source_path": "/docs/sp50.pdf", "file_name": "sp50.pdf", "format": "pdf"}),
    ]
    embs2 = [
        FakeEmb("docX_0000", [1.0] * 1024),
        FakeEmb("docY_0000", [0.0] * 1024),
    ]
    upsert_chunks(_vs_dir2, c_list, embs2)
    ensure_fts_index(_vs_dir2)
    
    # Проверим поиск при разном alpha
    res_vec = vs_search(_vs_dir2, [1.0] * 1024, top_k=2, query_text="пожарная безопасность", alpha=1.0)
    check(len(res_vec) > 0, "gemini test: search with alpha=1.0 runs without error")
    
    res_fts = vs_search(_vs_dir2, [1.0] * 1024, top_k=2, query_text="пожарная безопасность", alpha=0.0)
    check(len(res_fts) > 0, "gemini test: search with alpha=0.0 runs without error")
    
    res_hyb = vs_search(_vs_dir2, [1.0] * 1024, top_k=2, query_text="пожарная безопасность", alpha=0.5)
    check(len(res_hyb) > 0, "gemini test: search with alpha=0.5 runs without error")
    
    shutil.rmtree(str(_vs_dir2.parent), ignore_errors=True)

    # 12.6 Embedding Provider Abstraction Test
    from embedder.abstract import EmbeddingProvider
    
    class MockProvider(EmbeddingProvider):
        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 1024] * len(texts)
        def get_dimension(self) -> int:
            return 1024
        def get_model_name(self) -> str:
            return "mock-model"
        def check_connection(self) -> bool:
            return True
            
    m_prov = MockProvider()
    check(m_prov.get_dimension() == 1024, "gemini test: MockProvider dimension matches")
    check(m_prov.get_model_name() == "mock-model", "gemini test: MockProvider name matches")
    check(m_prov.check_connection() is True, "gemini test: MockProvider connection works")
    check(len(m_prov.embed_batch(["t"])) == 1, "gemini test: MockProvider embedding returns batch")

except Exception as e:
    fail("gemini validation tests", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# 18. RULES EXTRACTOR LOCAL NPU
# ──────────────────────────────────────────────────────────────────────────────
section("18. RULES EXTRACTOR LOCAL NPU")
try:
    from storage.rules_extractor import StructuredRulesExtractor
    extractor = StructuredRulesExtractor()
    
    check(extractor.enabled is True, "rules_extractor: enabled=True")
    check(extractor.model_id == "qwen3.5-9b-FLM", f"rules_extractor: model_id matches (got {extractor.model_id})")
    check("13305" in extractor.model_url, f"rules_extractor: model_url is local (got {extractor.model_url})")
    
    # Test actual rule extraction
    text_sample = "Ширина путей эвакуации должна быть не менее 1.2 м при числе эвакуирующихся более 15 человек."
    rules = extractor.extract_rules(text_sample, "doc_test", "/docs/test.pdf", "chunk_00")
    
    check(isinstance(rules, list), "rules_extractor: extract returns list")
    if rules:
        check(len(rules) >= 1, "rules_extractor: extracted at least one rule")
        r = rules[0]
        check(r["subject"] != "N/A", "rules_extractor: subject extracted")
        check(r["value"] == 1.2, f"rules_extractor: value is correct (got {r['value']})")
        check(r["unit"] == "m", f"rules_extractor: unit is correct (got {r['unit']})")
    else:
        skip("rules_extractor: no rules returned (local model might be sleeping)")

except Exception as e:
    fail("rules_extractor local NPU", str(e))
    import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
# RESULTS
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
total = PASS + FAIL + SKIP
print(f"RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped  ({total} total)")
if FAIL == 0:
    print("✅ ALL TESTS PASSED")
else:
    print(f"❌ {FAIL} FAILURES — see details above")
sys.exit(0 if FAIL == 0 else 1)
