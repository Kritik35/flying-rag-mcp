from __future__ import annotations
import importlib
from pathlib import Path

IMMEDIATE_EXTS = frozenset({".txt", ".md", ".py", ".json", ".csv"})
DEFERRED_EXTS  = frozenset({".pdf", ".docx", ".xlsx", ".xls", ".ifc", ".dwg"})
METADATA_ONLY_EXTS = frozenset({".rvt"})
DEFERRED_SIZE_MB = 10.0

_MAPPING: dict[str, tuple[str, str]] = {
    ".txt":  ("parsers.text",    "parse"),
    ".md":   ("parsers.text",    "parse"),
    ".py":   ("parsers.text",    "parse"),
    ".pdf":  ("parsers.pdf_vision", "parse"),
    ".docx": ("parsers.office",  "parse"),
    ".xlsx": ("parsers.office",  "parse"),
    ".xls":  ("parsers.office",  "parse"),
    ".json": ("parsers.data",    "parse"),
    ".csv":  ("parsers.data",    "parse"),
    ".ifc":  ("parsers.bim_ifc", "parse"),
    ".dwg":  ("parsers.bim_dwg", "parse"),
    ".rvt":  ("parsers.bim_rvt", "parse"),
}


def should_defer(path: Path) -> bool:
    """True если файл нужно откложить в ночную очередь."""
    suffix = path.suffix.lower()
    if suffix in DEFERRED_EXTS or suffix in METADATA_ONLY_EXTS:
        return True
    try:
        if path.stat().st_size / (1024 * 1024) > DEFERRED_SIZE_MB:
            return True
    except OSError:
        pass
    return False


def get_parser(path: Path):
    """Вернуть parse(path) из нужного модуля или None."""
    entry = _MAPPING.get(path.suffix.lower())
    if entry is None:
        return None
    mod_name, fn_name = entry
    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, fn_name)
    except (ModuleNotFoundError, AttributeError):
        return lambda p: None


if __name__ == "__main__":
    assert should_defer(Path("doc.pdf")) is True
    assert should_defer(Path("note.txt")) is False
    assert should_defer(Path("model.rvt")) is True
    print("OK should_defer")
    assert callable(get_parser(Path("test.txt")))
    assert callable(get_parser(Path("doc.pdf")))
    assert get_parser(Path("file.xyz")) is None
    print("OK get_parser")
    print("ALL TESTS PASSED")
