#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instrumental stage-by-stage profiling for exact norm search.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e")

from rag_server.tools import _db_paths, _cfg, search_documents, build_search_scope_key
from rag_server.norm_resolver import get_norm_registry
from rag_server.query_router import route_query
from rag_server.query_planner import plan_query
from rag_server.query_shape import lexical_alpha
from embedder.client import _DEFAULT_PROVIDER, get_embeddings
from storage.vector_store import search
from rag_server.retrieval_quality import apply_retrieval_quality
from storage.semantic_cache import SemanticCache

def profile_query(query: str):
    lance_path, meta_path = _db_paths()
    print("=" * 70)
    print(f"PROFILING QUERY: {query}")
    print("=" * 70)
    
    t_start = time.perf_counter()

    # 1. ENR Resolution
    t0 = time.perf_counter()
    norm_reg = get_norm_registry(meta_path)
    multi_res = norm_reg.resolve_all(query)
    t_enr = (time.perf_counter() - t0) * 1000.0
    print(f"1. ENR resolution: {t_enr:.2f} ms | targets: {len(multi_res.resolutions)}")
    for r in multi_res.resolutions:
        print(f"   -> target: {r.target.raw_match} | status: {r.status} | doc: {r.target_source_path}")

    # 2. Router & Alpha
    t0 = time.perf_counter()
    route = route_query(query)
    alpha = lexical_alpha(query, default=0.7)
    t_route = (time.perf_counter() - t0) * 1000.0
    print(f"2. Router & Alpha: {t_route:.2f} ms | route={route.route}, alpha={alpha}")

    # 3. Query Planner
    t0 = time.perf_counter()
    plan = plan_query(query, dataset=route.dataset, route=route.route)
    t_plan = (time.perf_counter() - t0) * 1000.0
    queries = list(plan.queries)
    print(f"3. Query Planner: {t_plan:.2f} ms | {len(queries)} subqueries: {queries}")

    # 4. Primary embedding (llama-server)
    t0 = time.perf_counter()
    p_vec = get_embeddings([query], is_query=True)[0]
    t_pemb = (time.perf_counter() - t0) * 1000.0
    print(f"4. Primary Embedding: {t_pemb:.2f} ms")

    # 5. Subqueries embeddings (llama-server)
    t0 = time.perf_counter()
    sub_vecs = get_embeddings(queries[1:], is_query=True) if len(queries) > 1 else []
    vecs = [p_vec] + sub_vecs
    t_subemb = (time.perf_counter() - t0) * 1000.0
    print(f"5. Extra Subquery Embeddings ({len(sub_vecs)} extra vectors): {t_subemb:.2f} ms")

    # 6. LanceDB/FTS search per subquery
    t0 = time.perf_counter()
    result_lists = []
    for idx, (qt, qv) in enumerate(zip(queries, vecs)):
        t_s0 = time.perf_counter()
        trace = {}
        rows = search(lance_path, qv, top_k=30, query_text=qt, hybrid=True, alpha=alpha, meta_path=meta_path, trace=trace)
        t_s = (time.perf_counter() - t_s0) * 1000.0
        result_lists.append(rows)
        fts_ms = trace.get("timing_ms", {}).get("fts_search", 0)
        vec_ms = trace.get("timing_ms", {}).get("vector_search", 0)
        hydrate_ms = trace.get("timing_ms", {}).get("hydration", 0)
        print(f"   Subquery [{idx+1}] \"{qt}\": {t_s:.2f} ms | rows: {len(rows)} | fts: {fts_ms:.1f}ms, vec: {vec_ms:.1f}ms, hydrate: {hydrate_ms:.1f}ms")
    t_search = (time.perf_counter() - t0) * 1000.0
    print(f"6. Total Subquery Searches: {t_search:.2f} ms")

    # 7. Named Norm Guard
    t0 = time.perf_counter()
    named_paths = multi_res.target_source_paths
    guard_lists = []
    for tp in named_paths:
        fn = Path(tp).name
        t_g0 = time.perf_counter()
        g_trace = {}
        g_rows = search(lance_path, p_vec, top_k=5, folder_filter=fn, query_text=query, hybrid=True, alpha=alpha, meta_path=meta_path, trace=g_trace)
        t_g = (time.perf_counter() - t_g0) * 1000.0
        guard_lists.append(g_rows)
        print(f"   Named Guard [{fn}]: {t_g:.2f} ms | rows: {len(g_rows)}")
    t_guard = (time.perf_counter() - t0) * 1000.0
    print(f"7. Total Named Guard Searches: {t_guard:.2f} ms")

    # 8. Fusion & Retrieval Quality
    t0 = time.perf_counter()
    from rag_server.query_planner import fuse_ranked_results
    fused = fuse_ranked_results(result_lists + guard_lists, limit=30)
    primary_norm = multi_res.primary_target
    target_clause = primary_norm.clause if primary_norm else None
    target_clause_type = primary_norm.clause_type if primary_norm else None
    
    quality_pool = apply_retrieval_quality(
        query, fused, dataset=route.dataset, top_k=20, max_per_doc=2,
        target_source_path=named_paths, target_clause=target_clause
    )
    t_qual = (time.perf_counter() - t0) * 1000.0
    print(f"8. Fusion & Retrieval Quality: {t_qual:.2f} ms | pool: {len(quality_pool)}")

    # 9. Clause Extraction (if target_clause)
    t0 = time.perf_counter()
    if named_paths and target_clause:
        c_matches = norm_reg.extract_clause_from_doc(named_paths[0], target_clause, target_clause_type)
        t_clause = (time.perf_counter() - t0) * 1000.0
        print(f"9. Clause Extraction: {t_clause:.2f} ms | matches: {len(c_matches)}")
    else:
        print(f"9. Clause Extraction: skipped (no clause in query)")

    # 10. Reranker Decision
    t0 = time.perf_counter()
    from rag_server.rerank_policy import decide_rerank
    decision = decide_rerank(explicit_rerank=None, auto_enabled=True, plan=plan, quality_pool=quality_pool, top_k=5)
    t_rerank_dec = (time.perf_counter() - t0) * 1000.0
    print(f"10. Reranker Decision: {t_rerank_dec:.2f} ms | apply: {decision.apply}, reason: {decision.reason}")

    # 11. CRAG grading
    t0 = time.perf_counter()
    from rag_server.crag import grade_retrieval
    verdict = grade_retrieval(query, quality_pool[:5], route, top_k=5)
    t_crag = (time.perf_counter() - t0) * 1000.0
    print(f"11. CRAG Grading: {t_crag:.2f} ms | verdict: {verdict.label}, needs_correction: {verdict.needs_correction}")

    # 12. Complete search_documents cold vs warm
    print("-" * 50)
    print("Testing full search_documents() E2E:")
    t0 = time.perf_counter()
    res1 = search_documents(query, top_k=5, use_cache=True, debug=False)
    t_e2e_1 = (time.perf_counter() - t0) * 1000.0
    print(f"E2E Run 1 (Cold / Cache Store): {t_e2e_1:.2f} ms | res len: {len(res1)}")

    t0 = time.perf_counter()
    res2 = search_documents(query, top_k=5, use_cache=True, debug=False)
    t_e2e_2 = (time.perf_counter() - t0) * 1000.0
    print(f"E2E Run 2 (Warm / Cache Hit):   {t_e2e_2:.2f} ms | res len: {len(res2)}")

    t0 = time.perf_counter()
    res3 = search_documents(query, top_k=5, use_cache=True, debug=True)
    t_e2e_3 = (time.perf_counter() - t0) * 1000.0
    print(f"E2E Run 3 (Warm with debug=True): {t_e2e_3:.2f} ms")

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "СП 7.13130.2013 требования пожарной безопасности"
    profile_query(q)
