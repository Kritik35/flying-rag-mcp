"""
storage/graph.py — граф семантических связей между документами.

Хранит top-K похожих документов для каждого doc_id в SQLite.
Обновляется при добавлении нового документа в LanceDB.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path


def _documents_table_name(dim: int | None = None) -> str:
    if dim is None:
        from embedder.client import _DEFAULT_PROVIDER
        dim = _DEFAULT_PROVIDER.get_dimension()
    return f"documents_{dim}"


# ── Инициализация ────────────────────────────────────────────────────────────

def init_graph(db_path: Path) -> None:
    """Создать таблицу рёбер если не существует."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_edges (
            doc_id_a   TEXT NOT NULL,
            doc_id_b   TEXT NOT NULL,
            similarity REAL NOT NULL,
            PRIMARY KEY (doc_id_a, doc_id_b)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_a ON doc_edges(doc_id_a)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_b ON doc_edges(doc_id_b)")
    conn.commit()
    conn.close()


# ── Добавление рёбер ─────────────────────────────────────────────────────────

def add_document_edges(
    lance_path: Path,
    meta_db_path: Path,
    doc_id: str,
    top_k: int = 5,
) -> int:
    """
    Для нового doc_id найти top_k наиболее похожих документов
    и записать рёбра в граф.

    Алгоритм:
    1. Взять все чанки doc_id из LanceDB → вычислить centroid (среднее вектора)
    2. Поиск top_k похожих чанков по centroid (исключая тот же doc_id)
    3. Дедуплицировать по doc_id → взять лучший score для каждого
    4. Записать рёбра (bidirectional)

    Возвращает количество добавленных рёбер.
    """
    try:
        import lancedb
        import numpy as np
    except ImportError:
        return 0

    init_graph(meta_db_path)

    db = lancedb.connect(str(lance_path))
    try:
        tbl = db.open_table(_documents_table_name())
    except Exception:
        return 0

    # 1. Чанки текущего документа
    try:
        own_chunks = tbl.search().where(f"doc_id = '{doc_id}'").to_list()
    except Exception:
        return 0

    if not own_chunks:
        return 0

    # 2. Centroid всех чанков документа
    vecs = [row["vector"] for row in own_chunks if "vector" in row]
    if not vecs:
        return 0

    centroid = np.mean(vecs, axis=0).tolist()

    # 3. Поиск похожих (берём больше чтобы было из чего фильтровать)
    try:
        results = tbl.search(centroid).limit(top_k * 10).to_list()
    except Exception:
        return 0

    # 4. Группируем по doc_id, берём лучший score, исключаем себя
    best: dict[str, float] = {}
    for row in results:
        other_id = row.get("doc_id", "")
        score = float(row.get("_distance", 1.0))
        similarity = max(0.0, 1.0 - score)  # distance → similarity
        if other_id and other_id != doc_id:
            if other_id not in best or similarity > best[other_id]:
                best[other_id] = similarity

    if not best:
        return 0

    # 5. Топ-K соседей
    neighbors = sorted(best.items(), key=lambda x: x[1], reverse=True)[:top_k]

    # 6. Запись рёбер (bidirectional)
    conn = sqlite3.connect(meta_db_path)
    added = 0
    for other_id, sim in neighbors:
        conn.execute(
            "INSERT OR REPLACE INTO doc_edges (doc_id_a, doc_id_b, similarity) VALUES (?,?,?)",
            (doc_id, other_id, sim),
        )
        conn.execute(
            "INSERT OR REPLACE INTO doc_edges (doc_id_a, doc_id_b, similarity) VALUES (?,?,?)",
            (other_id, doc_id, sim),
        )
        added += 1
    conn.commit()
    conn.close()

    return added


# ── Чтение графа ─────────────────────────────────────────────────────────────

def get_neighbors(
    meta_db_path: Path,
    doc_id: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Вернуть top_k семантически похожих документов для doc_id.

    Возвращает: [{doc_id, similarity, file_name}, ...]

    Note: doc_id = sha256(source_path)[:8], so we resolve file_name
    via a Python-side lookup (SQLite can't compute sha256 natively).
    """
    import hashlib

    init_graph(meta_db_path)
    conn = sqlite3.connect(meta_db_path)

    edge_rows = conn.execute(
        "SELECT doc_id_b, similarity FROM doc_edges WHERE doc_id_a=? "
        "ORDER BY similarity DESC LIMIT ?",
        (doc_id, top_k),
    ).fetchall()

    # Build doc_id → file_name map: sha256(source_path)[:8] → file_name
    id_to_name: dict[str, str] = {}
    try:
        for sp, fn in conn.execute("SELECT source_path, file_name FROM files"):
            if sp:
                key = hashlib.sha256(sp.encode()).hexdigest()[:8]
                id_to_name[key] = fn or ""
    except Exception:
        pass

    conn.close()

    return [
        {
            "doc_id": r[0],
            "similarity": round(r[1], 4),
            "file_name": id_to_name.get(r[0], ""),
        }
        for r in edge_rows
    ]


def get_graph_stats(meta_db_path: Path) -> dict:
    """Статистика графа: кол-во рёбер, документов с рёбрами."""
    try:
        init_graph(meta_db_path)
        conn = sqlite3.connect(meta_db_path)
        edges = conn.execute("SELECT COUNT(*) FROM doc_edges").fetchone()[0]
        docs  = conn.execute("SELECT COUNT(DISTINCT doc_id_a) FROM doc_edges").fetchone()[0]
        conn.close()
        return {"edges": edges, "docs_with_edges": docs}
    except Exception as e:
        return {"error": str(e)}
