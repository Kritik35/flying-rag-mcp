from __future__ import annotations
import sys
import sqlite3
from contextlib import closing
from datetime import timedelta
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
    from config_loader import resolve
    config = load_config()
    return resolve(config.get("storage", {}).get("metadata_db", "data/metadata.db"))

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

def get_chunk_vector(db_path: Path, chunk_id: str, dim: int | None = None) -> list[float] | None:
    try:
        if dim is None:
            dim = _DEFAULT_PROVIDER.get_dimension()
        _, table = _get_table(db_path, dim)
        rows = table.search().where(f"chunk_id = '{chunk_id}'").limit(1).to_list()
        if rows:
            return rows[0]["vector"]
    except Exception:
        pass
    return None

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


def _fts_text(query_text: str) -> str:
    """The query as plain terms for the FTS channel.

    Lance reads double quotes as a phrase, and a phrase needs token positions
    the index is built without. People quote codes — "ПВ-01-02" — and each
    such query threw, so the hybrid fell back to the dense channel alone. The
    exact channel in tools already matches identifiers as written.
    """
    return query_text.replace('"', " ")


def _has_fts_index(table) -> bool:
    return any(str(getattr(i, "index_type", "")).upper() == "FTS"
               and "text" in list(getattr(i, "columns", []) or ["text"])
               for i in table.list_indices())


def ensure_fts_index(db_path: Path, dim: int | None = None, rebuild: bool = False) -> bool:
    """Make sure the FTS index exists; build it over the whole store only if asked.

    Every server start and every watcher run used to rebuild it over all 1.4
    million rows. `replace=True` writes the new index beside the old one, and
    the old one stays on disk until its version is pruned — which nothing did:
    70 GB of replaced indices built up in two days. Rows added since the
    index was built are still
    searched (unindexed fragments are scanned), and `refresh_indices` folds
    them in.
    """
    try:
        if dim is None:
            dim = _DEFAULT_PROVIDER.get_dimension()
        _, table = _get_table(db_path, dim)
        if not rebuild and _has_fts_index(table):
            return True
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
        print(f"[vector_store] FTS index built for dim {dim} "
              f"({FTS_LANGUAGE})", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[vector_store] FTS index WARN: {e}", file=sys.stderr)
        return False


def remove_orphan_indices(table_dir: Path, min_age: timedelta = timedelta(hours=1)) -> dict:
    """Delete index directories that no remaining version refers to.

    Pruning versions deletes the files of the indices they referenced but
    leaves their directories, empty, with a fresh mtime (679 of 682 after the
    2026-10-08 cleanup); an interrupted write can leave a full one. A
    directory younger than `min_age` is kept: it may belong to a write whose
    manifest is not committed yet, so the empty ones go on a later run. Call
    under the writer lock.
    """
    import shutil
    import time
    import uuid

    indices, versions = Path(table_dir) / "_indices", Path(table_dir) / "_versions"
    report = {"removed": 0, "bytes": 0, "kept_young": 0}
    if not indices.is_dir() or not versions.is_dir():
        return report
    manifests = b"".join(m.read_bytes() for m in versions.glob("*.manifest"))
    if not manifests:
        return report
    cutoff = time.time() - min_age.total_seconds()
    for entry in indices.iterdir():
        try:
            ident = uuid.UUID(entry.name)
        except ValueError:
            continue
        if ident.bytes in manifests or entry.name.encode() in manifests:
            continue
        if entry.stat().st_mtime > cutoff:
            report["kept_young"] += 1
            continue
        size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        shutil.rmtree(entry)
        report["removed"] += 1
        report["bytes"] += size
    return report


def refresh_indices(db_path: Path, dim: int | None = None,
                    keep: timedelta = timedelta(days=1),
                    orphan_min_age: timedelta = timedelta(hours=1)) -> dict:
    """After a write: fold new rows into the indices, prune old versions and
    the index directories nothing refers to any more. Call under the writer lock.

    Servers open the table afresh on each query, so a day of versions is
    plenty for anyone still reading an older one.
    """
    if dim is None:
        dim = _DEFAULT_PROVIDER.get_dimension()
    _, table = _get_table(db_path, dim)
    if not _has_fts_index(table):
        ensure_fts_index(db_path, dim=dim)
    table.optimize(cleanup_older_than=keep, delete_unverified=False)
    report = remove_orphan_indices(Path(db_path) / f"documents_{dim}.lance",
                                   min_age=orphan_min_age)
    report["orphans_removed"] = report.pop("removed")
    print(f"[vector_store] indices refreshed; removed {report['orphans_removed']} "
          f"unused index dirs ({report['bytes'] / 1e9:.2f} GB)", file=sys.stderr)
    return report


def upsert_chunks(db_path: Path, chunks: list, embeddings: list, dim: int | None = None) -> int:
    if not chunks:
        return 0
    if dim is None:
        if embeddings:
            dim = len(embeddings[0].embedding)
        else:
            dim = _DEFAULT_PROVIDER.get_dimension()
            
    _, table = _get_table(db_path, dim)
    doc_ids = list({c.doc_id for c in chunks})
    for did in doc_ids:
        try:
            table.delete(f"doc_id = '{did}'")
        except Exception:
            pass
            
    records = _vector_records(chunks, embeddings)
    if records:
        table.add(records)
    return len(records)

def _vector_records(chunks: list, embeddings: list) -> list[dict]:
    emb_map = {e.chunk_id: e.embedding for e in embeddings}
    records = []
    for chunk in chunks:
        emb = emb_map.get(chunk.chunk_id)
        if emb is None:
            continue
        records.append({
            "chunk_id":    chunk.chunk_id,
            "doc_id":      chunk.doc_id,
            "text":        chunk.text,
            "vector":      np.array(emb, dtype=np.float16).tolist(),
            "source_path": chunk.metadata.get("source_path", ""),
            "file_name":   chunk.metadata.get("file_name", ""),
            "format":      chunk.metadata.get("format", ""),
            "created_at":  chunk.metadata.get("created_at", ""),
            "modified_at": chunk.metadata.get("modified_at", ""),
            "section":     chunk.metadata.get("section", ""),
            "namespace":   chunk.metadata.get("namespace", ""),
            "parent_id":   chunk.metadata.get("parent_id", chunk.chunk_id),
        })
    return records


def replace_document(db_path: Path, doc_id: str, chunks: list, embeddings: list,
                     dim: int | None = None) -> int:
    """Swap a document's rows for new ones in a single commit.

    `upsert_chunks` deleted the document and then added it back: two commits,
    and a crash or a killed process between them left the document missing
    from search with nothing to say so. A merge-insert keyed on
    (doc_id, chunk_id) that also deletes the document's rows absent from the
    new set is one commit — readers see the old version or the new one.

    Chunk ids must be unique within the document: an ambiguous key is refused
    by LanceDB, and that refusal is preferable to a silent duplicate.
    """
    if dim is None:
        dim = len(embeddings[0].embedding) if embeddings else _DEFAULT_PROVIDER.get_dimension()
    _, table = _get_table(db_path, dim)
    records = _vector_records(chunks, embeddings)
    ids = [r["chunk_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate chunk ids in document {doc_id}")
    if any(r["doc_id"] != doc_id for r in records):
        raise ValueError(f"rows of another document passed for {doc_id}")
    safe = doc_id.replace("'", "''")
    if not records:
        table.delete(f"doc_id = '{safe}'")
        return 0
    (table.merge_insert(["doc_id", "chunk_id"])
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .when_not_matched_by_source_delete(f"doc_id = '{safe}'")
        .execute(records))
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
        # Дата изменения нужна, чтобы из изданий одного листа показывать
        # свежее: номер изменения в имени бывает у старого и отсутствует у
        # нового.
        "modified_at":    row.get("modified_at"),
    }


def _scope_where(folder_filter: str | None, dataset: str | None) -> str | None:
    """Фильтр области поиска: папка и/или датасет."""
    parts = []
    if folder_filter:
        safe = folder_filter.replace("'", "''")
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


# Сколько строк забирать сканом подстроки. Код помещения встречается в
# сотнях фрагментов (291 для одного кода, 668 для четырёх на живом индексе),
# а порядок внутри найденного задаётся уже после скана — значит, обрезка
# до ранжирования может потерять лучшие фрагменты. Скан подстроки читает
# колонку целиком при любом пределе (0.25 с и на 600, и на 20 000 строк),
# так что предел — только про память: 5000 строк с векторами — около 10 МБ.
EXACT_SCAN_LIMIT = 5000


OCCURRENCE_SNIPPET = 160


def find_occurrences(db_path: Path, needle: str, *, folder_filter: str | None = None,
                     dataset: str | None = None, dim: int | None = None) -> list[dict]:
    """Every fragment that contains `needle` as a whole token, in corpus order.

    Search answers "what is most relevant" and stops at top-k; an audit asks
    "where does П1-TRF-01-01 occur — all of it". This is a full scan of the
    text column (a quarter of a second on 1.4M rows), case-insensitive, with
    the same boundary rule as the exact channel, so "П1-TRF-01-01" does not
    match inside "П1-TRF-01-012".
    """
    from rag_server.query_shape import _contains_whole

    needle = " ".join(str(needle or "").split())
    if not needle:
        return []
    if dim is None:
        dim = _DEFAULT_PROVIDER.get_dimension()
    _, table = _get_table(db_path, dim)
    low = needle.casefold()
    # Wildcards in the needle only widen the scan; the boundary check below
    # decides what counts.
    where = "lower(text) LIKE '%" + low.replace("'", "''") + "%'"
    scope = _scope_where(folder_filter, dataset)
    if scope:
        where = f"{where} AND {scope}"
    rows = (table.search().where(where)
            .select(["chunk_id", "source_path", "file_name", "section", "text"])
            .limit(table.count_rows() + 1).to_list())
    found = []
    for r in rows:
        text = " ".join(str(r.get("text") or "").split())
        if not _contains_whole(text.casefold(), low):
            continue
        at = text.casefold().find(low)
        half = OCCURRENCE_SNIPPET // 2
        start = max(0, at - half)
        snippet = ("…" if start else "") + text[start:at + len(needle) + half] + \
                  ("…" if at + len(needle) + half < len(text) else "")
        found.append({"source_path": r.get("source_path", ""),
                      "file_name": r.get("file_name", ""),
                      "section": r.get("section", ""),
                      "chunk_id": r.get("chunk_id", ""),
                      "snippet": snippet})
    found.sort(key=lambda f: (f["source_path"], f["chunk_id"]))
    return found


def search_exact(db_path: Path, query_embedding: list[float], codes: list[str],
                 top_k: int = 20, folder_filter: str | None = None,
                 dataset: str | None = None, meta_path: Path | None = None,
                 dim: int | None = None, trace: dict | None = None) -> list[dict]:
    """Фрагменты, где шифр запроса написан ровно, — отдельным каналом.

    Полнотекстовый канал режет «П1-TRF-01-01» на токены п1/trf/01/01, и
    фрагменты, где этих токенов много, вытесняли точные совпадения из пула: на
    живом индексе из 135 фрагментов с кодом в пул попадало 32, а в пятёрке не
    было ни одного. Здесь — скан подстроки по всем шифрам одним проходом,
    проверка границ тем же правилом, что у exact_hits, и порядок: сначала по
    числу шифров запроса во фрагменте, затем по близости к вектору запроса.
    """
    codes = [c for c in codes if c]
    if not codes:
        return []
    from rag_server.query_shape import _contains_whole

    if dim is None:
        dim = len(query_embedding)
    _, table = _get_table(db_path, dim)
    like = " OR ".join(
        "text LIKE '%" + c.replace("'", "''") + "%'" for c in codes)
    where = f"({like})"
    scope = _scope_where(folder_filter, dataset)
    if scope:
        where = f"{where} AND {scope}"
    rows = table.search().where(where).limit(EXACT_SCAN_LIMIT).to_list()

    q = np.asarray(query_embedding, dtype=np.float32)
    qn = float(np.linalg.norm(q)) or 1.0
    ranked = []
    for r in rows:
        haystack = " ".join(str(r.get("text") or "").split()).casefold()
        hits = sum(1 for c in codes if _contains_whole(haystack, c.casefold()))
        if not hits:
            continue
        v = np.asarray(r.get("vector") or [], dtype=np.float32)
        sim = float(v @ q / ((float(np.linalg.norm(v)) or 1.0) * qn)) if v.size == q.size else 0.0
        r = dict(r)
        r["_score"] = max(0.0, min(1.0, sim))
        ranked.append((hits, sim, r))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if trace is not None:
        trace["exact_scanned"] = len(rows)
        trace["exact_matched"] = len(ranked)
        # Упёрлись в предел — часть совпадений не рассмотрена; молчать нельзя.
        trace["exact_truncated"] = len(rows) >= EXACT_SCAN_LIMIT
    return _finalize([r for _h, _s, r in ranked], top_k, meta_path, None)


def search(
    db_path: Path,
    query_embedding: list[float],
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

    A hybrid query that falls back to the dense channel is a *degraded* search,
    not a hybrid one, and the trace has to say so — otherwise a broken FTS index
    is indistinguishable from a healthy contour from the outside.
    """
    dim = len(query_embedding)
    _, table = _get_table(db_path, dim)
    vec = np.array(query_embedding, dtype=np.float16).tolist()
    rows = []
    
    def _build_where() -> str | None:
        return _scope_where(folder_filter, dataset)
    
    hybrid_requested = bool(hybrid and query_text)
    channels: list[str] = []
    fusion = "none"
    score_kind = "unknown"
    degraded_reason = ""

    if hybrid_requested:
        try:
            reranker, fusion_name, fusion_score_kind = build_fusion_reranker(
                fusion_mode(), alpha
            )
            q = (
                table.search(query_type="hybrid")
                .vector(vec)
                .text(_fts_text(query_text))
                .limit(top_k * 4)
                .rerank(reranker=reranker)
            )
            q = _apply_ann_params(q)
            where = _build_where()
            if where:
                # Pre-filter, like the dense fallback below. Post-filtering took
                # candidates globally and then applied the scope to what came
                # back, so a narrow scope kept almost nothing: on the live index
                # `source_path LIKE '%ОВ2%'` returned 5 rows of 48, and a single
                # named norm returned 1. Silently, too — a handful of rows is
                # still rows, so the trace called it a healthy hybrid.
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

    if not rows:
        q = table.search(vec, vector_column_name="vector").limit(top_k * 4)
        q = _apply_ann_params(q)
        where = _build_where()
        if where:
            q = q.where(where, prefilter=True)
        rows = q.to_list()
        channels = ["dense"]
        fusion = "none"
        score_kind = "dense_similarity"

    if trace is not None:
        trace["channels"] = list(channels)
        trace["fusion"] = fusion
        trace["score_kind"] = score_kind
        trace["hybrid_requested"] = hybrid_requested
        # A hybrid request served by one channel is degraded, and must not be
        # reported as a successful hybrid.
        trace["degraded"] = bool(hybrid_requested and channels == ["dense"])
        trace["degraded_reason"] = degraded_reason

    return _finalize(rows, top_k, meta_path, trace)


def _finalize(rows: list, top_k: int, meta_path, trace: dict | None) -> list[dict]:
    """Дедуп по родителю, подтягивание родительского текста, форма результата.

    Общая для обычного и точного каналов: точный канал без неё отдавал бы
    куски без контекста, и реранкер с моделью видели бы обрывки таблиц.
    """
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
            # closing(): в sqlite3 `with connect()` только фиксирует
            # транзакцию, а соединение живёт до сборщика мусора — и на
            # Windows держит файл открытым, пока тот не придёт.
            with closing(sqlite3.connect(sqlite_path)) as conn:
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
