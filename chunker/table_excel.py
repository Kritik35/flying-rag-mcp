"""
chunker/table_excel.py — Table-aware чанкер для Excel (XLS/XLSX).

Каждая строка данных + заголовки колонок = отдельный чанк с поддержкой формул и итоговых строк.
Аналог table_docx.py для Excel-файлов.
"""
from __future__ import annotations
from pathlib import Path
import openpyxl


def chunk_excel_tables(path: Path) -> list[str]:
    """
    Извлечь все строки всех листов как структурированные текстовые блоки.
    Загружает книгу с data_only=False, чтобы иметь доступ к формулам.

    Каждый блок:
        Лист: Нагрузки
        Тип: Итоговая строка (опционально)
        Параметр: Постоянная нагрузка
        Значение: 5.2
        Единица: кПа
        ...

    Пропускает строки где все ячейки пустые.
    Возвращает list[str] — один элемент = одна строка данных.
    """
    try:
        # Загружаем с data_only=False чтобы видеть формулы (например, =SUM(...))
        wb = openpyxl.load_workbook(str(path), data_only=False)
    except Exception:
        return []

    chunks: list[str] = []

    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue

        # Пытаемся определить первую непустую строку как строку заголовков
        header = None
        header_idx = 0
        for idx, r in enumerate(rows):
            if any(cell is not None and str(cell).strip() != "" for cell in r):
                header = [str(cell).strip() if cell is not None else f"Col_{i+1}" for i, cell in enumerate(r)]
                header_idx = idx
                break

        if header is None:
            continue

        # Итерируем по всем строкам ниже заголовка
        for row in rows[header_idx + 1:]:
            # Пропускаем полностью пустые строки
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            lines = [f"Лист: {sheet.title}"]

            # Проверяем, является ли строка итоговой/суммарной
            row_str_lower = " ".join(str(cell).lower() for cell in row if cell is not None)
            is_summary = any(kw in row_str_lower for kw in ["итого", "всего", "summary", "total"])
            if is_summary:
                lines.append("Тип: Итоговая строка")

            for h, cell in zip(header, row):
                h_name = str(h).strip()
                val = str(cell).strip() if cell is not None else ""
                if h_name and val:
                    if val.startswith("="):
                        lines.append(f"{h_name}: {val} (Формула)")
                    else:
                        lines.append(f"{h_name}: {val}")

            if len(lines) > 1:
                chunks.append("\n".join(lines))

    wb.close()
    return chunks


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        fp = Path(sys.argv[1])
        result = chunk_excel_tables(fp)
        print(f"Chunks: {len(result)}")
        for c in result[:3]:
            print("\n---")
            print(c)
