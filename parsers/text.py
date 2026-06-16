from __future__ import annotations
import ast
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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1251")


def _timestamps(path: Path) -> tuple[str, str]:
    stat = path.stat()
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return fmt(stat.st_ctime), fmt(stat.st_mtime)


def _md_headings(text: str) -> list[str]:
    headings = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            headings.append(line.lstrip("#").strip())
    return headings


def _py_stats(path: Path) -> dict:
    try:
        content = _read_text(path)
        tree = ast.parse(content)
        funcs = sum(1 for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
        classes = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
        return {"functions": funcs, "classes": classes}
    except Exception:
        return {"functions": 0, "classes": 0}


def parse(path: Path) -> ParsedDocument:
    text = _read_text(path)
    c_time, m_time = _timestamps(path)
    ext = path.suffix.lstrip(".").lower()
    extra: dict = {}
    if ext == "md":
        extra = {"headings": _md_headings(text)}
    elif ext == "py":
        extra = _py_stats(path)
    return ParsedDocument(
        source_path=str(path.resolve()),
        file_name=path.name,
        format=ext,
        text=text,
        created_at=c_time,
        modified_at=m_time,
        extra=extra,
    )


if __name__ == "__main__":
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", encoding="utf-8", delete=False) as f:
        f.write("# Title\n## Sub\ntext")
        p = Path(f.name)
    d = parse(p); os.unlink(p)
    assert d.format == "md" and len(d.extra["headings"]) == 2
    print("OK MD:", d.extra["headings"])
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write("def foo(): pass\nclass Bar: pass")
        p = Path(f.name)
    d = parse(p); os.unlink(p)
    assert d.extra["functions"] == 1 and d.extra["classes"] == 1
    print("OK PY:", d.extra)
    print("ALL TESTS PASSED")
