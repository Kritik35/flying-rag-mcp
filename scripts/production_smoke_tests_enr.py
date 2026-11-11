#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Smoke Tests for FlyingRAG with Exact Norm Resolution (ENR).
Executed against merged integration/acer-qwen-embedding (commit 9c0a609)
using real stdio JSON-RPC MCP transport.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = r"C:\RAG_Acer\repos\flying-rag-mcp"
VENV_PYTHON = r"C:\RAG_Acer\venv\Scripts\python.exe"
CONFIG_PATH = r"C:\RAG_Acer\configs\config.yaml"

def run_smoke_tests():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    print("=" * 80, flush=True)
    print("FLYINGRAG PRODUCTION ENR SMOKE TESTS (REAL MCP TRANSPORT)", flush=True)
    print("=" * 80, flush=True)

    env = {
        **os.environ,
        "PYTHONPATH": REPO_DIR,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "FLYING_RAG_CONFIG": CONFIG_PATH,
    }

    # Spawning MCP server via main.py in the production repo
    proc = subprocess.Popen(
        [VENV_PYTHON, "-u", str(Path(REPO_DIR) / "main.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        encoding="utf-8",
        cwd=REPO_DIR,
        env=env,
    )

    req_id = 0

    def send_recv(req: dict) -> dict:
        nonlocal req_id
        req_id += 1
        req["id"] = req_id
        req["jsonrpc"] = "2.0"
        line = json.dumps(req, ensure_ascii=False)
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
        resp_line = proc.stdout.readline()
        if not resp_line:
            raise RuntimeError("Server closed connection unexpectedly.")
        return json.loads(resp_line)

    def call_tool(name: str, arguments: dict) -> dict:
        req = {
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            }
        }
        res = send_recv(req)
        content_text = res.get("result", {}).get("content", [{}])[0].get("text", "{}")
        return json.loads(content_text)

    results_summary = []

    try:
        # Initialize MCP Handshake
        t0 = time.perf_counter()
        init_res = send_recv({
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "production-smoke-tester", "version": "1.0"}
            }
        })
        init_time = (time.perf_counter() - t0) * 1000.0
        server_info = init_res.get("result", {}).get("serverInfo", {})
        print(f"[OK] MCP Server Initialized in {init_time:.1f} ms: {server_info} (PID {proc.pid})", flush=True)

        # Send notifications/initialized
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        # ── Test 1: СП 7.13130.2013 ──────────────────────────────────────────
        print("\n[TEST 1] СП 7.13130.2013 — первичный норматив (не СП 153)...", flush=True)
        t0 = time.perf_counter()
        d1 = call_tool("search_documents", {"query": "СП 7.13130.2013", "top_k": 5, "debug": True})
        lat1 = (time.perf_counter() - t0) * 1000.0
        res1 = d1.get("results", [])
        top_doc1 = res1[0].get("file_name", "") if res1 else ""
        pass1 = ("7.13130" in top_doc1) and ("153" not in top_doc1)
        print(f"  Latency: {lat1:.1f} ms | Top document: {top_doc1} | Status: {'PASS' if pass1 else 'FAIL'}", flush=True)
        assert pass1, f"Expected СП 7.13130, got {top_doc1}"
        results_summary.append(("Test 1: СП 7.13130.2013", lat1, "PASS" if pass1 else "FAIL", f"Top: {top_doc1}"))

        # ── Test 2: СП 7.13130 пункт 6.4 ─────────────────────────────────────
        print("\n[TEST 2] СП 7.13130 пункт 6.4 — проверка точного пункта 6.4 (не 6.4.1)...", flush=True)
        t0 = time.perf_counter()
        d2 = call_tool("search_documents", {"query": "СП 7.13130 пункт 6.4", "top_k": 3, "debug": True})
        lat2 = (time.perf_counter() - t0) * 1000.0
        debug2 = d2.get("debug", {})
        cl_stat2 = debug2.get("clause_status")
        tgt_cl2 = debug2.get("target_clause")
        res2 = d2.get("results", [])
        top_txt2 = res2[0].get("text", "") if res2 else ""
        pass2 = (cl_stat2 == "clause_matched" or "6.4" in top_txt2) and (tgt_cl2 == "6.4")
        print(f"  Latency: {lat2:.1f} ms | Clause Status: {cl_stat2} | Target: {tgt_cl2} | Top text: {top_txt2[:80]}...", flush=True)
        assert pass2, f"Expected target_clause 6.4, got {tgt_cl2}"
        results_summary.append(("Test 2: СП 7.13130 п. 6.4", lat2, "PASS" if pass2 else "FAIL", f"Status: {cl_stat2}"))

        # ── Test 3: СП 7.13130 пункт 99.99 ───────────────────────────────────
        print("\n[TEST 3] СП 7.13130 пункт 99.99 — clause_not_found (без вымышленного пункта)...", flush=True)
        t0 = time.perf_counter()
        d3 = call_tool("search_documents", {"query": "СП 7.13130 пункт 99.99", "top_k": 3, "debug": True})
        lat3 = (time.perf_counter() - t0) * 1000.0
        debug3 = d3.get("debug", {})
        cl_stat3 = debug3.get("clause_status")
        tgt_cl3 = debug3.get("target_clause")
        res3 = d3.get("results", [])
        top_doc3 = res3[0].get("file_name", "") if res3 else ""
        pass3 = (cl_stat3 == "clause_not_found") and (tgt_cl3 == "99.99") and ("7.13130" in top_doc3)
        print(f"  Latency: {lat3:.1f} ms | Clause Status: {cl_stat3} | Target: {tgt_cl3} | Top doc: {top_doc3}", flush=True)
        assert pass3, f"Expected clause_not_found, got {cl_stat3}"
        results_summary.append(("Test 3: СП 7.13130 п. 99.99", lat3, "PASS" if pass3 else "FAIL", f"Status: {cl_stat3}"))

        # ── Test 4: ГЭСН 08-01-001 ───────────────────────────────────────────
        print("\n[TEST 4] ГЭСН 08-01-001 — norm_not_found (без подмены СП 331)...", flush=True)
        t0 = time.perf_counter()
        d4 = call_tool("search_documents", {"query": "ГЭСН 08-01-001", "top_k": 3, "debug": True})
        lat4 = (time.perf_counter() - t0) * 1000.0
        st4 = d4.get("status")
        err4 = d4.get("error_code")
        res4 = d4.get("results", [])
        pass4 = (st4 == "norm_not_found") and (err4 == "norm_absent_from_corpus") and (len(res4) == 0)
        print(f"  Latency: {lat4:.1f} ms | Status: {st4} | Error: {err4} | Results len: {len(res4)}", flush=True)
        assert pass4, f"Expected norm_not_found, got {st4}"
        results_summary.append(("Test 4: ГЭСН 08-01-001", lat4, "PASS" if pass4 else "FAIL", f"Status: {st4}"))

        # ── Test 5: СП 7.13130 и ГЭСН 08-01-001 ──────────────────────────────
        print("\n[TEST 5] СП 7.13130 и ГЭСН 08-01-001 — независимое разрешение, partial_found...", flush=True)
        t0 = time.perf_counter()
        d5 = call_tool("search_documents", {"query": "СП 7.13130 и ГЭСН 08-01-001", "top_k": 3, "debug": True})
        lat5 = (time.perf_counter() - t0) * 1000.0
        debug5 = d5.get("debug", {})
        resols5 = debug5.get("norm_resolutions", [])
        res5 = d5.get("results", [])
        top_doc5 = res5[0].get("file_name", "") if res5 else ""
        sp_found = any("7.13130" in r.get("target", "") and r.get("status") in ("found", "edition_unverified") for r in resols5)
        gesn_absent = any("08-01-001" in r.get("target", "") and r.get("status") == "norm_absent_from_corpus" for r in resols5)
        pass5 = sp_found and gesn_absent and ("7.13130" in top_doc5)
        print(f"  Latency: {lat5:.1f} ms | SP found: {sp_found} | GESN absent: {gesn_absent} | Top doc: {top_doc5}", flush=True)
        assert pass5, "Multi-norm contract failed"
        results_summary.append(("Test 5: Мульти-норматив СП + ГЭСН", lat5, "PASS" if pass5 else "FAIL", "partial_found OK"))

        # ── Test 6: Неподтверждённая редакция (СП 7.13130.2012) ───────────────
        print("\n[TEST 6] СП 7.13130.2012 требования — предупреждение edition_unverified...", flush=True)
        t0 = time.perf_counter()
        d6 = call_tool("search_documents", {"query": "СП 7.13130.2012 требования", "top_k": 3, "debug": True})
        lat6 = (time.perf_counter() - t0) * 1000.0
        debug6 = d6.get("debug", {})
        ed_st6 = debug6.get("edition_status")
        resols6 = debug6.get("norm_resolutions", [])
        warning6 = resols6[0].get("warning", "") if resols6 else ""
        pass6 = (ed_st6 == "edition_unverified") and ("2012" in warning6) and ("2013" in warning6)
        print(f"  Latency: {lat6:.1f} ms | Edition Status: {ed_st6} | Warning: {warning6}", flush=True)
        assert pass6, f"Expected edition_unverified, got {ed_st6}"
        results_summary.append(("Test 6: Неподтверждённая редакция", lat6, "PASS" if pass6 else "FAIL", f"Status: {ed_st6}"))

        # ── Test 7: Повторный идентичный запрос (Exact Cache Hit) ─────────────
        print("\n[TEST 7] Повторный идентичный нормативный запрос — Exact Cache Hit...", flush=True)
        # Call with exact query from Test 1
        t0 = time.perf_counter()
        d7 = call_tool("search_documents", {"query": "СП 7.13130.2013", "top_k": 5, "debug": True})
        lat7 = (time.perf_counter() - t0) * 1000.0
        debug7 = d7.get("debug", {})
        cache_hit7 = debug7.get("cache_hit")
        score_kind7 = debug7.get("retrieval", {}).get("score_kind")
        pass7 = (cache_hit7 is True) or (score_kind7 == "cache")
        print(f"  Latency: {lat7:.1f} ms | Cache hit: {cache_hit7} | Score kind: {score_kind7}", flush=True)
        assert pass7, f"Expected cache_hit=True, got {cache_hit7}"
        results_summary.append(("Test 7: Повторный запрос (кэш)", lat7, "PASS" if pass7 else "FAIL", f"{lat7:.1f} ms"))

        # ── Test 8: Общий инженерный запрос без шифра (Hybrid) ────────────────
        print("\n[TEST 8] Общий инженерный запрос — штатный Hybrid без регрессии...", flush=True)
        t0 = time.perf_counter()
        d8 = call_tool("search_documents", {"query": "противопожарные клапаны в воздуховодах", "top_k": 5, "debug": True})
        lat8 = (time.perf_counter() - t0) * 1000.0
        debug8 = d8.get("debug", {})
        res8 = d8.get("results", [])
        route8 = debug8.get("route")
        pass8 = (len(res8) >= 3) and (route8 in ("default", "normative_fire", "normative", "general"))
        top_txt8 = res8[0].get("text", "")[:80] if res8 else ""
        print(f"  Latency: {lat8:.1f} ms | Results count: {len(res8)} | Route: {route8} | Top text: {top_txt8}...", flush=True)
        assert pass8, f"Expected >= 3 results, got {len(res8)}"
        results_summary.append(("Test 8: Общий инженерный гибрид", lat8, "PASS" if pass8 else "FAIL", f"Results: {len(res8)}"))

        # ── Test 9: debug=True с use_cache=False ─────────────────────────────
        print("\n[TEST 9] Режим debug=True с use_cache=False — чистый обход кэша...", flush=True)
        t0 = time.perf_counter()
        d9 = call_tool("search_documents", {"query": "СП 7.13130.2013", "top_k": 5, "debug": True, "use_cache": False})
        lat9 = (time.perf_counter() - t0) * 1000.0
        debug9 = d9.get("debug", {})
        cache_hit9 = debug9.get("cache_hit")
        channels9 = debug9.get("retrieval", {}).get("channels", [])
        pass9 = (cache_hit9 is not True) and ("exact_cache" not in channels9)
        print(f"  Latency: {lat9:.1f} ms | Cache hit: {cache_hit9} | Channels: {channels9}", flush=True)
        assert pass9, f"Expected no cache hit when use_cache=False, got {cache_hit9}"
        results_summary.append(("Test 9: use_cache=False bypass", lat9, "PASS" if pass9 else "FAIL", "Bypass verified"))

        print("\n" + "=" * 80, flush=True)
        print("ALL PRODUCTION SMOKE TESTS COMPLETED SUCCESSFULLY!", flush=True)
        print("=" * 80, flush=True)
        for name, lat, status, detail in results_summary:
            print(f"  [{status}] {name:<35} | {lat:>8.1f} ms | {detail}", flush=True)
        print("=" * 80, flush=True)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    run_smoke_tests()
