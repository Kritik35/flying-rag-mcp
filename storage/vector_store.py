from __future__ import annotations
import sys
import sqlite3
import hashlib
import yaml
from pathlib import Path
import numpy as np
import pyarrow as pa
from embedder.client import _DEFAULT_PROVIDER

def load_config():
    from config_loader import load_config as _load
    return _load()

ROOT = Path(__file__).resolve().parent.parent


def _get_sqlite_path() -> Path:
    """Absolute path to the metadata DB.

    ``storage.metadata_db`` is configured relative to the repository, but an MCP
    server is launched by its client with an arbitrary working directory. A
    CWD-relative path therefore did not exist at runtime, parent hydration
    silently found nothing, and every result fell back to the 150-token child
    chunk instead of its 1000-token parent — the parent-child design switched
    itself off with no error anywhere.
    """
    config = load_config()
    db_str = config.get("storage", {}).get("metadata_db", "data/metadata.db")
    path = Path(db_str)
    return path if path.is_absolute() else (ROOT / path)

_DB_CACHE = {}

def _get_table(db_path: Path, dim: int | None = None):
    import lancedb
    if dim is None:
        dim = _DEFAULT_PROVIDER.get_dimension()
    db_path.mkdir(parents=True, exist_ok=True)
    
    db_key = str(db_path)
    if db_key not in _DB_CACHE:
        _DB_CACHE[db_key] = lancedb.connect(db_key)
    db = _DB_CACHE[db_key]
    
    table_name = f"documents_{dim}"
    
    schema = pa.schema([
        pa.field("chunk_id",    pa.string()),
        pa.field("doc_id",      pa.string()),
        pa.field("text",        pa.string()),
        pa.field("vector",      pa.list_(pa.float16(), dim)),
        pa.field("source_path", pa.string()),
        pa.field("file_name",   pa.string()),
        pa.field("format",      pa.string()),
        pa.field("created_at",  pa.string()),
        pa.field("modified_at", pa.string()),
        pa.field("section",     pa.string()),
        pa.field("namespace",   pa.string()),
        pa.field("parent_id",   pa.string()),
    ])
    
    if table_name not in db.table_names():
        return db, db.create_table(table_name, schema=schema)
    return db, db.open_table(table_name)

def get_chunk_vector(db_path: Path, chunk_id: str, dim: int | None = None, doc_id: str | None = None) -> list[float] | None:
    try:
        if dim is None:
            dim = _DEFAULT_PROVIDER.get_dimension()
        _, table = _get_table(db_path, dim)
        safe_chunk_id = chunk_id.replace("'", "''")
        where_clause = f"chunk_id = '{safe_chunk_id}'"
        if doc_id:
            safe_doc_id = doc_id.replace("'", "''")
            where_clause += f" AND doc_id = '{safe_doc_id}'"
        rows = table.search().where(where_clause).limit(1).to_list()
        if rows:
            return rows[0]["vector"]
    except Exception:
        pass
    return None


def get_verified_chunk_vector(
    db_path: Path,
    chunk_id: str,
    expected_hash: str | None = None,
    expected_dim: int | None = None,
    doc_id: str | None = None,
) -> tuple[list[float] | None, str]:
    """Safely retrieves a cached vector while verifying text contract and dimensionality.

    Returns: (vector, status_reason)
    status_reason: "CACHE_VERIFIED" | "CACHE_UNVERIFIED: <reason>"
    """
    try:
        if expected_dim is None:
            if hasattr(_DEFAULT_PROVIDER, "get_dimension"):
                expected_dim = _DEFAULT_PROVIDER.get_dimension()
            else:
                expected_dim = getattr(_DEFAULT_PROVIDER, "dimension", 1024)
        _, table = _get_table(db_path, expected_dim)
        safe_chunk_id = chunk_id.replace("'", "''")
        where_clause = f"chunk_id = '{safe_chunk_id}'"
        if doc_id:
            safe_doc_id = doc_id.replace("'", "''")
            where_clause += f" AND doc_id = '{safe_doc_id}'"

        # Check up to 101 rows to detect excessive collisions
        rows = table.search().where(where_clause).limit(101).to_list()
        if not rows:
            return None, "CACHE_UNVERIFIED: vector_not_found_in_lancedb"

        if len(rows) > 100:
            return None, "CACHE_UNVERIFIED: excessive_collisions (> 100 rows)"

        first_vec = rows[0].get("vector")
        if first_vec is None:
            return None, "CACHE_UNVERIFIED: empty_vector"

        first_vec_arr = np.asarray(first_vec)
        if len(first_vec_arr) != expected_dim:
            return None, f"CACHE_UNVERIFIED: dimension_mismatch (got {len(first_vec_arr)}, expected {expected_dim})"

        if not np.isfinite(first_vec_arr).all():
            return None, "CACHE_UNVERIFIED: non_finite_vector_values"

        # Ambiguity check: analyze ALL physical rows for this chunk_id
        if len(rows) > 1:
            for r in rows[1:]:
                r_vec = r.get("vector")
                if r_vec is None:
                    return None, "CACHE_UNVERIFIED: ambiguous_conflicting_vectors (empty vector in row)"
                r_vec_arr = np.asarray(r_vec)
                if len(r_vec_arr) != expected_dim:
                    return None, f"CACHE_UNVERIFIED: dimension_mismatch in colliding row (got {len(r_vec_arr)}, expected {expected_dim})"
                if not np.isfinite(r_vec_arr).all():
                    return None, "CACHE_UNVERIFIED: non_finite_vector_values in colliding row"
                if not np.allclose(r_vec_arr, first_vec_arr, atol=1e-5):
                    return None, "CACHE_UNVERIFIED: ambiguous_conflicting_vectors"

        # Text hash check
        if expected_hash:
            for r in rows:
                row_text = r.get("text")
                if not row_text:
                    return None, "CACHE_UNVERIFIED: missing_row_text_for_hash_verification"
                h = hashlib.sha256(row_text.encode("utf-8")).hexdigest()
                if h != expected_hash:
                    return None, "CACHE_UNVERIFIED: text_hash_mismatch"

        return first_vec, "CACHE_VERIFIED"
    except Exception as e:
        return None, f"CACHE_UNVERIFIED: exception ({e})"

# Language of the corpus, for the lexical channel's stemmer and stop
# words. ascii_folding is off: it is for Latin diacritics and has
# nothing useful to do with Cyrillic.
FTS_LANGUAGE = "Russian"


DEFAULT_FUSION = "linear"


def fusion_mode() -> str:
    """How the dense and lexical channels are combined: 'linear' or 'rrf'."""
    try:
        value = (load_config().get("retrieval") or {}).get("fusion", DEFAULT_FUSION)
    except Exception:
        return DEFAULT_FUSION
    return str(value or DEFAULT_FUSION).strip().casefold()


def build_fusion_reranker(mode: str, alpha: float):
    """(reranker, fusion name, score kind) for the requested mode.

    Linear combination adds a cosine similarity to a BM25 score — two
    quantities on different scales, blended by a weight tuned against one
    corpus. RRF uses only the rank a result took in each channel, which is the
    part that carries meaning across both.

    The score kind travels with it: retrieval thresholds are read against that
    field, so an RRF score must not arrive labelled as a linear combination.
    """
    from lancedb.rerankers import LinearCombinationReranker, RRFReranker

    if str(mode or "").strip().casefold() == "rrf":
        return RRFReranker(), "rrf", "rrf"
    return (LinearCombinationReranker(weight=alpha),
            "linear_combination", "linear_combination")


def ensure_fts_index(db_path: Path, dim: int | None = None) -> bool:
    try:
        if dim is None:
            dim = _DEFAULT_PROVIDER.get_dimension()
        _, table = _get_table(db_path, dim)
        # The corpus is Russian; create_fts_index defaults to an English
        # stemmer and English stop words. Every inflected form then became its
        # own token, and on the live index the top-40 for "воздуховод" and
        # "воздуховодов" shared nothing at all — the lexical half of the hybrid
        # was matching one form instead of the word. Russian inflects across
        # six cases and two numbers, so most of that channel was idle.
        table.create_fts_index(
            "text", replace=True, language=FTS_LANGUAGE,
            stem=True, remove_stop_words=True, ascii_folding=False,
        )
        print(f"[vector_store] FTS index created/updated for dim {dim} "
              f"({FTS_LANGUAGE})", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[vector_store] FTS index WARN: {e}", file=sys.stderr)
        return False

def upsert_chunks(db_path: Path, chunks: list, embeddings: list, dim: int | None = None) -> int:
    if not chunks:
        return 0
    if dim is None:
        if embeddings:
            dim = len(embeddings[0].embedding)
        else:
            if hasattr(_DEFAULT_PROVIDER, "get_dimension"):
                dim = _DEFAULT_PROVIDER.get_dimension()
            else:
                dim = getattr(_DEFAULT_PROVIDER, "dimension", 1024)

    # 1. Preflight Completeness & Integrity Checks (BEFORE any destructive operation)
    seen_chunk_ids = set()
    for c in chunks:
        cid = getattr(c, "chunk_id", None)
        did = getattr(c, "doc_id", None)
        if not cid or not str(cid).strip():
            raise ValueError("Preflight check failed in upsert_chunks: chunk has empty chunk_id")
        if not did or not str(did).strip():
            raise ValueError(f"Preflight check failed in upsert_chunks: chunk '{cid}' has empty doc_id")
        if cid in seen_chunk_ids:
            raise ValueError(f"Preflight check failed in upsert_chunks: duplicate chunk_id '{cid}' detected")
        seen_chunk_ids.add(cid)

    emb_map = {e.chunk_id: e.embedding for e in embeddings if hasattr(e, "chunk_id")}
    missing = [c.chunk_id for c in chunks if c.chunk_id not in emb_map or emb_map[c.chunk_id] is None]
    if missing:
        raise ValueError(
            f"Preflight check failed in upsert_chunks: {len(missing)} chunk(s) missing embeddings: {missing[:5]}"
        )

    # Validate vector dimensionality and finite values for 100% of embeddings
    for c in chunks:
        emb = emb_map[c.chunk_id]
        arr = np.asarray(emb, dtype=np.float32)
        if len(arr) != dim:
            raise ValueError(
                f"Preflight check failed: chunk '{c.chunk_id}' embedding dimension {len(arr)} != expected {dim}"
            )
        if not np.isfinite(arr).all():
            raise ValueError(
                f"Preflight check failed: chunk '{c.chunk_id}' embedding contains non-finite values (NaN or Inf)"
            )

    # Pre-convert all records in memory to verify schema/serialization validity
    records = []
    for chunk in chunks:
        emb = emb_map[chunk.chunk_id]
        chunk_meta = getattr(chunk, "metadata", {}) or {}
        records.append({
            "chunk_id":    chunk.chunk_id,
            "doc_id":      chunk.doc_id,
            "text":        chunk.text,
            "vector":      np.array(emb, dtype=np.float16).tolist(),
            "source_path": chunk_meta.get("source_path", ""),
            "file_name":   chunk_meta.get("file_name", ""),
            "format":      chunk_meta.get("format", ""),
            "created_at":  chunk_meta.get("created_at", ""),
            "modified_at": chunk_meta.get("modified_at", ""),
            "section":     chunk_meta.get("section", ""),
            "namespace":   chunk_meta.get("namespace", ""),
            "parent_id":   chunk_meta.get("parent_id", chunk.chunk_id),
        })

    _, table = _get_table(db_path, dim)
    doc_ids = list({c.doc_id for c in chunks})

    # 2. Snapshot prior consistent state for crash recovery rollback (P0-02)
    backup_rows = []
    for did in doc_ids:
        try:
            safe_did = did.replace("'", "''")
            rows = table.search().where(f"doc_id = '{safe_did}'").limit(10000).to_list()
            if rows:
                backup_rows.extend(rows)
        except Exception:
            pass

    # 3. Delete existing document records
    for did in doc_ids:
        try:
            safe_did = did.replace("'", "''")
            table.delete(f"doc_id = '{safe_did}'")
        except Exception as e:
            err_msg = str(e).lower()
            if "not found" not in err_msg and "does not exist" not in err_msg and "empty" not in err_msg:
                raise RuntimeError(f"Failed to delete existing document vectors for doc_id='{did}': {e}") from e

    # 4. Add new records with crash rollback
    if records:
        try:
            table.add(records)
        except Exception as add_err:
            if backup_rows:
                try:
                    table.add(backup_rows)
                except Exception as rb_err:
                    raise RuntimeError(
                        f"FATAL: table.add failed ({add_err}) AND rollback failed ({rb_err}). Document {doc_ids} is quarantined."
                    ) from add_err
            raise RuntimeError(f"Upsert failed during table.add: {add_err}. Prior state restored.") from add_err

    return len(records)

# ── ANN index tuning ──────────────────────────────────────────────────────────
# IVF_PQ index on documents_1024 (num_partitions=1024, num_sub_vectors=64).
# Measured recall@20 vs exact flat scan on 10 RU engineering queries:
#   nprobes=60 refine=80 → ~94% recall @ ~101ms/q  (flat scan was ~700ms/q).
# Without these params LanceDB defaults give ~56% recall — must be set explicitly.
ANN_NPROBES = 60
ANN_REFINE_FACTOR = 80
MAX_CONTEXT_CHARS = 6000


def _apply_ann_params(query):
    """Apply nprobes/refine_factor when the table has a vector ANN index.

    Safe no-op on builders/versions that don't expose these methods (e.g. a
    store that was never indexed yet), so search keeps working pre-index.
    """
    try:
        query = query.nprobes(ANN_NPROBES)
    except Exception:
        pass
    try:
        query = query.refine_factor(ANN_REFINE_FACTOR)
    except Exception:
        pass
    return query


def build_search_result(
    row: dict,
    parent_text: str | None = None,
    max_context_chars: int = MAX_CONTEXT_CHARS,
) -> dict:
    child_text = row.get("text") or ""
    context_text = parent_text or child_text
    context_source = "parent" if parent_text else "child"
    if max_context_chars > 0 and len(context_text) > max_context_chars:
        context_text = context_text[:max_context_chars]
        if context_source == "parent":
            context_source = "parent_truncated"
        else:
            context_source = "child_truncated"

    raw_score = row.get("_score") or row.get("score")
    raw_dist  = row.get("_distance")
    raw_rel   = row.get("_relevance_score")
    if raw_score is not None:
        score = float(raw_score)
    elif raw_dist is not None:
        score = max(0.0, 1.0 - float(raw_dist))
    elif raw_rel is not None:
        score = float(raw_rel)
    else:
        score = 0.0

    p_id = row.get("parent_id")
    return {
        "chunk_id":       row["chunk_id"],
        "parent_id":      p_id or row["chunk_id"],
        "doc_id":         row["doc_id"],
        "text":           context_text,
        "child_text":     child_text,
        "context_source": context_source,
        "context_chars":  len(context_text),
        "source_path":    row["source_path"],
        "file_name":      row["file_name"],
        "section":        row["section"],
        "score":          round(score, 4),
    }


def search(
    db_path: Path,
    query_embedding: list[float] | None = None,
    top_k: int = 5,
    folder_filter: str | None = None,
    query_text: str | None = None,
    hybrid: bool = True,
    dataset: str | None = None,
    alpha: float = 0.7,
    trace: dict | None = None,
    meta_path: Path | None = None,
) -> list[dict]:
    """Search the store. When ``trace`` is given it is filled with what actually ran.

    Routing rules:
      - alpha == 0.0: Pure FTS search via LanceDB/Tantivy. No embeddings or vector search.
                      Does NOT fallback to vector search if FTS fails (strictly reports degradation).
      - alpha == 1.0 or not (hybrid and query_text): Pure dense vector search (skips FTS).
      - 0.0 < alpha < 1.0 (hybrid): Combined dense vector + FTS with reranker.
    """
    dim = len(query_embedding) if query_embedding is not None else None
    _, table = _get_table(db_path, dim)
    vec = np.array(query_embedding, dtype=np.float16).tolist() if query_embedding is not None else None
    rows = []
    
    def _build_where() -> str | None:
        parts = []
        if folder_filter:
            safe = folder_filter.replace("'", "''")
            if ((":\\" in folder_filter or ":/" in folder_filter or folder_filter.startswith(("\\", "/")))
                and any(folder_filter.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".dwg"])):
                parts.append(f"source_path = '{safe}'")
            else:
                parts.append(f"source_path LIKE '%{safe}%'")
        if dataset:
            safe_ds = dataset.replace("'", "''")
            _path_patterns = {
                "normative": ["Downloaded_GOSTs", "Parsing", "НТД"],
                "project":   ["#_Work", "ПД_PDF"],
            }
            patterns = _path_patterns.get(dataset, [])
            ns_conditions = [f"namespace = '{safe_ds}'"]
            for p in patterns:
                safe_p = p.replace("'", "''")
                ns_conditions.append(f"source_path LIKE '%{safe_p}%'")
            parts.append("(" + " OR ".join(ns_conditions) + ")")
        return " AND ".join(parts) if parts else None
    
    hybrid_requested = bool(hybrid and query_text and 0.0 < alpha < 1.0)
    channels: list[str] = []
    fusion = "none"
    score_kind = "unknown"
    degraded_reason = ""

    # ROUTE 1: Pure FTS (alpha == 0.0)
    if alpha == 0.0:
        if not query_text:
            degraded_reason = "fts_query_text_required"
        else:
            try:
                q = table.search(query_text, query_type="fts").limit(top_k * 4)
                where = _build_where()
                if where:
                    q = q.where(where, prefilter=True)
                rows = q.to_list()
                if rows:
                    channels = ["fts"]
                    fusion = "none"
                    score_kind = "bm25"
                else:
                    degraded_reason = "fts_returned_empty"
            except Exception as e:
                degraded_reason = f"fts_failed: {type(e).__name__}: {e}"
                print(f"[vector_store] pure fts search failed: {e}", file=sys.stderr)
                rows = []

        # Strict requirement: on alpha == 0.0, never fall back to random vector search
        is_real_failure = bool(degraded_reason and degraded_reason != "fts_returned_empty")
        if trace is not None:
            trace["channels"] = list(channels)
            trace["fusion"] = fusion
            trace["score_kind"] = score_kind
            trace["hybrid_requested"] = False
            trace["degraded"] = is_real_failure
            trace["degraded_reason"] = degraded_reason
            trace["status"] = "error" if is_real_failure else ("empty" if not rows else "ok")

        if not rows:
            return []

    # ROUTE 2: Pure Dense Vector Search (alpha == 1.0 or not hybrid)
    elif alpha >= 1.0 or not (hybrid and query_text):
        if vec is None:
            degraded_reason = "dense_query_embedding_required"
            if trace is not None:
                trace["channels"] = []
                trace["fusion"] = "none"
                trace["score_kind"] = "unknown"
                trace["hybrid_requested"] = False
                trace["degraded"] = True
                trace["degraded_reason"] = degraded_reason
            return []

        try:
            q = table.search(vec, vector_column_name="vector").limit(top_k * 4)
            q = _apply_ann_params(q)
            where = _build_where()
            if where:
                q = q.where(where, prefilter=True)
            rows = q.to_list()
            if rows:
                channels = ["dense"]
                fusion = "none"
                score_kind = "dense_similarity"
            else:
                degraded_reason = "dense_returned_empty"
        except Exception as e:
            degraded_reason = f"dense_failed: {type(e).__name__}: {e}"
            print(f"[vector_store] pure dense search failed: {e}", file=sys.stderr)
            rows = []

        if trace is not None:
            trace["channels"] = list(channels)
            trace["fusion"] = fusion
            trace["score_kind"] = score_kind
            trace["hybrid_requested"] = False
            trace["degraded"] = bool(degraded_reason and degraded_reason != "dense_returned_empty")
            trace["degraded_reason"] = degraded_reason

    # ROUTE 3: Hybrid Search (0.0 < alpha < 1.0)
    else:
        if vec is None:
            degraded_reason = "hybrid_query_embedding_required"
            if trace is not None:
                trace["channels"] = []
                trace["fusion"] = "none"
                trace["score_kind"] = "unknown"
                trace["hybrid_requested"] = True
                trace["degraded"] = True
                trace["degraded_reason"] = degraded_reason
            return []

        try:
            reranker, fusion_name, fusion_score_kind = build_fusion_reranker(
                fusion_mode(), alpha
            )
            q = (
                table.search(query_type="hybrid")
                .vector(vec)
                .text(query_text)
                .limit(top_k * 4)
                .rerank(reranker=reranker)
            )
            q = _apply_ann_params(q)
            where = _build_where()
            if where:
                q = q.where(where, prefilter=True)
            rows = q.to_list()
            if rows:
                channels = ["dense", "fts"]
                fusion = fusion_name
                score_kind = fusion_score_kind
            else:
                degraded_reason = "hybrid_returned_empty"
        except Exception as e:
            degraded_reason = f"hybrid_failed: {type(e).__name__}: {e}"
            print(f"[vector_store] hybrid fallback to vector: {e}", file=sys.stderr)
            rows = []

        # Fallback to dense if hybrid failed
        if not rows and vec is not None:
            try:
                q = table.search(vec, vector_column_name="vector").limit(top_k * 4)
                q = _apply_ann_params(q)
                where = _build_where()
                if where:
                    q = q.where(where, prefilter=True)
                rows = q.to_list()
                channels = ["dense"]
                fusion = "none"
                score_kind = "dense_similarity"
            except Exception as e:
                degraded_reason = f"dense_fallback_failed: {e}"

        if trace is not None:
            trace["channels"] = list(channels)
            trace["fusion"] = fusion
            trace["score_kind"] = score_kind
            trace["hybrid_requested"] = True
            trace["degraded"] = bool(channels == ["dense"])
            trace["degraded_reason"] = degraded_reason

    seen_parents = set()
    deduped_rows = []
    for r in rows:
        p_id = r.get("parent_id") or r.get("chunk_id")
        if p_id not in seen_parents:
            seen_parents.add(p_id)
            deduped_rows.append(r)
    
    # The caller knows the authoritative metadata path; fall back to config only
    # when it did not pass one.
    sqlite_path = Path(meta_path) if meta_path else _get_sqlite_path()
    parent_texts = {}
    hydration_error = ""
    if sqlite_path.exists():
        try:
            with sqlite3.connect(sqlite_path) as conn:
                p_ids = [r.get("parent_id") for r in deduped_rows[:top_k] if r.get("parent_id")]
                if p_ids:
                    placeholders = ",".join("?" for _ in p_ids)
                    cursor = conn.execute(
                        f"SELECT parent_id, parent_text FROM parent_chunks WHERE parent_id IN ({placeholders})",
                        p_ids
                    )
                    parent_texts = {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            hydration_error = f"{type(e).__name__}: {e}"
            print(f"[vector_store] Error fetching parents from SQLite: {e}", file=sys.stderr)
    else:
        hydration_error = f"metadata db not found: {sqlite_path}"

    out = []
    for r in deduped_rows[:top_k]:
        p_id = r.get("parent_id")
        parent_text = parent_texts.get(p_id) if p_id else None
        out.append(build_search_result(r, parent_text=parent_text))

    if trace is not None:
        # Serving a child chunk where a parent exists is a real loss of context,
        # so it belongs in the trace rather than only in stderr.
        hydrated = sum(1 for item in out if item["context_source"].startswith("parent"))
        trace["parent_hydration"] = {
            "requested": len(out),
            "hydrated": hydrated,
            "fell_back_to_child": len(out) - hydrated,
            "error": hydration_error,
        }
    return out

def delete_doc(db_path: Path, doc_id: str, dim: int | None = None) -> None:
    if dim is None:
        dim = _DEFAULT_PROVIDER.get_dimension()
    _, table = _get_table(db_path, dim)
    table.delete(f"doc_id = '{doc_id}'")

def delete_source(db_path: Path, source_path: str, dim: int | None = None) -> int:
    if dim is None:
        dim = _DEFAULT_PROVIDER.get_dimension()
    _, table = _get_table(db_path, dim)
    safe = source_path.replace("'", "''")
    table.delete(f"source_path = '{safe}'")
    return 1

def count_chunks(db_path: Path, dim: int | None = None) -> int:
    try:
        if dim is None:
            dim = _DEFAULT_PROVIDER.get_dimension()
        _, table = _get_table(db_path, dim)
        return table.count_rows()
    except Exception:
        return 0
