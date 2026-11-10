#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orchestrates the Paired 55-Query A/B Benchmark between Baseline (7ea2a48) and ENR (Stage E.2).
Computes segregated metrics with exact denominators.
"""
import subprocess
import sys
import json
import numpy as np
from pathlib import Path

VENV_PYTHON = r"C:\RAG_Acer\venv\Scripts\python.exe"
BASELINE_REPO = r"C:\RAG_Acer\repos\flying-rag-mcp"
ENR_REPO = r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e"
EVAL_SCRIPT = r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e\scripts\eval_paired_55.py"

BASELINE_OUT = r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e\baseline_55_results.json"
ENR_OUT = r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e\enr_55_results.json"
REPORT_OUT = r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e\paired_55_comparison.json"


def run_sub(repo, mode, out_path):
    print(f"\n=======================================================")
    print(f"Launching {mode.upper()} evaluation run...")
    print(f"=======================================================")
    cmd = [VENV_PYTHON, EVAL_SCRIPT, "--repo", repo, "--mode", mode, "--out", out_path]
    res = subprocess.run(cmd, capture_output=False)
    if res.returncode != 0:
        raise RuntimeError(f"Run failed for {mode} with exit code {res.returncode}")


def compute_metrics(records):
    # Separate by category
    doc_records = [r for r in records if r["category"] == "exact_doc"]
    clause_records = [r for r in records if r["category"] == "clause"]
    absent_records = [r for r in records if r["category"] == "absent_norm"]
    absent_clause_records = [r for r in records if r["category"] == "absent_clause"]
    hybrid_records = [r for r in records if r["category"] == "general_hybrid"]

    # 1. Exact Document Hit@1/5 (only present docs, N=len(doc_records))
    n_docs = len(doc_records)
    doc_hit1 = sum(1 for r in doc_records if r["doc_rank"] == 1)
    doc_hit5 = sum(1 for r in doc_records if r["doc_rank"] is not None and r["doc_rank"] <= 5)
    doc_rr_list = [1.0 / r["doc_rank"] if r["doc_rank"] else 0.0 for r in doc_records]
    doc_mrr = float(np.mean(doc_rr_list)) if doc_rr_list else 0.0

    # 2. Clause Hit@1/5 (only verified clauses, N=len(clause_records))
    n_clauses = len(clause_records)
    clause_hit1 = sum(1 for r in clause_records if r["clause_rank"] == 1)
    clause_hit5 = sum(1 for r in clause_records if r["clause_rank"] is not None and r["clause_rank"] <= 5)
    clause_rr_list = [1.0 / r["clause_rank"] if r["clause_rank"] else 0.0 for r in clause_records]
    clause_mrr = float(np.mean(clause_rr_list)) if clause_rr_list else 0.0

    # 3. Absent Norm Accuracy & False Attributions (only absent norms, N=len(absent_records))
    n_absent = len(absent_records)
    absent_acc = sum(1 for r in absent_records if r["absent_detected"])
    absent_fp = sum(1 for r in absent_records if r["false_attribution"]) # returned fake chunks as evidence
    absent_fn = sum(1 for r in doc_records if r.get("status") == "norm_not_found") # present norm falsely declared absent

    # 4. Absent clause detection
    n_absent_clause = len(absent_clause_records)
    absent_clause_acc = sum(1 for r in absent_clause_records if r["absent_clause_detected"])

    # 5. Hybrid queries Hit (N=len(hybrid_records))
    n_hybrid = len(hybrid_records)
    hybrid_hits = sum(1 for r in hybrid_records if r["hybrid_hit"])

    # 6. Overall MRR across retrieval queries (doc + clause + hybrid)
    all_retrieval = doc_records + clause_records
    retrieval_rr = []
    for r in all_retrieval:
        rank = r.get("clause_rank") if r["category"] == "clause" else r.get("doc_rank")
        retrieval_rr.append(1.0 / rank if rank else 0.0)
    overall_mrr = float(np.mean(retrieval_rr)) if retrieval_rr else 0.0

    # 7. Latencies by category (cold and warm)
    def calc_lat(recs, key):
        vals = [r[key] for r in recs]
        if not vals:
            return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
        return {
            "mean": float(np.mean(vals)),
            "p50": float(np.percentile(vals, 50)),
            "p95": float(np.percentile(vals, 95)),
        }

    lat_doc_cold = calc_lat(doc_records, "cold_latency_ms")
    lat_doc_warm = calc_lat(doc_records, "warm_latency_ms")

    lat_clause_cold = calc_lat(clause_records, "cold_latency_ms")
    lat_clause_warm = calc_lat(clause_records, "warm_latency_ms")

    lat_absent_cold = calc_lat(absent_records, "cold_latency_ms")
    lat_absent_warm = calc_lat(absent_records, "warm_latency_ms")

    lat_hybrid_cold = calc_lat(hybrid_records, "cold_latency_ms")
    lat_hybrid_warm = calc_lat(hybrid_records, "warm_latency_ms")

    all_cold = calc_lat(records, "cold_latency_ms")
    all_warm = calc_lat(records, "warm_latency_ms")

    return {
        "counts": {
            "total": len(records),
            "exact_doc": n_docs,
            "clause": n_clauses,
            "absent_norm": n_absent,
            "absent_clause": n_absent_clause,
            "general_hybrid": n_hybrid,
        },
        "exact_doc": {
            "hit1": doc_hit1,
            "hit1_pct": doc_hit1 / n_docs * 100.0,
            "hit5": doc_hit5,
            "hit5_pct": doc_hit5 / n_docs * 100.0,
            "mrr": doc_mrr,
            "denominator": n_docs,
        },
        "clause": {
            "hit1": clause_hit1,
            "hit1_pct": clause_hit1 / n_clauses * 100.0,
            "hit5": clause_hit5,
            "hit5_pct": clause_hit5 / n_clauses * 100.0,
            "mrr": clause_mrr,
            "denominator": n_clauses,
        },
        "absent_norm": {
            "accuracy": absent_acc,
            "accuracy_pct": absent_acc / n_absent * 100.0,
            "false_positive": absent_fp,
            "false_negative": absent_fn,
            "denominator": n_absent,
        },
        "absent_clause": {
            "accuracy": absent_clause_acc,
            "accuracy_pct": absent_clause_acc / n_absent_clause * 100.0 if n_absent_clause else 0.0,
            "denominator": n_absent_clause,
        },
        "general_hybrid": {
            "hit": hybrid_hits,
            "hit_pct": hybrid_hits / n_hybrid * 100.0,
            "denominator": n_hybrid,
        },
        "overall_retrieval_mrr": overall_mrr,
        "latencies": {
            "exact_doc": {"cold": lat_doc_cold, "warm": lat_doc_warm},
            "clause": {"cold": lat_clause_cold, "warm": lat_clause_warm},
            "absent_norm": {"cold": lat_absent_cold, "warm": lat_absent_warm},
            "general_hybrid": {"cold": lat_hybrid_cold, "warm": lat_hybrid_warm},
            "overall": {"cold": all_cold, "warm": all_warm},
        }
    }


def main():
    # 1. Run Baseline
    run_sub(BASELINE_REPO, "baseline", BASELINE_OUT)

    # 2. Run ENR
    run_sub(ENR_REPO, "enr", ENR_OUT)

    # 3. Load results
    with open(BASELINE_OUT, "r", encoding="utf-8") as f:
        baseline_recs = json.load(f)
    with open(ENR_OUT, "r", encoding="utf-8") as f:
        enr_recs = json.load(f)

    # 4. Compute metrics
    b_metrics = compute_metrics(baseline_recs)
    e_metrics = compute_metrics(enr_recs)

    comparison = {
        "baseline": b_metrics,
        "enr": e_metrics,
    }

    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    print("\n" + "="*80)
    print("                    STRICT PAIRED 55-QUERY A/B AUDIT RESULTS")
    print("="*80)
    print(f"{'Metric':<32} | {'Baseline (7ea2a48)':<20} | {'ENR (Stage E.2)':<20} | {'Delta':<12}")
    print("-"*80)

    # Exact Document
    b_d_h1 = b_metrics['exact_doc']['hit1_pct']
    e_d_h1 = e_metrics['exact_doc']['hit1_pct']
    n_d = b_metrics['exact_doc']['denominator']
    print(f"{f'Exact Doc Hit@1 (N={n_d})':<32} | {b_d_h1:5.1f}% ({b_metrics['exact_doc']['hit1']}/{n_d}){'':<7} | {e_d_h1:5.1f}% ({e_metrics['exact_doc']['hit1']}/{n_d}){'':<7} | {e_d_h1 - b_d_h1:+5.1f}%")

    b_d_h5 = b_metrics['exact_doc']['hit5_pct']
    e_d_h5 = e_metrics['exact_doc']['hit5_pct']
    print(f"{f'Exact Doc Hit@5 (N={n_d})':<32} | {b_d_h5:5.1f}% ({b_metrics['exact_doc']['hit5']}/{n_d}){'':<7} | {e_d_h5:5.1f}% ({e_metrics['exact_doc']['hit5']}/{n_d}){'':<7} | {e_d_h5 - b_d_h5:+5.1f}%")

    b_d_mrr = b_metrics['exact_doc']['mrr']
    e_d_mrr = e_metrics['exact_doc']['mrr']
    print(f"{f'Exact Doc MRR (N={n_d})':<32} | {b_d_mrr:6.4f}{'':<14} | {e_d_mrr:6.4f}{'':<14} | {e_d_mrr - b_d_mrr:+6.4f}")

    print("-"*80)
    # Clause
    b_c_h1 = b_metrics['clause']['hit1_pct']
    e_c_h1 = e_metrics['clause']['hit1_pct']
    n_c = b_metrics['clause']['denominator']
    print(f"{f'Clause Hit@1 (N={n_c})':<32} | {b_c_h1:5.1f}% ({b_metrics['clause']['hit1']}/{n_c}){'':<7} | {e_c_h1:5.1f}% ({e_metrics['clause']['hit1']}/{n_c}){'':<7} | {e_c_h1 - b_c_h1:+5.1f}%")

    b_c_h5 = b_metrics['clause']['hit5_pct']
    e_c_h5 = e_metrics['clause']['hit5_pct']
    print(f"{f'Clause Hit@5 (N={n_c})':<32} | {b_c_h5:5.1f}% ({b_metrics['clause']['hit5']}/{n_c}){'':<7} | {e_c_h5:5.1f}% ({e_metrics['clause']['hit5']}/{n_c}){'':<7} | {e_c_h5 - b_c_h5:+5.1f}%")

    b_c_mrr = b_metrics['clause']['mrr']
    e_c_mrr = e_metrics['clause']['mrr']
    print(f"{f'Clause MRR (N={n_c})':<32} | {b_c_mrr:6.4f}{'':<14} | {e_c_mrr:6.4f}{'':<14} | {e_c_mrr - b_c_mrr:+6.4f}")

    print("-"*80)
    # Absent Norm
    b_a_acc = b_metrics['absent_norm']['accuracy_pct']
    e_a_acc = e_metrics['absent_norm']['accuracy_pct']
    n_a = b_metrics['absent_norm']['denominator']
    print(f"{f'Absent Norm Accuracy (N={n_a})':<32} | {b_a_acc:5.1f}% ({b_metrics['absent_norm']['accuracy']}/{n_a}){'':<7} | {e_a_acc:5.1f}% ({e_metrics['absent_norm']['accuracy']}/{n_a}){'':<7} | {e_a_acc - b_a_acc:+5.1f}%")

    b_a_fp = b_metrics['absent_norm']['false_positive']
    e_a_fp = e_metrics['absent_norm']['false_positive']
    print(f"{'Absent Norm False Positives':<32} | {b_a_fp:<20} | {e_a_fp:<20} | {e_a_fp - b_a_fp:+d}")

    b_a_fn = b_metrics['absent_norm']['false_negative']
    e_a_fn = e_metrics['absent_norm']['false_negative']
    print(f"{'Present Norm False Negatives':<32} | {b_a_fn:<20} | {e_a_fn:<20} | {e_a_fn - b_a_fn:+d}")

    print("-"*80)
    # General Hybrid
    b_h_pct = b_metrics['general_hybrid']['hit_pct']
    e_h_pct = e_metrics['general_hybrid']['hit_pct']
    print(f"{'General Hybrid Hit@5 (N=12)':<32} | {b_h_pct:5.1f}% ({b_metrics['general_hybrid']['hit']}/{b_metrics['general_hybrid']['denominator']}){'':<7} | {e_h_pct:5.1f}% ({e_metrics['general_hybrid']['hit']}/{e_metrics['general_hybrid']['denominator']}){'':<7} | {e_h_pct - b_h_pct:+5.1f}%")

    print("-"*80)
    # Latencies
    print(f"{'Latencies (p50 / p95)':<32} | {'Baseline (Cold)':<20} | {'ENR (Cold)':<20} | {'ENR (Warm)':<12}")
    print("-"*80)
    for cat_key, cat_name in [
        ("exact_doc", "Exact Doc Latency (ms)"),
        ("clause", "Clause Latency (ms)"),
        ("absent_norm", "Absent Norm Latency (ms)"),
        ("general_hybrid", "General Hybrid Latency (ms)"),
        ("overall", "Overall Latency (ms)"),
    ]:
        b_c = b_metrics['latencies'][cat_key]['cold']
        e_c = e_metrics['latencies'][cat_key]['cold']
        e_w = e_metrics['latencies'][cat_key]['warm']
        print(f"{cat_name:<32} | {b_c['p50']:6.1f} / {b_c['p95']:6.1f} ms  | {e_c['p50']:6.1f} / {e_c['p95']:6.1f} ms  | {e_w['p50']:6.1f} / {e_w['p95']:6.1f} ms")

    print("="*80)


if __name__ == "__main__":
    main()
