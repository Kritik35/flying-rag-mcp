"""Тесты парсеров Flying RAG MCP."""
import sys, os, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("legacy script smoke test; run with python test_parsers.py")

passed = failed = 0

def ok(name):
    global passed
    passed += 1
    print(f"  ✅ {name}")

def fail(name, e):
    global failed
    failed += 1
    print(f"  ❌ {name}: {e}")


# ── 1. text.py ──────────────────────────────────────────────────────────────
print("\n=== 1. parsers/text.py ===")
try:
    from parsers.text import parse as parse_text
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# Заголовок\n\nТекст параграфа.")
        tmp = f.name
    try:
        doc = parse_text(Path(tmp))
        assert "Заголовок" in doc.text
        assert doc.format == "md"
        assert "headings" in doc.extra
        ok("parse .md → text + headings")
    finally:
        os.unlink(tmp)
except Exception as e:
    fail("parse .md", e)

try:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def hello():\n    pass\nclass Foo:\n    pass\n")
        tmp = f.name
    try:
        doc = parse_text(Path(tmp))
        assert doc.extra.get("functions", 0) >= 1
        assert doc.extra.get("classes", 0) >= 1
        ok("parse .py → ast stats")
    finally:
        os.unlink(tmp)
except Exception as e:
    fail("parse .py ast", e)


# ── 2. office.py ────────────────────────────────────────────────────────────
print("\n=== 2. parsers/office.py ===")
try:
    import parsers.office
    ok("office.py import OK")
except Exception as e:
    fail("office.py import", e)


# ── 3. data.py ──────────────────────────────────────────────────────────────
print("\n=== 3. parsers/data.py ===")
try:
    from parsers.data import parse as parse_data
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write('{"name": "СП 7.13130", "year": 2013}')
        tmp = f.name
    try:
        doc = parse_data(Path(tmp))
        assert "name" in doc.text
        assert doc.format == "json"
        ok("parse .json → text with keys")
    finally:
        os.unlink(tmp)
except Exception as e:
    fail("parse .json", e)

try:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write("нарм,значение\nСП 7,пожарная")
        tmp = f.name
    try:
        doc = parse_data(Path(tmp))
        assert doc.format == "csv"
        assert doc.extra.get("rows", 0) >= 1
        ok("parse .csv → rows + columns")
    finally:
        os.unlink(tmp)
except Exception as e:
    fail("parse .csv", e)


# ── 4. dispatcher.py ────────────────────────────────────────────────────────
print("\n=== 4. parsers/dispatcher.py ===")
try:
    from parsers.dispatcher import get_parser, should_defer

    # get_parser принимает Path — создаём фиктивный Path с нужным суффиксом
    for ext in [".txt", ".pdf", ".json", ".docx", ".ifc"]:
        p = Path(f"dummy{ext}")
        parser = get_parser(p)
        assert parser is not None, f"get_parser({ext}) вернул None"
    ok("get_parser для txt/pdf/json/docx/ifc → не None")

    assert should_defer(Path("big_file.pdf")) is True
    assert should_defer(Path("notes.txt")) is False
    ok("should_defer: pdf=True, txt=False")
except Exception as e:
    fail("dispatcher", e)


# ── 5. watcher/queue.py ─────────────────────────────────────────────────────
print("\n=== 5. watcher/queue.py ===")
try:
    from watcher.queue import IndexQueue, IndexTask, Priority
    q = IndexQueue()
    q.push(IndexTask(Priority.IMMEDIATE, Path("a.txt"), "index"))
    q.push(IndexTask(Priority.DEFERRED, Path("b.pdf"), "index"))
    assert q.size() == 2
    task = q.pop_immediate()
    assert task is not None and task.path.name == "a.txt"
    deferred = q.pop_all_deferred()
    assert len(deferred) == 1 and deferred[0].path.name == "b.pdf"
    ok("queue push/pop_immediate/pop_all_deferred")
except Exception as e:
    fail("queue", e)


# ── 6. chunker/code.py ──────────────────────────────────────────────────────
print("\n=== 6. chunker/code.py ===")
try:
    from chunker.code import chunk_code
    tmp = Path(tempfile.mktemp(suffix=".py"))
    # Файл достаточно большой чтобы гарантировать AST-разбивку
    big_src = "\n\n".join([f"def func_{i}():\n    '''doc'''\n    return {i}\n" for i in range(30)])
    big_src += "\n\nclass MyClass:\n    def method(self): pass\n"
    tmp.write_text(big_src, encoding="utf-8")
    try:
        from parsers.text import parse as parse_text
        doc = parse_text(tmp)
        chunks = chunk_code(doc)
        assert len(chunks) > 1, f"expected >1 chunks, got {len(chunks)}"
        sections = [c.metadata.get("section", "") for c in chunks]
        assert any("def" in s or "class" in s for s in sections), f"no def/class in {sections[:3]}"
        ok(f"chunk_code: {len(chunks)} чанков, секции найдены")
    finally:
        try: os.unlink(tmp)
        except OSError: pass
except Exception as e:
    fail("chunk_code", e)


# ── 7. storage/graph.py ──────────────────────────────────────────────────────
print("\n=== 7. storage/graph.py ===")
try:
    from storage.graph import init_graph, get_neighbors, get_graph_stats
    import tempfile as _tf
    tmp_db = Path(_tf.mktemp(suffix=".db"))
    try:
        init_graph(tmp_db)
        stats = get_graph_stats(tmp_db)
        assert stats["edges"] == 0
        neighbors = get_neighbors(tmp_db, "abc12345", top_k=5)
        assert neighbors == []
        ok("graph init + get_neighbors пустой граф")
    finally:
        try: os.unlink(tmp_db)
        except OSError: pass
except Exception as e:
    fail("storage/graph", e)


# ── Итог ────────────────────────────────────────────────────────────────────
print(f"\n{'='*40}")
print(f"ИТОГ: {passed} passed, {failed} failed")
if failed == 0:
    print("✅ Все тесты прошли!")
else:
    print("❌ Есть ошибки")
    sys.exit(1)
