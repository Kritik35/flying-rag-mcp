"""
test_mvp.py — проверка импортов и базовой логики MVP.
Запуск: python test_mvp.py
Не требует lemonade-server или LanceDB данных.
"""
import sys, tempfile, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("legacy script smoke test; run with python test_mvp.py")

PASS = []
FAIL = []

def ok(name): PASS.append(name); print(f"  ✅ {name}")
def fail(name, e): FAIL.append(name); print(f"  ❌ {name}: {e}")


print("\n=== 1. IMPORTS ===")
try:
    from parsers.text import parse as txt_parse, ParsedDocument
    ok("parsers.text")
except Exception as e: fail("parsers.text", e)

try:
    from parsers.pdf import parse as pdf_parse
    ok("parsers.pdf")
except Exception as e: fail("parsers.pdf", e)

try:
    from parsers.dispatcher import get_parser, should_defer
    ok("parsers.dispatcher")
except Exception as e: fail("parsers.dispatcher", e)

try:
    from chunker.semantic import chunk_document, Chunk
    ok("chunker.semantic")
except Exception as e: fail("chunker.semantic", e)

try:
    from validator.crag import validate_crag, wrap_meta_header
    ok("validator.crag")
except Exception as e: fail("validator.crag", e)

try:
    from embedder.client import check_connection, get_embeddings
    ok("embedder.client")
except Exception as e: fail("embedder.client", e)

try:
    from embedder.batcher import embed_chunks, EmbeddingResult
    ok("embedder.batcher")
except Exception as e: fail("embedder.batcher", e)

try:
    from storage.metadata_db import init_db, upsert_file, get_file, file_changed, list_files, delete_file
    ok("storage.metadata_db")
except Exception as e: fail("storage.metadata_db", e)

try:
    from storage.vector_store import upsert_chunks, search, count_chunks
    ok("storage.vector_store")
except Exception as e: fail("storage.vector_store", e)

try:
    from rag_server.tools import get_tool_definitions
    ok("rag_server.tools")
except Exception as e: fail("rag_server.tools", e)


print("\n=== 2. PARSERS LOGIC ===")
try:
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
        f.write("Hello World\nThis is a test.")
        p = Path(f.name)
    doc = txt_parse(p); os.unlink(p)
    assert doc.format == "txt" and "Hello" in doc.text
    ok("parse TXT")
except Exception as e: fail("parse TXT", e)

try:
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", encoding="utf-8", delete=False) as f:
        f.write("# Title\n## Sub\nContent text here.")
        p = Path(f.name)
    doc = txt_parse(p); os.unlink(p)
    assert doc.format == "md" and len(doc.extra.get("headings", [])) == 2
    ok("parse MD headings")
except Exception as e: fail("parse MD headings", e)

try:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write("def foo(): pass\nclass Bar: pass")
        p = Path(f.name)
    doc = txt_parse(p); os.unlink(p)
    assert doc.extra.get("functions") == 1 and doc.extra.get("classes") == 1
    ok("parse PY ast stats")
except Exception as e: fail("parse PY ast stats", e)


print("\n=== 3. CHUNKER ===")
try:
    from dataclasses import dataclass, field as dc_field

    @dataclass
    class FakeDoc:
        source_path: str = "/tmp/test.md"
        file_name: str = "test.md"
        format: str = "md"
        text: str = "# Sec1\n\nContent A.\n\n# Sec2\n\nContent B."
        created_at: str = "2026-01-01T00:00:00+00:00"
        modified_at: str = "2026-01-01T00:00:00+00:00"

    chunks = chunk_document(FakeDoc())
    assert len(chunks) >= 2, f"Expected >=2 chunks, got {len(chunks)}"
    assert all(hasattr(c, "chunk_id") for c in chunks)
    ok(f"chunk_document → {len(chunks)} chunks")
except Exception as e: fail("chunk_document", e)


print("\n=== 4. VALIDATOR ===")
try:
    good = "# СП 50.2012\n\n5.1.1 Требования п.\n\n| Col | Val |\n|-----|-----|\n| A | 1 |\n" * 3
    ok_v, reason = validate_crag(good)
    assert ok_v, f"Expected pass, got {reason}"
    ok(f"validate_crag PASS: {reason}")
except Exception as e: fail("validate_crag PASS", e)

try:
    ok_v, reason = validate_crag("short")
    assert not ok_v and reason == "too_short"
    ok(f"validate_crag REJECT: {reason}")
except Exception as e: fail("validate_crag REJECT", e)


print("\n=== 5. METADATA DB ===")
try:
    import shutil
    tmp_db = Path(tempfile.mktemp(suffix=".db"))
    init_db(tmp_db)
    upsert_file(tmp_db, "/docs/a.txt", "a.txt", "txt", "sha1",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", 3)
    rec = get_file(tmp_db, "/docs/a.txt")
    assert rec and rec["chunk_count"] == 3
    assert file_changed(tmp_db, "/docs/a.txt", "sha1") is False
    assert file_changed(tmp_db, "/docs/a.txt", "sha2") is True
    lst = list_files(tmp_db)
    assert len(lst) == 1
    delete_file(tmp_db, "/docs/a.txt")
    assert get_file(tmp_db, "/docs/a.txt") is None
    try:
        os.unlink(tmp_db)
    except OSError:
        pass
    ok("metadata_db full CRUD")
except Exception as e: fail("metadata_db CRUD", e)


print("\n=== 6. MCP TOOLS DEFINITIONS ===")
try:
    defs = get_tool_definitions()
    names = [d["name"] for d in defs]
    assert "search_documents" in names
    assert "list_indexed" in names
    assert "reindex_path" in names
    ok(f"tool definitions: {names}")
except Exception as e: fail("tool definitions", e)


print("\n=== 7. LEMONADE CONNECTION ===")
try:
    from embedder.client import check_connection
    ok_c = check_connection()
    if ok_c:
        ok("lemonade-server ONLINE")
    else:
        print("  ⚠️  lemonade-server OFFLINE (запусти сервер для тестирования embeddings)")
except Exception as e: fail("lemonade check", e)


print(f"\n{'='*40}")
print(f"РЕЗУЛЬТАТ: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print(f"FAILED: {', '.join(FAIL)}")
    sys.exit(1)
else:
    print("MVP CORE — ALL OK ✅")
