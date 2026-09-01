from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import tiktoken

MAX_PARENT_TOKENS = 1000
OVERLAP_PARENT_TOKENS = 100
MAX_CHILD_TOKENS = 150
OVERLAP_CHILD_TOKENS = 20

# Chunker identity for the index manifest. Bump the version when a change alters
# how existing text would be split — the manifest then refuses to mix old and
# new chunks in one store instead of degrading context silently.
CHUNKER_ID = "parent-child-tiktoken-v1"


def chunk_params() -> dict:
    return {
        "max_parent_tokens": MAX_PARENT_TOKENS,
        "overlap_parent_tokens": OVERLAP_PARENT_TOKENS,
        "max_child_tokens": MAX_CHILD_TOKENS,
        "overlap_child_tokens": OVERLAP_CHILD_TOKENS,
        "encoding": "cl100k_base",
    }

# Compatibility constants
MAX_TOKENS = MAX_CHILD_TOKENS
OVERLAP_TOKENS = OVERLAP_CHILD_TOKENS

_ENC = None


def _enc():
    global _ENC
    if _ENC is None:
        _ENC = tiktoken.get_encoding("cl100k_base")
    return _ENC


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


def _doc_id(source_path: str) -> str:
    return hashlib.sha256(source_path.encode()).hexdigest()[:8]


def _count_tokens(text: str) -> int:
    return len(_enc().encode(text))


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'^(#{1,3}\s+.+)$', re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return [("", text)]
    parts: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        pre = text[:matches[0].start()].strip()
        if pre:
            parts.append(("", pre))
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        parts.append((heading, content))
    return [(h, c) for h, c in parts if h or c]


def _split_long_text(text: str, max_tok: int, overlap: int) -> list[str]:
    enc = _enc()
    tokens = enc.encode(text)
    if len(tokens) <= max_tok:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tok, len(tokens))
        chunks.append(enc.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start = end - overlap
    return chunks


def _split_parents_and_children(doc_id: str, text: str, heading: str, base_meta: dict,
                                 start_parent_idx: int, start_child_idx: int) -> tuple[list[Chunk], int, int]:
    parent_sections = _split_long_text(text, MAX_PARENT_TOKENS, OVERLAP_PARENT_TOKENS)
    chunks = []
    parent_idx = start_parent_idx
    child_idx = start_child_idx
    
    for p_text in parent_sections:
        p_text_stripped = p_text.strip()
        if not p_text_stripped:
            continue
        p_id = f"{doc_id}_p_{parent_idx:04d}"
        
        child_sections = _split_long_text(p_text_stripped, MAX_CHILD_TOKENS, OVERLAP_CHILD_TOKENS)
        for c_text in child_sections:
            c_text_stripped = c_text.strip()
            if not c_text_stripped:
                continue
            c_id = f"{doc_id}_c_{child_idx:04d}"
            
            meta = base_meta.copy()
            meta["section"] = heading.lstrip("#").strip() if heading else ""
            meta["parent_id"] = p_id
            meta["parent_text"] = p_text_stripped
            
            chunks.append(Chunk(
                doc_id=doc_id,
                chunk_id=c_id,
                text=c_text_stripped,
                metadata=meta
            ))
            child_idx += 1
        parent_idx += 1
        
    return chunks, parent_idx, child_idx


def chunk_document(doc, namespace: str = "") -> list[Chunk]:
    if doc.format == "py":
        from chunker.code import chunk_code
        py_chunks = chunk_code(doc)
        for c in py_chunks:
            if namespace:
                c.metadata["namespace"] = namespace
            c.metadata["parent_id"] = c.chunk_id
            c.metadata["parent_text"] = c.text
        return py_chunks

    doc_id = _doc_id(doc.source_path)
    ns = namespace or str(Path(doc.source_path).parent)
    base_meta = {
        "source_path": doc.source_path,
        "file_name": doc.file_name,
        "format": doc.format,
        "created_at": doc.created_at,
        "modified_at": doc.modified_at,
        "namespace": ns,
    }

    if doc.format in ("xlsx", "xls"):
        from chunker.table_excel import chunk_excel_tables
        try:
            tbl_texts = chunk_excel_tables(Path(doc.source_path))
            xlsx_chunks = []
            for t_idx, t in enumerate(tbl_texts):
                c_id = f"{doc_id}_row_{t_idx:04d}"
                xlsx_chunks.append(Chunk(
                    doc_id=doc_id,
                    chunk_id=c_id,
                    text=t,
                    metadata={
                        **base_meta,
                        "section": "Table Excel",
                        "parent_id": c_id,
                        "parent_text": t
                    },
                ))
            if xlsx_chunks:
                return xlsx_chunks
        except Exception:
            pass

    tbl_chunks = []
    if doc.format == "docx":
        from chunker.table_docx import chunk_docx_tables
        try:
            tbl_texts = chunk_docx_tables(Path(doc.source_path))
            for t_idx, t in enumerate(tbl_texts):
                c_id = f"{doc_id}_tbl_{t_idx:04d}"
                tbl_chunks.append(Chunk(
                    doc_id=doc_id,
                    chunk_id=c_id,
                    text=t,
                    metadata={
                        **base_meta,
                        "section": "Table Docx",
                        "parent_id": c_id,
                        "parent_text": t
                    },
                ))
        except Exception:
            pass

    sections = _split_by_headings(doc.text or "")
    chunks: list[Chunk] = []
    parent_idx = 0
    child_idx = 0
    for heading, content in sections:
        full_text = f"{heading}\n\n{content}".strip() if heading else content.strip()
        if not full_text:
            continue
        sec_chunks, parent_idx, child_idx = _split_parents_and_children(
            doc_id, full_text, heading, base_meta, parent_idx, child_idx
        )
        chunks.extend(sec_chunks)
        
    if not chunks and not tbl_chunks:
        p_id = f"{doc_id}_p_0000"
        c_id = f"{doc_id}_c_0000"
        meta = base_meta.copy()
        meta["section"] = ""
        meta["parent_id"] = p_id
        meta["parent_text"] = doc.text or ""
        chunks.append(Chunk(
            doc_id=doc_id,
            chunk_id=c_id,
            text=doc.text or "",
            metadata=meta
        ))
    return chunks + tbl_chunks
