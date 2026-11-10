#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paired A/B Retrieval Evaluation Script for Stage E.2.
Can run in baseline mode (using C:\\RAG_Acer\\repos\\flying-rag-mcp)
or ENR mode (using C:\\RAG_Acer\\repos\\flying-rag-mcp-stage-e).
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

BENCHMARK_QUERIES = [
    # ── Category 1: Exact Document Present (21 queries) ─────────────────────
    {
        "id": "doc_sp60_year",
        "category": "exact_doc",
        "query": "СП 60.13330.2020",
        "target_docs": ["СП 60.13330.2020"],
    },
    {
        "id": "doc_sp1_year",
        "category": "exact_doc",
        "query": "СП 1.13130.2020",
        "target_docs": ["СП 1.13130", "1.13130.2020"],
    },
    {
        "id": "doc_sp7_year",
        "category": "exact_doc",
        "query": "СП 7.13130.2013",
        "target_docs": ["СП 7.13130.docx"],
        "disallowed_docs": ["СП 153", "Методические рекомендации"],
    },
    {
        "id": "doc_sp324_year",
        "category": "exact_doc",
        "query": "СП 324.1325800.2017",
        "target_docs": ["СП 324.1325800.2017"],
    },
    {
        "id": "doc_sp331_year",
        "category": "exact_doc",
        "query": "СП 331.1325800.2017",
        "target_docs": ["СП 331.1325800.2017"],
    },
    {
        "id": "doc_gost59972_year",
        "category": "exact_doc",
        "query": "ГОСТ Р 59972-2021",
        "target_docs": ["ГОСТ Р 59972-2021"],
    },
    {
        "id": "doc_sp60_noyear",
        "category": "exact_doc",
        "query": "СП 60.13330",
        "target_docs": ["СП 60.13330.2020"],
    },
    {
        "id": "doc_sp70_noyear",
        "category": "exact_doc",
        "query": "СП 70.13330",
        "target_docs": ["СП 70.13330"],
    },
    {
        "id": "doc_sp73_noyear",
        "category": "exact_doc",
        "query": "СП 73.13330",
        "target_docs": ["СП 73.13330"],
    },
    {
        "id": "doc_sp153_noyear",
        "category": "exact_doc",
        "query": "СП 153.13130",
        "target_docs": ["СП 153.13130"],
    },
    {
        "id": "doc_gost53300_year",
        "category": "exact_doc",
        "query": "ГОСТ Р 53300-2009",
        "target_docs": ["ГОСТ Р 53300-2009", "53300-2009"],
    },
    {
        "id": "doc_gost12_year",
        "category": "exact_doc",
        "query": "ГОСТ 12.1.004-91",
        "target_docs": ["12.1.004-91", "12.1.004"],
    },
    {
        "id": "doc_sp1_noyear",
        "category": "exact_doc",
        "query": "СП 1.13130",
        "target_docs": ["СП 1.13130", "1.13130.2020"],
    },
    {
        "id": "doc_sp7_noyear",
        "category": "exact_doc",
        "query": "СП 7.13130",
        "target_docs": ["СП 7.13130.docx"],
        "disallowed_docs": ["СП 153", "Методические рекомендации"],
    },
    {
        "id": "doc_sp7_fire",
        "category": "exact_doc",
        "query": "СП 7.13130.2013 требования пожарной безопасности",
        "target_docs": ["СП 7.13130.docx"],
        "disallowed_docs": ["СП 153", "Методические рекомендации"],
    },
    {
        "id": "doc_sp60_vent",
        "category": "exact_doc",
        "query": "СП 60.13330.2020 отопление вентиляция",
        "target_docs": ["СП 60.13330.2020"],
    },
    {
        "id": "doc_sp1_evac",
        "category": "exact_doc",
        "query": "СП 1.13130.2020 эвакуационные пути",
        "target_docs": ["СП 1.13130", "1.13130.2020"],
    },
    {
        "id": "doc_gost53300_smoke",
        "category": "exact_doc",
        "query": "ГОСТ Р 53300-2009 противодымная вентиляция методы испытаний",
        "target_docs": ["53300-2009"],
    },
    {
        "id": "doc_multi_sp60_sp7",
        "category": "exact_doc",
        "query": "СП 60.13330 и СП 7.13130",
        "target_docs": ["СП 60.13330", "СП 7.13130.docx"],
    },
    {
        "id": "doc_multi_sp7_gost",
        "category": "exact_doc",
        "query": "требования СП 7.13130 к огнестойкости воздуховодов по ГОСТ Р 53299",
        "target_docs": ["СП 7.13130.docx", "53299"],
    },
    {
        "id": "doc_sp13_year",
        "category": "exact_doc",
        "query": "СП 13.13130.2009",
        "target_docs": ["13.13130.2009"],
    },

    # ── Category 2: Verified Clauses (11 queries) ───────────────────────────
    {
        "id": "clause_8_1",
        "category": "clause",
        "query": "пункт 8.1 подпор воздуха",
        "target_clause": "8.1",
        "clause_keywords": ["8.1", "подпор"],
    },
    {
        "id": "clause_8_2",
        "category": "clause",
        "query": "пункт 8.2 компенсация дымоудаления",
        "target_clause": "8.2",
        "clause_keywords": ["8.2", "компенсаци"],
    },
    {
        "id": "clause_8_3",
        "category": "clause",
        "query": "пункт 8.3 незадымляемые лестничные клетки",
        "target_clause": "8.3",
        "clause_keywords": ["8.3", "лестничн"],
    },
    {
        "id": "clause_7_4",
        "category": "clause",
        "query": "пункт 7.4 рекуперация",
        "target_clause": "7.4",
        "clause_keywords": ["7.4", "рекуперац", "утилизац"],
    },
    {
        "id": "clause_sec_4",
        "category": "clause",
        "query": "раздел 4 эвакуационные пути",
        "target_clause": "4",
        "clause_keywords": ["раздел 4", "эвакуац"],
    },
    {
        "id": "clause_4_2_19",
        "category": "clause",
        "query": "пункт 4.2.19 открывание дверей",
        "target_clause": "4.2.19",
        "clause_keywords": ["4.2.19", "двер"],
    },
    {
        "id": "clause_7_1",
        "category": "clause",
        "query": "пункт 7.1 расход воздуха",
        "target_clause": "7.1",
        "clause_keywords": ["7.1", "расход"],
    },
    {
        "id": "clause_sp60_7_1_1",
        "category": "clause",
        "query": "СП 60.13330 пункт 7.1.1",
        "target_clause": "7.1.1",
        "target_docs": ["СП 60.13330.2020"],
        "clause_keywords": ["7.1.1"],
    },
    {
        "id": "clause_sp60_7_4_1",
        "category": "clause",
        "query": "СП 60.13330 пункт 7.4.1",
        "target_clause": "7.4.1",
        "target_docs": ["СП 60.13330.2020"],
        "clause_keywords": ["7.4.1"],
    },
    {
        "id": "clause_sp60_app_a3",
        "category": "clause",
        "query": "СП 60.13330 приложение А.3",
        "target_clause": "А.3",
        "target_docs": ["СП 60.13330.2020"],
        "clause_keywords": ["Приложение А.3", "А.3"],
    },
    {
        "id": "clause_sp7_6_4",
        "category": "clause",
        "query": "СП 7.13130 пункт 6.4",
        "target_clause": "6.4",
        "target_docs": ["СП 7.13130.docx"],
        "clause_keywords": ["6.4"],
    },

    # ── Category 3: Absent Norms (10 queries) ────────────────────────────────
    {
        "id": "absent_gesn_08_01",
        "category": "absent_norm",
        "query": "ГЭСН 08-01",
        "target_norm": "ГЭСН 08-01",
    },
    {
        "id": "absent_gesn_08_01_001",
        "category": "absent_norm",
        "query": "ГЭСН 08-01-001",
        "target_norm": "ГЭСН 08-01-001",
    },
    {
        "id": "absent_gesn_m_12",
        "category": "absent_norm",
        "query": "ГЭСНм 12",
        "target_norm": "ГЭСНм 12",
    },
    {
        "id": "absent_gesn_r_65",
        "category": "absent_norm",
        "query": "ГЭСНр 65",
        "target_norm": "ГЭСНр 65",
    },
    {
        "id": "absent_gesn_20",
        "category": "absent_norm",
        "query": "ГЭСН 20",
        "target_norm": "ГЭСН 20",
    },
    {
        "id": "absent_gesn_m_12_01_001",
        "category": "absent_norm",
        "query": "ГЭСНм 12-01-001",
        "target_norm": "ГЭСНм 12-01-001",
    },
    {
        "id": "absent_gesn_r_65_1",
        "category": "absent_norm",
        "query": "ГЭСНр 65-1",
        "target_norm": "ГЭСНр 65-1",
    },
    {
        "id": "absent_fer_20",
        "category": "absent_norm",
        "query": "ФЕР 20",
        "target_norm": "ФЕР 20",
    },
    {
        "id": "absent_sp_999",
        "category": "absent_norm",
        "query": "СП 999",
        "target_norm": "СП 999",
    },
    {
        "id": "absent_gost_99999",
        "category": "absent_norm",
        "query": "ГОСТ Р 99999",
        "target_norm": "ГОСТ Р 99999",
    },

    # ── Category 4: Absent Clause in Present Document (1 query) ──────────────
    {
        "id": "absent_clause_sp7_99_99",
        "category": "absent_clause",
        "query": "СП 7.13130 пункт 99.99",
        "target_norm": "СП 7.13130",
        "target_docs": ["СП 7.13130.docx"],
        "target_clause": "99.99",
    },

    # ── Category 5: General Hybrid / Equipment / Semantic (12 queries) ──────
    {
        "id": "eq_v1",
        "category": "general_hybrid",
        "query": "В1",
        "expected_keywords": ["В1", "вентиляц"],
    },
    {
        "id": "eq_p1",
        "category": "general_hybrid",
        "query": "П1",
        "expected_keywords": ["П1", "приточн"],
    },
    {
        "id": "eq_ov2",
        "category": "general_hybrid",
        "query": "ОВ2",
        "expected_keywords": ["ОВ2", "отоплен", "вентиляц"],
    },
    {
        "id": "eq_klop",
        "category": "general_hybrid",
        "query": "КЛОП-1",
        "expected_keywords": ["КЛОП", "клапан"],
    },
    {
        "id": "eq_calorifer",
        "category": "general_hybrid",
        "query": "калориферы водяные",
        "expected_keywords": ["калорифер"],
    },
    {
        "id": "eq_duct_600",
        "category": "general_hybrid",
        "query": "воздуховод 600х500",
        "expected_keywords": ["600", "500", "воздуховод"],
    },
    {
        "id": "eq_deflector",
        "category": "general_hybrid",
        "query": "дефлекторы круглые",
        "expected_keywords": ["дефлектор"],
    },
    {
        "id": "cost_duct",
        "category": "general_hybrid",
        "query": "сметные нормы воздуховоды",
        "expected_keywords": ["воздуховод", "монтаж", "норм"],
    },
    {
        "id": "cost_fan",
        "category": "general_hybrid",
        "query": "сметные нормы вентиляторы",
        "expected_keywords": ["вентилятор", "монтаж", "установк"],
    },
    {
        "id": "sem_smoke_corridor",
        "category": "general_hybrid",
        "query": "в каких случаях нужно предусматривать удаление дыма из коридоров",
        "expected_keywords": ["коридор", "дымоудален", "8.1", "продуктов горения"],
    },
    {
        "id": "sem_smoke_exceptions",
        "category": "general_hybrid",
        "query": "когда можно не делать систему удаления продуктов горения",
        "expected_keywords": ["8.2", "допускается не делать", "исключения"],
    },
    {
        "id": "sem_stairwell_press",
        "category": "general_hybrid",
        "query": "требования к подаче воздуха в лестничные клетки при пожаре",
        "expected_keywords": ["лестничн", "подпор", "пожар", "воздух"],
    },
]

def evaluate(repo_dir: str, mode: str, output_file: str):
    repo_path = Path(repo_dir).resolve()
    print(f"=== Running Evaluation for mode: {mode} using {repo_path} ===", flush=True)
    sys.path.insert(0, str(repo_path))

    from rag_server.tools import search_documents

    results = []
    use_debug = (mode != "baseline")
    
    for idx, case in enumerate(BENCHMARK_QUERIES, 1):
        qid = case["id"]
        cat = case["category"]
        query = case["query"]
        
        # Cold search (isolated cache)
        t0 = time.perf_counter()
        raw_res = search_documents(query=query, top_k=5, use_cache=False, debug=use_debug)
        t_cold = (time.perf_counter() - t0) * 1000.0

        # Warm search (cache enabled)
        t0_w = time.perf_counter()
        raw_warm = search_documents(query=query, top_k=5, use_cache=True, debug=use_debug)
        t_warm = (time.perf_counter() - t0_w) * 1000.0

        # Extract items and traces
        if isinstance(raw_res, dict):
            status = raw_res.get("status", "valid")
            error_code = raw_res.get("error_code")
            items = raw_res.get("results", [])
            trace = raw_res.get("retrieval_trace") or raw_res.get("debug", {})
            clause_status = trace.get("clause_status")
        else:
            items = raw_res if isinstance(raw_res, list) else []
            status = "valid"
            error_code = None
            trace = {}
            clause_status = None

        # 1. Exact document rank check
        doc_rank = None
        target_docs = case.get("target_docs", [])
        disallowed = case.get("disallowed_docs", [])

        if target_docs:
            for r_idx, item in enumerate(items, 1):
                src = str(item.get("source_path", "")) + " " + str(item.get("file_name", ""))
                is_disallowed = any(d.casefold() in src.casefold() for d in disallowed)
                if not is_disallowed and any(t.casefold() in src.casefold() for t in target_docs):
                    doc_rank = r_idx
                    break

        # 2. Clause rank check
        clause_rank = None
        target_clause = case.get("target_clause")
        clause_keywords = case.get("clause_keywords", [])

        if target_clause:
            for r_idx, item in enumerate(items, 1):
                sec = str(item.get("section", ""))
                txt = str(item.get("text", ""))
                c_status = item.get("clause_status") or item.get("quality", {}).get("clause_status")
                
                # Check clause match
                if c_status or f"пункт {target_clause}".casefold() in sec.casefold() or f"{target_clause}".casefold() in sec.casefold():
                    clause_rank = r_idx
                    break
                elif all(k.casefold() in txt.casefold() for k in clause_keywords):
                    clause_rank = r_idx
                    break

        # 3. Absent norm check
        absent_detected = False
        false_attribution = False
        if cat == "absent_norm":
            if status == "norm_not_found" or error_code == "norm_absent_from_corpus":
                absent_detected = True
            else:
                if items:
                    false_attribution = True

        # 4. Absent clause check
        absent_clause_detected = False
        if cat == "absent_clause":
            if clause_status == "clause_not_found" or trace.get("clause_status") == "clause_not_found":
                absent_clause_detected = True

        # 5. General hybrid check
        hybrid_hit = False
        exp_kw = case.get("expected_keywords", [])
        if cat == "general_hybrid" and exp_kw:
            for r_idx, item in enumerate(items, 1):
                txt = (str(item.get("text", "")) + " " + str(item.get("source_path", ""))).casefold()
                if any(k.casefold() in txt for k in exp_kw):
                    hybrid_hit = True
                    break

        record = {
            "id": qid,
            "category": cat,
            "query": query,
            "cold_latency_ms": t_cold,
            "warm_latency_ms": t_warm,
            "status": status,
            "error_code": error_code,
            "items_count": len(items),
            "doc_rank": doc_rank,
            "clause_rank": clause_rank,
            "absent_detected": absent_detected,
            "false_attribution": false_attribution,
            "absent_clause_detected": absent_clause_detected,
            "clause_status": clause_status,
            "hybrid_hit": hybrid_hit,
            "top_source": items[0].get("file_name") if items else None,
        }
        results.append(record)
        print(f"[{idx:02d}/55] {cat:<15} | {query[:35]:<35} | doc_rank: {str(doc_rank):<4} | clause_rank: {str(clause_rank):<4} | absent: {absent_detected} | {t_cold:.1f}ms", flush=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Saved evaluation results to {output_file}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="Repo directory to import from")
    parser.add_argument("--mode", required=True, choices=["baseline", "enr"])
    parser.add_argument("--out", required=True, help="Output JSON file")
    args = parser.parse_args()
    evaluate(args.repo, args.mode, args.out)
