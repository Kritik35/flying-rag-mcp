"""AST-чанкер для Python файлов. Каждая функция/класс = отдельный чанк."""
from __future__ import annotations
import ast
from pathlib import Path

import tiktoken

from chunker.semantic import Chunk, _doc_id

MAX_TOKENS = 400
_ENC = None


def _enc():
    global _ENC
    if _ENC is None:
        _ENC = tiktoken.get_encoding("cl100k_base")
    return _ENC


def chunk_code(doc) -> list[Chunk]:
    """
    Разбивает Python файл на чанки по функциям и классам.
    doc: ParsedDocument из parsers/text.py
    """
    did = _doc_id(doc.source_path)

    # Весь файл < MAX_TOKENS → один чанк
    if len(_enc().encode(doc.text)) < MAX_TOKENS:
        return [Chunk(
            doc_id=did, chunk_id=f"{did}_000", text=doc.text,
            metadata={**_base_meta(doc), "section": "full_file"},
        )]

    try:
        tree = ast.parse(doc.text)
    except SyntaxError:
        return [Chunk(
            doc_id=did, chunk_id=f"{did}_000", text=doc.text,
            metadata={**_base_meta(doc), "section": "full_file"},
        )]

    chunks: list[Chunk] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        prefix = "class" if isinstance(node, ast.ClassDef) else "def"
        section = f"{prefix} {node.name}"
        src = ast.get_source_segment(doc.text, node) or ""
        if not src.strip():
            continue
        idx = len(chunks)
        chunks.append(Chunk(
            doc_id=did,
            chunk_id=f"{did}_{idx:03d}",
            text=src,
            metadata={**_base_meta(doc), "section": section},
        ))

    # Нет функций/классов — вернуть весь файл
    if not chunks:
        return [Chunk(
            doc_id=did, chunk_id=f"{did}_000", text=doc.text,
            metadata={**_base_meta(doc), "section": "script"},
        )]

    return chunks


def _base_meta(doc) -> dict:
    return {
        "source_path": doc.source_path,
        "file_name":   doc.file_name,
        "created_at":  doc.created_at,
        "modified_at": doc.modified_at,
        "format":      doc.format,
        "namespace":   str(Path(doc.source_path).parent),
    }
