from __future__ import annotations
"""
storage/semantic_cache.py

Semantic answer cache for flying-rag.
Stores verified search results by query embedding similarity.

Ported from les_rag2/proxy/services/semantic_cache.py and adapted for LanceDB/flying-rag.

Usage:
    cache = SemanticCache()
    hit = cache.lookup(query, embedding, threshold=0.94)
    if hit:
        return hit.results
    ...
    cache.store(query, embedding, results)
"""

import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_WS_RE = re.compile(r"\s+")
_DEFAULT_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.94"))
_CACHE_ENABLED = os.getenv("SEMANTIC_CACHE_ENABLED", "true").lower() == "true"
_CACHE_MAX_ROWS = int(os.getenv("SEMANTIC_CACHE_MAX_ROWS", "500"))


@dataclass
class CacheHit:
    results: list[dict]
    similarity: float
    age_seconds: float


def _normalize(q: str) -> str:
    return _WS_RE.sub(" ", q.strip().lower())


def _cosine(a: list[float], b: list[float]) -> float:
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class SemanticCache:
    def __init__(self, db_path: str = "data/metadata.db", corpus_generation: str = "default"):
        self.db_path = db_path
        self.corpus_generation = str(corpus_generation)
        self._enabled = _CACHE_ENABLED

    def _scope(self, scope_key: str) -> str:
        return f"corpus:{self.corpus_generation}|{scope_key}"

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                norm_query   TEXT NOT NULL,
                scope_key    TEXT NOT NULL DEFAULT '',
                embedding    TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at   REAL NOT NULL,
                hit_count    INTEGER DEFAULT 0,
                last_hit_at  REAL DEFAULT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_scope "
            "ON search_cache(scope_key, created_at)"
        )
        conn.commit()
        return conn

    def lookup(
        self,
        query: str,
        embedding: list[float],
        threshold: float = _DEFAULT_THRESHOLD,
        scope_key: str = "",
    ) -> Optional[CacheHit]:
        if not self._enabled or not embedding:
            return None

        norm = _normalize(query)
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """SELECT id, norm_query, embedding, results_json, created_at
                   FROM search_cache
                   WHERE scope_key=?
                   ORDER BY created_at DESC LIMIT ?""",
                (self._scope(scope_key), _CACHE_MAX_ROWS),
            ).fetchall()

            best_id = None
            best_sim = 0.0
            best_results = None
            best_age = 0.0

            for row in rows:
                row_id, row_q, row_emb_json, row_res, row_ts = row
                # Exact match shortcut
                if row_q == norm:
                    sim = 1.0
                else:
                    try:
                        row_emb = json.loads(row_emb_json)
                        sim = _cosine(embedding, row_emb)
                    except Exception:
                        continue

                if sim > best_sim:
                    best_sim = sim
                    best_id = row_id
                    best_results = row_res
                    best_age = time.time() - row_ts

            if best_id is None or best_sim < threshold:
                return None

            conn.execute(
                "UPDATE search_cache SET hit_count=hit_count+1, last_hit_at=? WHERE id=?",
                (time.time(), best_id),
            )

            try:
                results = json.loads(best_results)
            except Exception:
                return None

            return CacheHit(results=results, similarity=best_sim, age_seconds=best_age)

    def store(
        self,
        query: str,
        embedding: list[float],
        results: list[dict],
        scope_key: str = "",
    ) -> None:
        if not self._enabled or not embedding or not results:
            return
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO search_cache
                   (norm_query, scope_key, embedding, results_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    _normalize(query),
                    self._scope(scope_key),
                    json.dumps(embedding, separators=(",", ":")),
                    json.dumps(results, ensure_ascii=False),
                    time.time(),
                ),
            )

    def clear(self, older_than_days: float = 7.0) -> int:
        """Remove cache entries older than N days. Returns count deleted."""
        cutoff = time.time() - older_than_days * 86400
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM search_cache WHERE created_at < ?", (cutoff,)
            )
            return cur.rowcount

    def stats(self) -> dict:
        try:
            with closing(self._connect()) as conn, conn:
                count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
                hits  = conn.execute("SELECT SUM(hit_count) FROM search_cache").fetchone()[0] or 0
                return {"entries": count, "total_hits": hits, "enabled": self._enabled}
        except Exception as e:
            return {"error": str(e)}
