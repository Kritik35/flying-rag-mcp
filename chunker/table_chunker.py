"""
chunker/table_chunker.py — Семантический чанкер для таблиц (Vision LLM / Stage 5).

Каждая текстовая строка, полученная из парсера, становится отдельным чанком
с добавлением метаданных.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from dataclasses import dataclass
from .semantic import Chunk, _doc_id, _count_tokens

def chunk_table_rows(doc, namespace: str = "") -> list[Chunk]:
    """
    Семантический чанкер для ParsedDocument, сгенерированного pdf_vision.py.
    """
    doc_id = _doc_id(doc.source_path)
    ns = namespace or str(Path(doc.source_path).parent)
    
    # Хэш структуры всей таблицы для дедупликации (для простоты - от текста документа)
    table_hash = hashlib.sha256((doc.text or "").encode()).hexdigest()[:16]
    
    base_meta = {
        "source_path": doc.source_path,
        "file_name": doc.file_name,
        "format": doc.format,
        "created_at": doc.created_at,
        "modified_at": doc.modified_at,
        "namespace": ns,
        "table_hash": table_hash,
        "doc_version": "1.0", # Заглушка, можно брать из extra
        "cross_references": []
    }
    
    # В pdf_vision.py мы объединяли строки через \n\n
    raw_rows = (doc.text or "").split("\n\n")
    chunks: list[Chunk] = []
    
    for idx, row_text in enumerate(raw_rows):
        row_text = row_text.strip()
        if not row_text:
            continue
            
        chunks.append(Chunk(
            doc_id=doc_id,
            chunk_id=f"{doc_id}_tbl_{idx:04d}",
            text=row_text,
            metadata={
                **base_meta, 
                "row_index": idx,
                "type": "table_row"
            }
        ))
        
    # Fallback
    if not chunks:
        chunks.append(Chunk(
            doc_id=doc_id,
            chunk_id=f"{doc_id}_tbl_0000",
            text=doc.text or "",
            metadata={**base_meta, "type": "empty_table"}
        ))
        
    return chunks

if __name__ == "__main__":
    from dataclasses import dataclass as dc, field as f

    @dc
    class FakeDoc:
        source_path: str = "/tmp/test_table.pdf"
        file_name: str = "test_table.pdf"
        format: str = "pdf"
        text: str = "Строка таблицы: [Система] = П1. [Вентилятор | L, м3/ч] = 1000\n\nСтрока таблицы: [Система] = В1. [Вентилятор | L, м3/ч] = 800"
        created_at: str = "2026-01-01T00:00:00+00:00"
        modified_at: str = "2026-01-01T00:00:00+00:00"
        extra: dict = f(default_factory=dict)

    doc = FakeDoc()
    chunks = chunk_table_rows(doc)
    assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"
    print(f"OK: {len(chunks)} chunks")
    print("ALL TESTS PASSED")
