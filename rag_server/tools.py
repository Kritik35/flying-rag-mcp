from __future__ import annotations
import sys
import threading
from pathlib import Path
import yaml
import os

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _cfg() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _db_paths() -> tuple[Path, Path]:
    cfg = _cfg()
    return (
        ROOT / cfg["storage"]["lancedb_path"],
        ROOT / cfg["storage"]["metadata_db"],
    )


def build_reindex_command(
    python_exe: str,
    indexer_script: str,
    target: Path,
    force: bool = False,
    use_cache: bool = True,
) -> list[str]:
    command = [python_exe, indexer_script]
    if force:
        command.append("--force")
    if not use_cache:
        command.append("--no-cache")
    command.append(str(target))
    return command


def build_search_scope_key(
    dataset: str | None,
    folder_filter: str | None,
    alpha: float,
    model_name: str,
    route: str | None = None,
) -> str:
    return (
        f"{model_name}|retrieval-quality-v9-routed|{route or ''}|"
        f"{dataset or ''}|{folder_filter or ''}|{alpha}"
    )


# Deterministic weak-retrieval retry augmentations per route (no LLM).
_RETRY_AUGMENT = {
    "project_ov2": "ОВ2 ПВ ДВ противодымная вентиляция дымоудаление подпор воздуха",
    "normative_fire": "СП 7.13130 противодымная вентиляция дымоудаление подпор вытяжная приточная",
    "normative_hvac": "СП 60.13330 отопление вентиляция кондиционирование воздухообмен микроклимат утилизация теплоты",
}

def auto_rerank_enabled() -> bool:
    cfg = _cfg()
    return bool(cfg.get("retrieval", {}).get("auto_rerank", False))


def search_documents(
    query: str,
    folder_filter: str | None = None,
    top_k: int = 5,
    dataset: str | None = None,
    rerank: bool | None = None,
    alpha: float = 0.7,
    use_cache: bool = True,
    debug: bool = False,
) -> list[dict] | dict:
    from embedder.client import _DEFAULT_PROVIDER, get_embeddings
    from storage.vector_store import search
    from storage.semantic_cache import SemanticCache
    from rag_server.query_planner import fuse_ranked_results, plan_query
    from rag_server.retrieval_quality import apply_retrieval_quality
    from rag_server.rerank_policy import decide_rerank
    from rag_server.query_router import route_query
    from storage.source_focus import concentrate_sources

    lance_path, meta_path = _db_paths()
    top_k = max(1, min(top_k, 20))

    cache = SemanticCache(db_path=str(meta_path))
    auto_rerank = auto_rerank_enabled()

    try:
        # ── deterministic scope routing (explicit args always win) ──────────
        route = route_query(
            query, explicit_dataset=dataset, explicit_folder_filter=folder_filter
        )
        applied_dataset = route.dataset
        applied_folder = route.folder_filter

        scope_key = build_search_scope_key(
            applied_dataset, applied_folder, alpha,
            _DEFAULT_PROVIDER.get_model_name(), route=route.route,
        )
        if auto_rerank:
            scope_key += "|auto-rerank"

        # Core retrieval, reusable for the weak-retrieval retry.
        def _execute(effective_query: str):
            plan = plan_query(effective_query, dataset=applied_dataset)
            query_texts = plan.queries
            vecs = get_embeddings(query_texts, is_query=True)
            pool_size = max(top_k * 8, 30)
            per_query_pool = max(12, pool_size // max(1, len(query_texts) - 1))

            def _one(pair):
                qt, qv = pair
                return search(
                    lance_path, qv, top_k=per_query_pool,
                    folder_filter=applied_folder, query_text=qt,
                    hybrid=True, dataset=applied_dataset, alpha=alpha,
                )

            pairs = list(zip(query_texts, vecs))
            if len(pairs) == 1:
                result_lists = [_one(pairs[0])]
            else:
                # Subquery searches are independent reads — run them concurrently
                # (each was ~400ms serial; LanceDB handles concurrent reads).
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=min(4, len(pairs))) as ex:
                    result_lists = list(ex.map(_one, pairs))
            results = (
                result_lists[0]
                if len(result_lists) == 1
                else fuse_ranked_results(result_lists, limit=pool_size)
            )
            quality_pool = apply_retrieval_quality(
                effective_query, results, dataset=applied_dataset,
                top_k=max(top_k * 4, top_k), max_per_doc=2,
            )
            decision = decide_rerank(
                explicit_rerank=rerank, auto_enabled=auto_rerank,
                plan=plan, quality_pool=quality_pool, top_k=top_k,
            )
            if decision.apply and len(quality_pool) > top_k:
                try:
                    from rag_server.reranker import rerank_sync
                    quality_pool = rerank_sync(effective_query, quality_pool, top_k=top_k)
                except Exception as re_err:
                    print(f"[tools] reranker skipped: {re_err}", file=sys.stderr)
                    quality_pool = quality_pool[:top_k]
            focused = concentrate_sources(quality_pool, max_docs=3, min_score=0.30, query=None)
            final = (focused if focused else quality_pool)[:top_k]
            return final, plan, decision

        # Embedding for cache key uses the original query (stable across retries).
        primary_embedding = get_embeddings([query], is_query=True)[0]

        cache_hit = False
        if use_cache and not debug and rerank is not True:
            hit = cache.lookup(query, primary_embedding, scope_key=scope_key)
            if hit:
                print(
                    f"[tools] cache hit sim={hit.similarity:.3f} age={hit.age_seconds:.0f}s",
                    file=sys.stderr,
                )
                return hit.results[:top_k]

        final, plan, rerank_decision = _execute(query)

        # ── CRAG: grade retrieval; correct once if warranted (no LLM) ───────
        from rag_server.crag import grade_retrieval
        verdict = grade_retrieval(query, final, route, top_k)
        crag_corrected = False
        if verdict.needs_correction and route.route in _RETRY_AUGMENT:
            retry_query = f"{query} {_RETRY_AUGMENT[route.route]}"
            retry_final, retry_plan, retry_decision = _execute(retry_query)
            retry_verdict = grade_retrieval(query, retry_final, route, top_k)
            better = (
                retry_verdict.confidence > verdict.confidence
                or (retry_final and not final)
            )
            if better:
                final, plan, rerank_decision = retry_final, retry_plan, retry_decision
                verdict = retry_verdict
                crag_corrected = True
                print(
                    f"[tools] CRAG correction applied verdict={verdict.label} "
                    f"conf={verdict.confidence:.2f}",
                    file=sys.stderr,
                )

        if use_cache and not debug and final and rerank_decision.reason != "forced":
            cache.store(query, primary_embedding, final, scope_key=scope_key)

        if not debug:
            return final

        trace = {
            "route": route.route,
            "reason": route.reason,
            "confidence": route.confidence,
            "matched_terms": list(route.matched_terms),
            "inferred_dataset": route.inferred_dataset,
            "inferred_folder_filter": route.inferred_folder_filter,
            "applied_dataset": applied_dataset,
            "applied_folder_filter": applied_folder,
            "ambiguous": route.ambiguous,
            "subqueries": list(plan.queries),
            "rerank": {"applied": rerank_decision.apply, "reason": rerank_decision.reason},
            "crag": {
                "verdict": verdict.label,
                "confidence": verdict.confidence,
                "reason": verdict.reason,
                "corrected": crag_corrected,
            },
            "cache_hit": cache_hit,
        }
        if route.structured:
            trace["structured_hint"] = {
                "tool": "extract_structured_values",
                "suggested_label": route.structured_label,
                "reason": "query matched structured_table terms",
            }
        return {"debug": trace, "results": final}
    except Exception as e:
        if debug:
            return {"debug": {"error": str(e)}, "results": []}
        return [{"error": str(e)}]


def search_rules(
    query: str,
    subject: str | None = None,
    parameter: str | None = None,
    limit: int = 10,
) -> list[dict]:
    _, meta_path = _db_paths()
    import sqlite3
    if not meta_path.exists():
        return []
    try:
        with sqlite3.connect(meta_path) as conn:
            conn.row_factory = sqlite3.Row
            where = []
            params = []
            if query:
                where.append("(rule_text LIKE ? OR subject LIKE ? OR parameter LIKE ?)")
                q_wild = f"%{query}%"
                params.extend([q_wild, q_wild, q_wild])
            if subject:
                where.append("subject LIKE ?")
                params.append(f"%{subject}%")
            if parameter:
                where.append("parameter LIKE ?")
                params.append(f"%{parameter}%")
            
            sql = "SELECT * FROM engineering_rules"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        return [{"error": str(e)}]


def extract_structured_values(
    label: str,
    source_like: str | None = None,
    limit: int = 500,
    max_rows: int = 50,
) -> dict:
    """Extract label/value pairs from already indexed parent chunks."""
    import sqlite3
    from structured_values.extractor import extract_labeled_values

    _lance_path, meta_path = _db_paths()
    if not meta_path.exists():
        return {"error": f"Metadata DB not found: {meta_path}"}

    limit = max(1, min(int(limit), 5000))
    max_rows = max(1, min(int(max_rows), 500))
    label = str(label or "").strip()
    if not label:
        return {"error": "label is required"}

    # SQLite LIKE is not case-insensitive for Cyrillic, so pre-filter on a few
    # case variants of the label (the Python extractor below casefolds anyway).
    variants = list(dict.fromkeys([label, label.lower(), label.upper(), label.capitalize()]))
    where = ["(" + " OR ".join("parent_text LIKE ?" for _ in variants) + ")"]
    params: list[str | int] = [f"%{v}%" for v in variants]
    if source_like:
        where.append("source_path LIKE ?")
        params.append(f"%{source_like}%")
    params.append(limit)

    sql = f"""
        SELECT source_path, parent_text
        FROM parent_chunks
        WHERE {' AND '.join(where)}
        LIMIT ?
    """

    rows = []
    scanned_chunks = 0
    conn = sqlite3.connect(meta_path)
    try:
        for source_path, parent_text in conn.execute(sql, params).fetchall():
            scanned_chunks += 1
            for item in extract_labeled_values(str(parent_text), labels=[label]):
                rows.append(
                    {
                        "record": item.record,
                        "label": item.label,
                        "value": item.value,
                        "unit": item.unit,
                        "confidence": item.confidence,
                        "evidence": item.evidence,
                        "line_no": item.line_no,
                        "source_path": str(source_path),
                    }
                )
    finally:
        conn.close()

    return {
        "summary": {
            "label": label,
            "source_like": source_like or "",
            "scanned_parent_chunks": scanned_chunks,
            "total_rows": len(rows),
            "returned_rows": min(len(rows), max_rows),
            "note": "Heuristic extraction from indexed parent chunks; verify critical rows against source files.",
        },
        "rows": rows[:max_rows],
    }


def graph_neighbors(doc_id: str, top_k: int = 5) -> list[dict]:
    from storage.graph import get_neighbors, get_graph_stats
    _, meta_path = _db_paths()
    try:
        neighbors = get_neighbors(meta_path, doc_id, top_k)
        if not neighbors:
            stats = get_graph_stats(meta_path)
            total_edges = stats.get('edges', 0)
            if total_edges == 0:
                msg = "Graph is empty. Reindex files to build graph."
            else:
                msg = f"No connections for this document (total edges: {total_edges})."
            return [{"info": msg}]
        return neighbors
    except Exception as e:
        return [{"error": str(e)}]


def list_indexed(folder_filter: str | None = None, limit: int = 50,
                 dataset: str | None = None) -> dict:
    from storage.metadata_db import list_files
    _, meta_path = _db_paths()
    try:
        all_files = list_files(meta_path, folder_filter=folder_filter, dataset=dataset)
        total = len(all_files)
        total_chunks = sum(f.get("chunk_count", 0) for f in all_files)
        page = [
            {k: f[k] for k in ("file_name", "format", "chunk_count", "status")}
            for f in all_files[:limit]
        ]
        return {
            "summary": {
                "total_files": total,
                "total_chunks": total_chunks,
                "showing": len(page),
                "filter": folder_filter or "all",
            },
            "files": page,
            "hint": f"Showing first {limit} of {total}." if total > limit else "",
        }
    except Exception as e:
        return {"error": str(e)}


def reindex_path(path: str, force: bool = False, use_cache: bool = True) -> dict:
    import subprocess
    import uuid
    from storage.metadata_db import create_reindex_job

    target = Path(path)
    if not target.exists():
        return {"status": "error", "message": f"Not found: {path}"}

    job_id = uuid.uuid4().hex[:8]
    indexer = ROOT / "indexer.py"
    _lance_path, meta_path = _db_paths()
    log_dir = ROOT / "storage"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"reindex_{job_id}.log"
    err_path = log_dir / f"reindex_{job_id}.err.log"
    env = os.environ.copy()
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env["PYTHONIOENCODING"] = "utf-8"

    CREATE_NO_WINDOW = 0x08000000
    stdout_handle = log_path.open("w", encoding="utf-8", errors="replace")
    stderr_handle = err_path.open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            build_reindex_command(sys.executable, str(indexer), target, force=force, use_cache=use_cache),
            stderr=stderr_handle,
            stdout=stdout_handle,
            creationflags=CREATE_NO_WINDOW,
            cwd=str(ROOT),
            env=env,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    create_reindex_job(meta_path, job_id, str(target), proc.pid, force, use_cache, str(log_path))
    print(f"[reindex] job={job_id} pid={proc.pid} path={target}", file=sys.stderr)

    return {
        "status": "started",
        "job_id": job_id,
        "pid": proc.pid,
        "path": str(target),
        "force": force,
        "use_cache": use_cache,
        "log_path": str(log_path),
        "err_path": str(err_path),
        "message": "Indexing started in background.",
    }


def reindex_status(job_id: str | None = None, limit: int = 20) -> dict:
    from storage.metadata_db import get_reindex_job, list_reindex_jobs

    _lance_path, meta_path = _db_paths()
    try:
        if job_id:
            job = get_reindex_job(meta_path, job_id)
            return {"job": job} if job else {"error": f"Unknown job_id: {job_id}"}
        return {"jobs": list_reindex_jobs(meta_path, limit=limit)}
    except Exception as e:
        return {"error": str(e)}


def get_tool_definitions() -> list[dict]:
    return [
        {
            "name": "search_documents",
            "description": "Semantic search over documents (GOST, SP, PD, IFC).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query":         {"type": "string",  "description": "Search query"},
                    "folder_filter": {"type": "string",  "description": "Filter by folder path (optional)"},
                    "top_k":         {"type": "number",  "description": "Number of results (1-20)"},
                    "dataset":       {"type": "string",  "description": "Dataset name (optional)"},
                    "rerank":        {
                        "type": ["boolean", "null"],
                        "description": "Enable LLM reranking: true=force, false=off, null/omitted=auto by config",
                    },
                    "alpha":         {"type": "number",  "description": "Vector search weight (optional, default 0.7)"},
                    "use_cache":     {"type": "boolean", "description": "Use semantic query cache (optional, default true)"},
                    "debug":         {"type": "boolean", "description": "Return routing/retrieval debug trace (optional, default false)"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "search_rules",
            "description": "Search extracted engineering compliance rules.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query":     {"type": "string", "description": "Search query"},
                    "subject":   {"type": "string", "description": "Subject filter (optional)"},
                    "parameter": {"type": "string", "description": "Parameter filter (optional)"},
                    "limit":     {"type": "number", "description": "Max results (optional, default 10)"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "list_indexed",
            "description": "Get status and file counts in RAG database.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "folder_filter": {"type": "string", "description": "Folder filter (optional)"},
                    "limit":         {"type": "number", "description": "Limit results (optional, default 50)"},
                    "dataset":       {"type": "string", "description": "Dataset name (optional)"},
                },
            },
        },
        {
            "name": "graph_neighbors",
            "description": "Find semantically related documents in graph.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID"},
                    "top_k":  {"type": "number",  "description": "Number of neighbors (optional, default 5)"},
                },
                "required": ["doc_id"],
            },
        },
        {
            "name": "extract_structured_values",
            "description": "Extract structured label/value pairs from indexed parent chunks (for vertical tables and technical sheets).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Parameter label to extract, e.g. Дорегулирование or Потеря давления"},
                    "source_like": {"type": "string", "description": "Optional source_path substring filter"},
                    "limit": {"type": "number", "description": "Max parent chunks to scan (optional, default 500)"},
                    "max_rows": {"type": "number", "description": "Max extracted rows to return (optional, default 50)"},
                },
                "required": ["label"],
            },
        },
        {
            "name": "reindex_path",
            "description": "Reindex a file or directory in background.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to file/directory"},
                    "force": {"type": "boolean", "description": "Ignore SHA skip (optional)"},
                    "use_cache": {"type": "boolean", "description": "Reuse cached chunk vectors (optional, default true)"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "reindex_status",
            "description": "Get recent reindex jobs or one job by id.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id (optional)"},
                    "limit": {"type": "number", "description": "Number of recent jobs (optional, default 20)"},
                },
            },
        },
    ]
