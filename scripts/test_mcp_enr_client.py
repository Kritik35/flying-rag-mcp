#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests genuine MCP calls against the experimental FlyingRAG ENR MCP server
running from C:\\RAG_Acer\\repos\\flying-rag-mcp-stage-e using unbuffered stdio JSON-RPC.
Verifies:
  1. norm_not_found (ГЭСН 08-01-001)
  2. clause_not_found (СП 7.13130 пункт 99.99)
  3. edition_unverified (СП 7.13130.2012 требования)
  4. partial_found (СП 7.13130 и ГЭСН 08-01-001)
"""
import json
import os
import subprocess
import sys
import time

VENV_PYTHON = r"C:\RAG_Acer\venv\Scripts\python.exe"
STAGE_E_DIR = r"C:\RAG_Acer\repos\flying-rag-mcp-stage-e"

def run_mcp_tests():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    print("=" * 70, flush=True)
    print("STARTING GENUINE MCP TEST AGAINST EXPERIMENTAL ENR SERVER", flush=True)
    print("=" * 70, flush=True)

    env = {
        **os.environ,
        "PYTHONPATH": STAGE_E_DIR,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(
        [VENV_PYTHON, "-u", "-m", "rag_server.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        encoding="utf-8",
        cwd=STAGE_E_DIR,
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

    try:
        # 1. Initialize MCP
        init_res = send_recv({
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"}
            }
        })
        print(f"[OK] MCP Initialized: {init_res.get('result', {}).get('serverInfo')}", flush=True)

        # Send initialized notification
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        # ── 1. TEST norm_not_found ───────────────────────────────────────────
        print("\n--- 1. Testing genuine MCP call: norm_not_found (ГЭСН 08-01-001) ---", flush=True)
        t0 = time.perf_counter()
        data1 = call_tool("search_documents", {"query": "ГЭСН 08-01-001", "top_k": 3, "debug": True})
        t1 = (time.perf_counter() - t0) * 1000.0
        print(f"Latency: {t1:.1f} ms", flush=True)
        print(f"Status: {data1.get('status')}", flush=True)
        print(f"Error Code: {data1.get('error_code')}", flush=True)
        print(f"Target Norm: {data1.get('target_norm')}", flush=True)
        print(f"Results len: {len(data1.get('results', []))}", flush=True)
        assert data1.get("status") == "norm_not_found", f"Expected norm_not_found, got {data1.get('status')}"
        assert data1.get("error_code") == "norm_absent_from_corpus"
        assert len(data1.get("results", [])) == 0, "Results array must be strictly empty for absent norm"
        print("[OK] [PASS] norm_not_found contract verified via real MCP call!", flush=True)

        # ── 2. TEST clause_not_found ─────────────────────────────────────────
        print("\n--- 2. Testing genuine MCP call: clause_not_found (СП 7.13130 пункт 99.99) ---", flush=True)
        t0 = time.perf_counter()
        data2 = call_tool("search_documents", {"query": "СП 7.13130 пункт 99.99", "top_k": 3, "debug": True})
        t2 = (time.perf_counter() - t0) * 1000.0
        print(f"Latency: {t2:.1f} ms", flush=True)
        debug2 = data2.get("debug", {})
        clause_st2 = debug2.get("clause_status")
        target_cl2 = debug2.get("target_clause")
        results2 = data2.get("results", [])
        print(f"Clause Status: {clause_st2}", flush=True)
        print(f"Target Clause: {target_cl2}", flush=True)
        print(f"Document results count: {len(results2)}", flush=True)
        if results2:
            print(f"Top document: {results2[0].get('file_name')}", flush=True)
        assert clause_st2 == "clause_not_found", f"Expected clause_not_found, got {clause_st2}"
        assert target_cl2 == "99.99"
        assert len(results2) > 0, "Document chunks must be returned when document is present"
        assert "7.13130" in (results2[0].get("file_name") or "")
        print("[OK] [PASS] clause_not_found contract verified via real MCP call!", flush=True)

        # ── 3. TEST edition_unverified ───────────────────────────────────────
        print("\n--- 3. Testing genuine MCP call: edition_unverified (СП 7.13130.2012) ---", flush=True)
        t0 = time.perf_counter()
        data3 = call_tool("search_documents", {"query": "СП 7.13130.2012 требования", "top_k": 3, "debug": True})
        t3 = (time.perf_counter() - t0) * 1000.0
        print(f"Latency: {t3:.1f} ms", flush=True)
        debug3 = data3.get("debug", {})
        ed_status3 = debug3.get("edition_status")
        resolutions3 = debug3.get("norm_resolutions", [])
        print(f"Edition Status: {ed_status3}", flush=True)
        print(f"Norm Resolutions: {resolutions3}", flush=True)
        assert ed_status3 == "edition_unverified", f"Expected edition_unverified, got {ed_status3}"
        assert any(r.get("status") == "edition_unverified" for r in resolutions3)
        print("[OK] [PASS] edition_unverified contract verified via real MCP call!", flush=True)

        # ── 4. TEST partial_found (multi-norm with mixed presence) ──────────
        print("\n--- 4. Testing genuine MCP call: partial_found (СП 7.13130 и ГЭСН 08-01-001) ---", flush=True)
        t0 = time.perf_counter()
        data4 = call_tool("search_documents", {"query": "СП 7.13130 и ГЭСН 08-01-001", "top_k": 3, "debug": True})
        t4 = (time.perf_counter() - t0) * 1000.0
        print(f"Latency: {t4:.1f} ms", flush=True)
        debug4 = data4.get("debug", {})
        resolutions4 = debug4.get("norm_resolutions", [])
        results4 = data4.get("results", [])
        print(f"Resolutions ({len(resolutions4)}):", flush=True)
        for r in resolutions4:
            print(f"  -> target: {r.get('target')} | status: {r.get('status')} | file: {r.get('file_name')}", flush=True)
        print(f"Results count: {len(results4)}", flush=True)
        if results4:
            print(f"Top result: {results4[0].get('file_name')}", flush=True)
        
        statuses = {r.get("target"): r.get("status") for r in resolutions4}
        assert any("7.13130" in t and s in ("found", "edition_unverified") for t, s in statuses.items())
        assert any("08-01-001" in t and s == "norm_absent_from_corpus" for t, s in statuses.items())
        assert len(results4) > 0, "Present standard chunks must be returned"
        assert "7.13130" in (results4[0].get("file_name") or "")
        print("[OK] [PASS] partial_found multi-norm contract verified via real MCP call!", flush=True)

        print("\n" + "=" * 70, flush=True)
        print("ALL 4 GENUINE MCP TESTS COMPLETED AND VERIFIED SUCCESSFULLY!", flush=True)
        print("=" * 70, flush=True)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    run_mcp_tests()
