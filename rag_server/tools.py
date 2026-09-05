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
    from config_loader import require_config
    return require_config()


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
    corpus_generation: str = "",
) -> str:
    return (
        f"{model_name}|corpus:{corpus_generation}|retrieval-quality-v9-routed|{route or ''}|"
        f"{dataset or ''}|{folder_filter or ''}|{alpha}"
    )


def _filter_visual_hits(
    hits: list[dict],
    meta_path: Path,
    dataset: str | None = None,
    folder_filter: str | None = None,
) -> list[dict]:
    filtered = list(hits)
    if folder_filter:
        needle = folder_filter.casefold()
        filtered = [
            h for h in filtered
            if needle in str(h.get("source_path", "")).casefold()
        ]
    if dataset and filtered:
        import sqlite3

        paths = [str(h.get("source_path", "")) for h in filtered if h.get("source_path")]
        if not paths or not meta_path.exists():
            return []
        placeholders = ",".join("?" for _ in paths)
        con = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True, timeout=10)
        try:
            rows = con.execute(
                f"SELECT source_path FROM files WHERE dataset = ? AND source_path IN ({placeholders})",
                [dataset] + paths,
            ).fetchall()
            allowed = {r[0] for r in rows}
        finally:
            con.close()
        filtered = [h for h in filtered if h.get("source_path") in allowed]
    return filtered


# Deterministic weak-retrieval retry augmentations per route (no LLM).
_RETRY_AUGMENT = {
    "project_ov2": "ОВ2 ПВ ДВ противодымная вентиляция дымоудаление подпор воздуха",
    "normative_fire": "СП 7.13130 противодымная вентиляция дымоудаление подпор вытяжная приточная",
    "normative_hvac": "СП 60.13330 отопление вентиляция кондиционирование воздухообмен микроклимат утилизация теплоты",
}

def auto_rerank_enabled() -> bool:
    cfg = _cfg()
    return bool(cfg.get("retrieval", {}).get("auto_rerank", False))


def blocked_result(
    error_code: str,
    detail: str,
    action: str,
    debug: bool = False,
) -> list[dict] | dict:
    """A retrieval the contour refuses to serve, stated as a result.

    Returning zero hits would be indistinguishable from "nothing matched", so a
    blocked search carries its machine-readable code and the operator action
    that clears it.
    """
    payload = {
        "error": detail,
        "error_code": error_code,
        "status": "blocked",
        "action": action,
    }
    if debug:
        return {"debug": {"status": "blocked", "error_code": error_code,
                          "reason": detail, "action": action},
                "results": []}
    return [payload]


# How many named norms get their own restricted read, and how deep. The guard
# is one ranked list among the subqueries, so its influence stays bounded.
#
# Off by default, and that is a measurement rather than caution. On the golden
# set the guard is a large win when the cross-encoder is not in play and a loss
# when it is:
#
#     guard off, rerank off   hit@5 0.4545   mrr 0.2576   passed 5/11
#     guard on,  rerank off   hit@5 0.7273   mrr 0.4242   passed 8/11
#     guard off, rerank on    hit@5 0.8182   mrr 0.4621   passed 6/11
#     guard on,  rerank on    hit@5 0.6364   mrr 0.4167   passed 6/11
#
# The guard puts the named document's own passages in the pool; the reranker
# then judges them on their own merit and drops them, because being from the
# right document is not the same as answering the question. Two mechanisms
# solving the same problem, and together they are worse than either alone.
# Useful where the reranker is unavailable — it was returning 500 for an
# unknown length of time before this session.
NAMED_NORM_LIMIT = 3
NAMED_NORM_DEPTH = 12


def fill_to_top_k(focused: list[dict], pool: list[dict], top_k: int) -> list[dict]:
    """Keep the concentrated head, then top up from the pool to `top_k`.

    Source concentration used to run on a list that had already been cut to
    top_k, so it could only remove: 15 of 16 measured queries came back short of
    what was asked. Concentration still decides what leads; the remainder keeps
    retrieval order below it instead of turning into missing results.
    """
    final = list(focused[:top_k])
    if len(final) >= top_k:
        return final
    seen = {c.get("chunk_id") or id(c) for c in final}
    for candidate in pool:
        if len(final) >= top_k:
            break
        marker = candidate.get("chunk_id") or id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        final.append(candidate)
    return final


def subquery_pool_size(pool_size: int, subquery_count: int) -> int:
    """How deep each subquery reads.

    The budget used to be divided by (subquery_count - 1), so recall per
    subquery fell as the query plan grew richer — backwards, since RRF needs
    each list deep enough to have something to fuse. Subquery reads are
    concurrent and cheap; give each one the full budget.
    """
    return max(24, int(pool_size))


def merge_search_traces(sub_traces: list[dict], subquery_count: int) -> dict:
    """Fold per-subquery store traces into one honest retrieval trace."""
    channels: list[str] = []
    for sub in sub_traces:
        for channel in sub.get("channels", []):
            if channel not in channels:
                channels.append(channel)
    degraded = [s for s in sub_traces if s.get("degraded")]
    # Several subqueries are fused by RRF; a single one keeps whatever the store
    # channel produced.
    if subquery_count > 1:
        fusion, score_kind = "rrf", "rrf"
    elif sub_traces:
        fusion = sub_traces[0].get("fusion", "none")
        score_kind = sub_traces[0].get("score_kind", "unknown")
    else:
        fusion, score_kind = "none", "unknown"
    # Parent hydration is part of retrieval health: serving child chunks where
    # parents exist quietly strips context down to 150 tokens.
    hydrated = sum(s.get("parent_hydration", {}).get("hydrated", 0) for s in sub_traces)
    fell_back = sum(
        s.get("parent_hydration", {}).get("fell_back_to_child", 0) for s in sub_traces
    )
    hydration_errors = [
        s["parent_hydration"]["error"]
        for s in sub_traces
        if s.get("parent_hydration", {}).get("error")
    ]
    return {
        "channels": channels,
        "fusion": fusion,
        "score_kind": score_kind,
        "subqueries": subquery_count,
        "degraded": bool(degraded),
        "degraded_reason": degraded[0].get("degraded_reason", "") if degraded else "",
        "degraded_subqueries": len(degraded),
        "parent_hydration": {
            "hydrated": hydrated,
            "fell_back_to_child": fell_back,
            "error": hydration_errors[0] if hydration_errors else "",
        },
    }


def search_documents(
    query: str,
    folder_filter: str | None = None,
    top_k: int = 5,
    dataset: str | None = None,
    rerank: bool | None = None,
    alpha: float = 0.7,
    use_cache: bool = True,
    debug: bool = False,
    include_visual: bool = False,
) -> list[dict] | dict:
    from embedder.client import _DEFAULT_PROVIDER, get_embeddings
    from storage.vector_store import search
    from storage.semantic_cache import SemanticCache
    from storage.metadata_db import get_corpus_generation
    from rag_server.query_planner import fuse_ranked_results, plan_query
    from rag_server.retrieval_quality import apply_retrieval_quality
    from rag_server.rerank_policy import decide_rerank
    from rag_server.named_norms import extract_norm_designations
    from rag_server.query_router import route_query
    from storage.source_focus import concentrate_sources

    lance_path, meta_path = _db_paths()
    top_k = max(1, min(top_k, 20))

    corpus_generation = str(get_corpus_generation(meta_path))
    focus_max_docs = max(1, int((_cfg().get("retrieval") or {}).get("focus_max_docs", 3)))
    named_norm_guard = bool((_cfg().get("retrieval") or {}).get("named_norm_guard", False))
    cache = SemanticCache(db_path=str(meta_path), corpus_generation=corpus_generation)
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
            corpus_generation=corpus_generation,
        )
        if auto_rerank:
            scope_key += "|auto-rerank"

        # Core retrieval, reusable for the weak-retrieval retry.
        def _execute(
            effective_query: str,
            use_hyde: bool = False,
            first_embedding: list[float] | None = None,
        ):
            plan = plan_query(
                effective_query, dataset=applied_dataset, route=route.route
            )
            query_texts = list(plan.queries)
            # HyDE (config hyde.enabled): generate a hypothetical answer passage
            # and add it as an extra query vector. Only on the weak-retrieval
            # retry (use_hyde) so normal queries pay no LLM latency.
            if use_hyde:
                try:
                    from rag_server.hyde import is_enabled as _hyde_on, generate_hypothetical
                    if _hyde_on():
                        hypo = generate_hypothetical(effective_query)
                        if hypo:
                            query_texts.append(hypo)
                except Exception as _hyde_err:
                    print(f"[tools] hyde skipped: {_hyde_err}", file=sys.stderr)
            if first_embedding is not None and query_texts and query_texts[0] == effective_query:
                vecs = [first_embedding]
                if len(query_texts) > 1:
                    vecs.extend(get_embeddings(query_texts[1:], is_query=True))
            else:
                vecs = get_embeddings(query_texts, is_query=True)
            pool_size = max(top_k * 8, 30)
            per_query_pool = subquery_pool_size(pool_size, len(query_texts))

            def _one(pair):
                qt, qv = pair
                sub_trace: dict = {}
                rows = search(
                    lance_path, qv, top_k=per_query_pool,
                    folder_filter=applied_folder, query_text=qt,
                    hybrid=True, dataset=applied_dataset, alpha=alpha,
                    trace=sub_trace, meta_path=meta_path,
                )
                return rows, sub_trace

            pairs = list(zip(query_texts, vecs))
            if len(pairs) == 1:
                paired = [_one(pairs[0])]
            else:
                # Subquery searches are independent reads — run them concurrently
                # (each was ~400ms serial; LanceDB handles concurrent reads).
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=min(4, len(pairs))) as ex:
                    paired = list(ex.map(_one, pairs))
            result_lists = [rows for rows, _ in paired]
            sub_traces = [sub for _, sub in paired]

            # Exact guard for a norm the plan names outright. A designation is
            # document identity and the lexical channel reads chunk text, so
            # "СП 484.1311500" retrieved the 93 documents that cite it and not
            # the norm itself — it sat at rank 40 for a query spelling out its
            # number. One extra read restricted to that document puts its own
            # best passages in the pool; fusion still decides where they land.
            # Skipped when the caller scoped the search themselves.
            named = (
                extract_norm_designations(" ".join(query_texts))[:NAMED_NORM_LIMIT]
                if named_norm_guard and not folder_filter
                else []
            )
            for designation in named:
                try:
                    rows = search(
                        lance_path, vecs[0], top_k=NAMED_NORM_DEPTH,
                        folder_filter=designation, query_text=effective_query,
                        hybrid=True, dataset=applied_dataset, alpha=alpha,
                        meta_path=meta_path,
                    )
                except Exception as guard_err:
                    print(f"[tools] named-norm guard skipped for "
                          f"{designation}: {guard_err}", file=sys.stderr)
                    continue
                if rows:
                    result_lists.append(rows)
            named_guard = {"designations": named,
                           "lists": len(result_lists) - len(paired)}
            retrieval_trace = merge_search_traces(sub_traces, len(pairs))
            retrieval_trace["named_norm_guard"] = named_guard
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
            rerank_trace: dict = {"status": "not_applied", "reason": decision.reason}
            if decision.apply and len(quality_pool) > top_k:
                try:
                    from rag_server.reranker import rerank_sync
                    quality_pool = rerank_sync(
                        effective_query, quality_pool, top_k=top_k, trace=rerank_trace
                    )
                    if rerank_trace.get("status") == "applied":
                        retrieval_trace["score_kind"] = "rerank_logit"
                except Exception as re_err:
                    print(f"[tools] reranker skipped: {re_err}", file=sys.stderr)
                    rerank_trace = {
                        "status": "failed",
                        "reason": f"{type(re_err).__name__}: {re_err}",
                    }
                    quality_pool = quality_pool[:top_k]
            focused = concentrate_sources(
                quality_pool, max_docs=focus_max_docs, min_score=0.30, query=None
            )
            final = fill_to_top_k(focused or quality_pool, quality_pool, top_k)
            return final, plan, decision, retrieval_trace, rerank_trace

        # ── Embedding contract ──────────────────────────────────────────────
        # The model asked for does not select the model on the server, and the
        # table name only carries the vector width. Verify both the live server
        # and the stored index manifest before trusting a single vector.
        from embedder.contract import EmbeddingContractError
        from storage.index_manifest import load_manifest, verify_manifest

        try:
            # Embedding for cache key uses the original query (stable across retries).
            primary_embedding = get_embeddings([query], is_query=True)[0]
        except EmbeddingContractError as ce:
            return blocked_result(
                ce.code, ce.detail,
                "load the configured embedding model in the server, then retry",
                debug=debug,
            )

        manifest_status, manifest_code, manifest_detail = verify_manifest(
            load_manifest(lance_path),
            model=_DEFAULT_PROVIDER.get_model_name(),
            dimension=len(primary_embedding),
        )
        if manifest_code:
            return blocked_result(
                manifest_code, manifest_detail,
                "reindex the corpus with the configured model, or point "
                "storage.lancedb_path at the store this model built",
                debug=debug,
            )
        # Diagnostics must never be able to break a search: a provider without
        # contract reporting degrades the trace, not the result.
        try:
            contract_state = _DEFAULT_PROVIDER.contract_state()
        except Exception:
            contract_state = {"status": "unsupported"}

        cache_hit = False
        if use_cache and not debug and rerank is not True:
            hit = cache.lookup(query, primary_embedding, scope_key=scope_key)
            if hit:
                print(
                    f"[tools] cache hit sim={hit.similarity:.3f} age={hit.age_seconds:.0f}s",
                    file=sys.stderr,
                )
                return hit.results[:top_k]

        final, plan, rerank_decision, retrieval_info, rerank_info = _execute(
            query, first_embedding=primary_embedding
        )

        # ── CRAG: grade retrieval; correct once if warranted (no LLM) ───────
        from rag_server.crag import grade_retrieval
        verdict = grade_retrieval(query, final, route, top_k)
        crag_corrected = False
        try:
            from rag_server.hyde import is_enabled as _hyde_on
            hyde_on = _hyde_on()
        except Exception:
            hyde_on = False
        if verdict.needs_correction and (route.route in _RETRY_AUGMENT or hyde_on):
            retry_query = (f"{query} {_RETRY_AUGMENT[route.route]}"
                           if route.route in _RETRY_AUGMENT else query)
            # HyDE fires here (weak retrieval) so good queries stay fast.
            (retry_final, retry_plan, retry_decision,
             retry_retrieval_info, retry_rerank_info) = _execute(retry_query, use_hyde=hyde_on)
            retry_verdict = grade_retrieval(query, retry_final, route, top_k)
            better = (
                retry_verdict.confidence > verdict.confidence
                or (retry_final and not final)
            )
            if better:
                final, plan, rerank_decision = retry_final, retry_plan, retry_decision
                retrieval_info, rerank_info = retry_retrieval_info, retry_rerank_info
                verdict = retry_verdict
                crag_corrected = True
                print(
                    f"[tools] CRAG correction applied verdict={verdict.label} "
                    f"conf={verdict.confidence:.2f}",
                    file=sys.stderr,
                )

        if use_cache and not debug and final and rerank_decision.reason != "forced":
            cache.store(query, primary_embedding, final, scope_key=scope_key)

        # ── ColPali visual hits (drawings) — kept OUT of the text results list
        # to preserve the result contract; surfaced via include_visual / debug
        # / the dedicated search_drawings tool. ─────────────────────────────
        visual_hits: list[dict] = []
        if include_visual or debug:
            try:
                from embedder.colpali import is_enabled as _cp_on, search_visual
                if _cp_on():
                    visual_raw = search_visual(query, top_k=top_k)
                    for h in _filter_visual_hits(
                        visual_raw, meta_path,
                        dataset=applied_dataset, folder_filter=applied_folder,
                    )[:3]:
                        h = dict(h)
                        h["type"] = "drawing"
                        visual_hits.append(h)
            except Exception as _cp_err:
                print(f"[tools] visual search skipped: {_cp_err}", file=sys.stderr)

        if not debug:
            return {"results": final, "visual": visual_hits} if include_visual else final

        trace = {
            # A hybrid request served by the dense channel alone is degraded,
            # and the status has to say so — otherwise a broken FTS index and a
            # healthy contour produce identical traces.
            "status": "degraded" if retrieval_info.get("degraded") else "ok",
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
            "retrieval": retrieval_info,
            "embedding_contract": {
                "expected_model": contract_state.get("expected_model", ""),
                "actual_model": contract_state.get("actual_model", ""),
                "status": contract_state.get("status", "unchecked"),
                "manifest": manifest_status,
            },
            "rerank": {
                # Whether the policy asked for a rerank, kept separate from
                # whether one happened: `applied: true` next to `status: failed`
                # read as a contradiction, and the policy's own reason was
                # overwritten by the failure reason.
                "decision": rerank_decision.apply,
                "decision_reason": rerank_decision.reason,
                **rerank_info,
            },
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
        trace["visual_hits"] = visual_hits
        return {"debug": trace, "results": final, "visual": visual_hits}
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


def search_drawings(
    query: str,
    top_k: int = 5,
    folder_filter: str | None = None,
    dataset: str | None = None,
) -> dict:
    """Visual (ColPali) search over indexed drawing pages (cross-modal)."""
    try:
        from embedder.colpali import is_enabled, search_visual
        from rag_server.query_router import route_query

        _, meta_path = _db_paths()
        route = route_query(
            query, explicit_dataset=dataset, explicit_folder_filter=folder_filter
        )
        scope = {"dataset": route.dataset, "folder_filter": route.folder_filter}
        if not is_enabled():
            return {"enabled": False,
                    "hint": "ColPali is off — set colpali.enabled in config.yaml",
                    "results": [],
                    "scope": scope}
        raw = search_visual(query, top_k=max(1, min(top_k, 20)))
        filtered = _filter_visual_hits(
            raw, meta_path, dataset=route.dataset, folder_filter=route.folder_filter
        )
        return {"enabled": True, "results": filtered, "scope": scope}
    except Exception as e:
        return {"error": str(e), "results": []}


def sum_table_values(
    subject: str,
    source_like: str | None = None,
    field: str | None = None,
    op: str = "sum",
    dataset: str | None = None,
    max_files: int = 20,
    max_rows: int = 50,
) -> dict:
    """Deterministically sum/count a numeric column over ALL matching table rows
    (re-parses the source xlsx/pdf/docx; never lets the LLM do arithmetic)."""
    from rag_server.table_query import sum_table_values as _impl
    return _impl(subject, source_like=source_like, field=field, op=op,
                 dataset=dataset, max_files=int(max_files), max_rows=int(max_rows))


def locate_quote(quote: str, source_path: str = "", file_name: str = "") -> dict:
    """Which page of the source a quote sits on.

    A citation that cannot say where it sits is hard to act on: an engineer
    writing a remark needs the page. The store has no page field and adding one
    means reindexing the whole corpus, so the page is looked up in the document
    itself, on request. Measured on 40 stored chunks: found for all 40, median
    694ms — too slow to attach to every search result, fine as its own call.

    Only documents the index holds can be opened; `file_name` is accepted so a
    caller can name the document the way search reported it.
    """
    from rag_server.locator import locate_quote as _locate
    from storage.metadata_db import _connect

    _lance, meta_path = _db_paths()
    with _connect(meta_path) as conn:
        if source_path:
            rows = conn.execute(
                "SELECT source_path FROM files WHERE source_path = ?",
                (source_path,),
            ).fetchall()
        elif file_name:
            rows = conn.execute(
                "SELECT source_path FROM files WHERE file_name = ?",
                (file_name,),
            ).fetchall()
        else:
            return {"status": "no_document_given", "pages": []}

    allowed = [r[0] for r in rows]
    if not allowed:
        return {"status": "not_indexed", "pages": [],
                "source_path": source_path or file_name}
    # A name can belong to more than one indexed path; answer for each.
    answers = [_locate(path, quote, allowed=allowed) for path in allowed[:3]]
    found = [a for a in answers if a["status"] == "found"]
    return found[0] if found else answers[0]


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

    denied = {"status": "error", "message": "Path is not allowed."}
    target = Path(path)
    if not target.exists():
        return denied
    target = target.resolve()

    watched_folders = _cfg().get("watched_folders")
    if not isinstance(watched_folders, list):
        return denied
    watched_roots = []
    for folder in watched_folders:
        if not isinstance(folder, (str, os.PathLike)):
            return denied
        root = Path(folder)
        # Недоступный корень (например, отключённый сетевой диск) не должен
        # блокировать остальные: пропускаем его, а не отклоняем весь запрос.
        if not root.is_absolute() or not root.exists() or not root.is_dir():
            continue
        watched_roots.append(root.resolve())
    if not any(target.is_relative_to(root) for root in watched_roots):
        return denied

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
                    "include_visual": {"type": "boolean", "description": "Also return ColPali drawing hits as {results, visual} (optional, default false)"},
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
            "name": "locate_quote",
            "description": "Find which page(s) of a source document contain a quote.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "quote":       {"type": "string", "description": "Text to locate (a sentence or two is enough)"},
                    "source_path": {"type": "string", "description": "Full path as reported by search (optional if file_name given)"},
                    "file_name":   {"type": "string", "description": "File name as reported by search (optional if source_path given)"},
                },
                "required": ["quote"],
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
                    "label": {"type": "string", "description": "Parameter label to extract, e.g. Параметр настройки or Потеря давления"},
                    "source_like": {"type": "string", "description": "Optional source_path substring filter"},
                    "limit": {"type": "number", "description": "Max parent chunks to scan (optional, default 500)"},
                    "max_rows": {"type": "number", "description": "Max extracted rows to return (optional, default 50)"},
                },
                "required": ["label"],
            },
        },
        {
            "name": "search_drawings",
            "description": "Visual search over drawing pages (ColPali/Jina). Finds чертежи by content, OCR-free.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to find on the drawings"},
                    "top_k": {"type": "number", "description": "Number of pages (optional, default 5)"},
                    "folder_filter": {"type": "string", "description": "Optional source_path substring filter; auto-routed when omitted"},
                    "dataset": {"type": "string", "description": "Optional dataset filter; auto-routed when omitted"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "sum_table_values",
            "description": ("Deterministically SUM or COUNT a numeric column over ALL rows of a "
                            "table (smeta/spec/ВОР). Re-parses the source xlsx/pdf/docx and computes "
                            "in Python — verified totals, no LLM arithmetic. Use for 'сколько/итого/"
                            "сумма/объём/площадь/количество'."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "What to count, e.g. 'кабель 3х1,5' or 'площадь венткамер'"},
                    "source_like": {"type": "string", "description": "Optional source_path substring to target one file"},
                    "field": {"type": "string", "description": "Optional column: qty|amount|amount_mat|amount_work|price (auto if omitted)"},
                    "op": {"type": "string", "description": "sum (default) | count"},
                    "dataset": {"type": "string", "description": "Optional dataset filter"},
                },
                "required": ["subject"],
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
