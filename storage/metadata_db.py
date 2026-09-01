from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from collections.abc import Iterator
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_path TEXT PRIMARY KEY,
    file_name   TEXT NOT NULL,
    format      TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    chunk_count INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'indexed',
    indexed_at  TEXT NOT NULL,
    dataset     TEXT DEFAULT 'normative',
    is_deprecated BOOLEAN DEFAULT 0,
    parent_source_path TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS raw_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    table_index INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    normalized_json TEXT,
    textualized_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_path) REFERENCES files(source_path)
);

CREATE TABLE IF NOT EXISTS indexing_progress (
    path TEXT PRIMARY KEY,
    total_files INTEGER NOT NULL,
    processed_files INTEGER NOT NULL,
    status      TEXT NOT NULL,
    last_file   TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parent_chunks (
    parent_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    parent_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_cache (
    chunk_hash TEXT PRIMARY KEY,
    vector_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engineering_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    rule_text TEXT NOT NULL,
    subject TEXT,
    parameter TEXT,
    operator TEXT,
    value REAL,
    unit TEXT,
    condition TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reindex_jobs (
    job_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    pid INTEGER,
    status TEXT NOT NULL,
    force BOOLEAN DEFAULT 0,
    use_cache BOOLEAN DEFAULT 1,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    log_path TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS runtime_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        try:
            conn.execute("ALTER TABLE files ADD COLUMN dataset TEXT DEFAULT 'normative'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE files ADD COLUMN is_deprecated BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE files ADD COLUMN parent_source_path TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

def _bump_corpus_generation(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO runtime_state(key, value) VALUES ('corpus_generation', 1)
           ON CONFLICT(key) DO UPDATE SET value = value + 1"""
    )

def get_corpus_generation(db_path: Path) -> int:
    # A read must not bring the database into existence: sqlite3.connect
    # creates the file, which turns "metadata DB is missing" into "metadata
    # DB is empty" and hides the misconfiguration from the retrieval trace.
    if not Path(db_path).exists():
        return 0
    with _connect(db_path) as conn:
        try:
            row = conn.execute(
                "SELECT value FROM runtime_state WHERE key = 'corpus_generation'"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0]) if row else 0

def upsert_file(db_path: Path, source_path: str, file_name: str,
                 format: str, sha256: str, created_at: str,
                 modified_at: str, chunk_count: int, status: str = "indexed",
                 dataset: str = "normative", is_deprecated: bool = False,
                 parent_source_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO files 
            (source_path, file_name, format, sha256, created_at, modified_at, chunk_count, status, indexed_at, dataset, is_deprecated, parent_source_path) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_path, file_name, format, sha256, created_at, modified_at, chunk_count, status, _now(), dataset, int(is_deprecated), parent_source_path)
        )
        _bump_corpus_generation(conn)

def mark_deprecated(db_path: Path, source_path: str) -> None:
    with _connect(db_path) as conn:
        changed = conn.execute(
            "UPDATE files SET is_deprecated = 1 WHERE source_path = ? AND is_deprecated = 0",
            (source_path,),
        ).rowcount
        if changed:
            _bump_corpus_generation(conn)

def save_raw_table(db_path: Path, source_path: str, table_index: int, raw_json: str,
                    normalized_json: str | None = None, textualized_json: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO raw_tables (source_path, table_index, raw_json, normalized_json, textualized_json, created_at) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (source_path, table_index, raw_json, normalized_json, textualized_json, _now())
        )

def get_file(db_path: Path, source_path: str) -> dict | None:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM files WHERE source_path = ?", (source_path,)).fetchone()
    return dict(row) if row else None

def file_changed(db_path: Path, source_path: str, new_sha256: str) -> bool:
    rec = get_file(db_path, source_path)
    if rec is None:
        return True
    return rec["sha256"] != new_sha256

def list_files(db_path: Path, folder_filter: str | None = None, dataset: str | None = None) -> list[dict]:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        where = []
        params = []
        if folder_filter:
            where.append("source_path LIKE ?")
            params.append("%" + folder_filter + "%")
        if dataset:
            where.append("dataset = ?")
            params.append(dataset)
        query = "SELECT * FROM files"
        if where:
            query += " WHERE " + " AND ".join(where)
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def delete_file(db_path: Path, source_path: str, *, preserve_rules: bool = False) -> None:
    import hashlib

    doc_id = hashlib.sha256(source_path.encode()).hexdigest()[:8]
    with _connect(db_path) as conn:
        changed = 0
        changed += conn.execute("DELETE FROM raw_tables WHERE source_path = ?", (source_path,)).rowcount
        changed += conn.execute("DELETE FROM files WHERE source_path = ?", (source_path,)).rowcount
        changed += conn.execute("DELETE FROM parent_chunks WHERE source_path = ?", (source_path,)).rowcount
        if not preserve_rules:
            changed += conn.execute("DELETE FROM engineering_rules WHERE source_path = ?", (source_path,)).rowcount
        try:
            changed += conn.execute(
                "DELETE FROM doc_edges WHERE doc_id_a = ? OR doc_id_b = ?", (doc_id, doc_id)
            ).rowcount
        except sqlite3.OperationalError:
            pass
        if changed:
            _bump_corpus_generation(conn)

def update_indexing_progress(db_path: Path, path: str, total_files: int,
                              processed_files: int, status: str,
                              last_file: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO indexing_progress
               (path, total_files, processed_files, status, last_file, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (path, total_files, processed_files, status, last_file or "", _now())
        )

def get_active_indexing_progress(db_path: Path) -> dict | None:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM indexing_progress WHERE status = 'indexing' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None

def save_parent_chunk(db_path: Path, parent_id: str, source_path: str, parent_text: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO parent_chunks (parent_id, source_path, parent_text, created_at) VALUES (?, ?, ?, ?)""",
            (parent_id, source_path, parent_text, _now())
        )

def get_parent_chunk(db_path: Path, parent_id: str) -> str | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT parent_text FROM parent_chunks WHERE parent_id = ?", (parent_id,)).fetchone()
    return row[0] if row else None

def save_cached_chunk(db_path: Path, chunk_hash: str, vector_id: str, parent_id: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO chunk_cache (chunk_hash, vector_id, parent_id, created_at) VALUES (?, ?, ?, ?)""",
            (chunk_hash, vector_id, parent_id, _now())
        )

def get_cached_chunk(db_path: Path, chunk_hash: str) -> dict | None:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM chunk_cache WHERE chunk_hash = ?", (chunk_hash,)).fetchone()
    return dict(row) if row else None

def save_engineering_rule(db_path: Path, source_path: str, chunk_id: str, rule_text: str,
                           subject: str | None, parameter: str | None, operator: str | None,
                           value: float | None, unit: str | None, condition: str | None) -> None:
    with _connect(db_path) as conn:
        exists = conn.execute(
            """SELECT 1 FROM engineering_rules
            WHERE source_path = ? AND chunk_id = ? AND rule_text = ?
            LIMIT 1""",
            (source_path, chunk_id, rule_text),
        ).fetchone()
        if exists:
            return
        conn.execute(
            """INSERT INTO engineering_rules (source_path, chunk_id, rule_text, subject, parameter, operator, value, unit, condition, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_path, chunk_id, rule_text, subject, parameter, operator, value, unit, condition, _now())
        )

def delete_engineering_rules(db_path: Path, source_path: str) -> int:
    """Удалить все правила файла перед повторной экстракцией (защита от дублей)."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM engineering_rules WHERE source_path = ?", (source_path,)
        )
        return cur.rowcount

def replace_engineering_rules(db_path: Path, source_path: str, rules: list[dict]) -> int:
    """Atomically replace every extracted rule for one source file."""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM engineering_rules WHERE source_path = ?", (source_path,))
        conn.executemany(
            """INSERT INTO engineering_rules
               (source_path, chunk_id, rule_text, subject, parameter, operator,
                value, unit, condition, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    source_path, rule["chunk_id"], rule["rule_text"],
                    rule.get("subject"), rule.get("parameter"), rule.get("operator"),
                    rule.get("value"), rule.get("unit"), rule.get("condition"), _now(),
                )
                for rule in rules
            ],
        )
    return len(rules)

def create_reindex_job(db_path: Path, job_id: str, path: str, pid: int | None,
                       force: bool, use_cache: bool, log_path: str | None) -> None:
    init_db(db_path)
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO reindex_jobs
               (job_id, path, pid, status, force, use_cache, started_at, updated_at, completed_at, log_path, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)""",
            (job_id, path, pid, "started", int(force), int(use_cache), now, now, log_path),
        )

def update_reindex_job(db_path: Path, job_id: str, status: str,
                       pid: int | None = None, error: str | None = None) -> None:
    completed_at = _now() if status in {"completed", "failed", "cancelled"} else None
    with _connect(db_path) as conn:
        conn.execute(
            """UPDATE reindex_jobs
               SET status = ?,
                   pid = COALESCE(?, pid),
                   updated_at = ?,
                   completed_at = COALESCE(?, completed_at),
                   error = COALESCE(?, error)
               WHERE job_id = ?""",
            (status, pid, _now(), completed_at, error, job_id),
        )

def get_reindex_job(db_path: Path, job_id: str) -> dict | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reindex_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None

def list_reindex_jobs(db_path: Path, limit: int = 20) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM reindex_jobs ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [dict(row) for row in rows]
