"""
chunker/table_docx.py — Table-aware чанкер для DOCX.

Каждая строка таблицы становится отдельным чанком с заголовком колонок.
Это решает проблему потери контекста при стандартном чанковании по токенам.
"""
from __future__ import annotations
from pathlib import Path


def chunk_docx_tables(doc_path: Path) -> list[str]:
    """
    Извлечь все строки всех таблиц из DOCX как структурированные текстовые блоки.

    Каждый блок:
        Город: Санкт-Петербург
        Т наиб. холодных суток 0,98: -31
        Т наиб. холодной пятидневки 0,98: -27
        ...

    Строки с пустым первым столбцом (разделители регионов) пропускаются.
    Возвращает list[str] — один элемент = один ключевой объект (город/объект).
    """
    from docx import Document

    doc = Document(str(doc_path))
    chunks: list[str] = []

    for table_idx, table in enumerate(doc.tables):
        if len(table.rows) < 2:
            continue

        # Заголовок: первая строка (может быть многоуровневой — берём первую)
        header = [cell.text.strip() for cell in table.rows[0].cells]
        # Убираем дубликаты в объединённых ячейках
        header_clean: list[str] = []
        for h in header:
            if not header_clean or h != header_clean[-1]:
                header_clean.append(h)

        for row in table.rows[1:]:
            cells = [cell.text.strip() for cell in row.cells]

            # Пропускаем пустые строки и строки-разделители регионов
            if not cells or not cells[0]:
                continue
            # Строки где все значения одинаковы (заголовок секции)
            if len(set(cells)) == 1:
                continue
            # Строки-заголовки которые повторяются в теле таблицы
            if cells[0] == header_clean[0]:
                continue

            block_parts = [f"{header_clean[0] or 'Объект'}: {cells[0]}"]
            for i in range(1, min(len(header_clean), len(cells))):
                if header_clean[i] and cells[i]:
                    block_parts.append(f"{header_clean[i]}: {cells[i]}")

            if len(block_parts) > 1:  # не добавляем пустые блоки
                chunks.append("\n".join(block_parts))

    return chunks


def get_spb_chunks(doc_path: Path) -> list[str]:
    """Быстро найти все блоки для Санкт-Петербурга."""
    return [c for c in chunk_docx_tables(doc_path)
            if 'Санкт-Петербург' in c or 'С.-Петербург' in c]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m chunker.table_docx <file.docx>", file=sys.stderr)
        raise SystemExit(2)
    fp = Path(sys.argv[1])
    spb = get_spb_chunks(fp)
    print(f"Блоков для Санкт-Петербурга: {len(spb)}")
    for i, b in enumerate(spb[:3]):
        print(f"\n--- Блок {i+1} ---")
        print(b[:500])
