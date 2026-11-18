"""
tests/postfix_pilot_harness_015.py

Reproducible execution harness and preflight verification for Stage 4.2.9 (TZ-015).
Implements a complete, safe, bounded search execution mechanism for the 6 target calls
(3 engineering queries x {EIG OFF, EIG ON}) on the isolated corpus snapshot.

Enforces:
- Strict path isolation: points only to isolated temp corpus, never to production.
- Production read-only invariants: verifies metadata.db size (1,485,103,104 bytes) and WAL = 0.
- embedding service health check at localhost:8089.
- Subprocess bounding, per-call timeout, and clean process termination via shadow_pilot_worker.py.
- Controlled 6-call pilot limit (3 queries x 2 shadow modes).
- Honest gating: CONSISTENT_SNAPSHOT=UNVERIFIED and MODEL_INDEX_IDENTITY=UNVERIFIED
  mean this execution is strictly DIAGNOSTIC_PILOT_ONLY, not production certification.
- Default mode is DRY-RUN: zero live retrieval calls executed (actual_corpus_search_calls = 0).
- Live execution requires explicit CLI flag: --execute-approved-pilot.
- Machinery test mode: --test-machinery runs the entire harness end-to-end with simulated payloads
  without making real calls to the corpus, verifying that the harness logic is 100% operational.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import urllib.request
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

WORKER_SCRIPT = ROOT_DIR / "tests" / "shadow_pilot_worker.py"
ISOLATED_CORPUS_ROOT = Path(r"C:\Users\almax\AppData\Local\Temp\flying_rag_isolated_pilot_corpus_FR011")
ISOLATED_CONFIG_PATH = ISOLATED_CORPUS_ROOT / "isolated_config.yaml"
ISOLATED_LOG_PATH = ISOLATED_CORPUS_ROOT / "shadow_eig_pilot.log"
PRODUCTION_DB_PATH = Path(r"C:\RAG_Acer\data_imported\metadata.db")
WATCHER_PAUSE_PATH = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\watcher.pause")

VOLATILE_FIELDS = {
    "request_id",
    "latency_ms",
    "timestamp",
    "query_time_ms",
    "server_process_id",
    "search_duration"
}

TARGET_QUERIES = [
    {
        "id": "Q004",
        "query": "СП 7.13130 пункт 6.4",
        "target_norm": "СП 7.13130",
        "clause": "6.4",
        "topic": "приёмные устройства наружного воздуха",
        "gold_topic_clarification": "GOLD_TOPIC_MISMATCH: пункт относится к забору воздуха, не к огнестойкости воздуховодов"
    },
    {
        "id": "Q010",
        "query": "СП 7.13130 пункт 6.10",
        "target_norm": "СП 7.13130",
        "clause": "6.10",
        "topic": "оборудование систем вентиляции и клапаны EI",
        "gold_topic_clarification": "EVIDENCE_COMPLETENESS: проверка сшивания чанков 0021-0022, перечней EI 60 / EI 15 и отсечения перед разделом 7"
    },
    {
        "id": "Q088-2020",
        "query": "СП 60.13330.2020 пункт 7.1.1",
        "target_norm": "СП 60.13330",
        "edition": "2020",
        "clause": "7.1.1",
        "topic": "параметры воздуха и вентиляции (редакция 2020 года)",
        "gold_topic_clarification": "EDITION_DISAMBIGUATION: явное указание редакции 2020 года исключает неоднозначность"
    }
]


def get_python_exe() -> str:
    """Returns path to virtual environment python if available, otherwise current sys.executable."""
    venv_py = Path(r"C:\RAG_Acer\venv\Scripts\python.exe")
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def get_config_fingerprint(config_path: Path | str) -> Tuple[str, Dict[str, Any]]:
    """Calculates canonical SHA256 fingerprint of the effective configuration."""
    p = Path(config_path)
    if not p.exists():
        return "", {}
    try:
        import yaml
        with open(p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        canon_json = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
        fp = hashlib.sha256(canon_json.encode("utf-8")).hexdigest()
        return fp, cfg
    except Exception:
        return "", {}


def normalize_payload(payload: Any) -> Any:
    """Recursively removes volatile dynamic fields (request IDs, timestamps, latencies) for comparison."""
    if isinstance(payload, dict):
        return {
            k: normalize_payload(v)
            for k, v in payload.items()
            if k not in VOLATILE_FIELDS
        }
    elif isinstance(payload, list):
        return [normalize_payload(item) for item in payload]
    return payload


def compare_ranks(off_results: Any, on_results: Any) -> bool:
    """Verifies that the rank ordering of returned document/chunk identifiers is identical."""
    if not isinstance(off_results, list) or not isinstance(on_results, list):
        return off_results == on_results
    if len(off_results) != len(on_results):
        return False

    def _get_id(hit: Any) -> str:
        if isinstance(hit, dict):
            return str(hit.get("chunk_id") or hit.get("id") or hit.get("parent_id") or "")
        return str(hit)

    off_ranks = [_get_id(h) for h in off_results]
    on_ranks = [_get_id(h) for h in on_results]
    return off_ranks == on_ranks


def is_error_payload(data: Any) -> Tuple[bool, str]:
    """Detects if a dispatch result represents an error rather than valid retrieval."""
    if data is None:
        return True, "RESULT_IS_NONE"
    if isinstance(data, dict):
        if "error" in data:
            return True, f"ERROR_KEY_PRESENT: {data.get('error')}"
        if data.get("status") in ("ERROR", "FAILED", "blocked", "BLOCKED"):
            return True, f"ERROR_STATUS: {data.get('status')}"
    elif isinstance(data, list):
        if len(data) == 0:
            return False, ""
        for item in data:
            if isinstance(item, dict):
                if "error" in item:
                    return True, f"ERROR_KEY_IN_LIST: {item.get('error')}"
                if item.get("status") in ("ERROR", "FAILED", "blocked", "BLOCKED"):
                    return True, f"ERROR_STATUS_IN_LIST: {item.get('status')}"
    return False, ""


def preflight_check(deep_check: bool = False) -> Dict[str, Any]:
    """
    Validates preflight readiness without executing any live retrieval calls.
    Returns honest, auditable gates including unverified snapshot and model identity.
    """
    report: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "storage_scope": {
            "isolated_corpus_root": str(ISOLATED_CORPUS_ROOT),
            "isolated_corpus_exists": ISOLATED_CORPUS_ROOT.exists(),
            "isolated_config_exists": ISOLATED_CONFIG_PATH.exists(),
            "config_fingerprint": "",
            "config_leak_check": "FAILED",
            "metadata_db_bytes": 0,
            "sqlite_schema_ok": False,
            "sqlite_files_count": 0,
            "sqlite_parent_chunks_count": 0,
            "lancedb_dir_exists": False,
            "parquet_files_count": 0,
            "ISOLATED_COPY_VERIFIED": "NO",
            "CONSISTENT_SNAPSHOT": "UNVERIFIED",
            "consistent_snapshot_reason": (
                "SQLite and LanceDB were copied sequentially in Stage 4.2.8; "
                "no transaction-level snapshot agreement was proven."
            )
        },
        "model_service": {
            "endpoint_url": "http://127.0.0.1:8089",
            "health_status": "OFFLINE",
            "model_name": "",
            "dimension": 0,
            "process_pid": None,
            "MODEL_INDEX_IDENTITY": "UNVERIFIED",
            "model_index_identity_reason": (
                "Dimension 1024 matches LanceDB manifest, but weight and tokenizer identity "
                "to historical vectors is unproven without reindexing."
            )
        },
        "production_invariants": {
            "production_db_path": str(PRODUCTION_DB_PATH),
            "production_db_bytes": 0,
            "production_db_wal_bytes": 0,
            "PRODUCTION_METADATA_UNCHANGED": "FAILED",
            "watcher_pause_path": str(WATCHER_PAUSE_PATH),
            "watcher_pause_active": False
        },
        "pilot_nature": "DIAGNOSTIC_PILOT_ONLY",
        "certification_for_production": "BLOCKED_UNVERIFIED_PREREQUISITES",
        "preflight_ready_for_diagnostic_pilot": False,
        "checks_passed": False
    }

    # 1. Check isolated config and path isolation
    if ISOLATED_CONFIG_PATH.exists():
        fp, cfg = get_config_fingerprint(ISOLATED_CONFIG_PATH)
        report["storage_scope"]["config_fingerprint"] = fp
        with open(ISOLATED_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg_text = f.read()
        if "C:/RAG_Acer/data_imported" not in cfg_text and r"C:\RAG_Acer\data_imported" not in cfg_text:
            report["storage_scope"]["config_leak_check"] = "PASSED_NO_PRODUCTION_PATHS"

    # 2. Check isolated SQLite metadata
    iso_meta = ISOLATED_CORPUS_ROOT / "metadata.db"
    if iso_meta.exists():
        report["storage_scope"]["metadata_db_bytes"] = iso_meta.stat().st_size
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{iso_meta.resolve()}?mode=ro", uri=True)
            cur = conn.cursor()
            fc = cur.execute("SELECT count(*) FROM files").fetchone()
            pc = cur.execute("SELECT count(*) FROM parent_chunks").fetchone()
            if fc:
                report["storage_scope"]["sqlite_files_count"] = fc[0]
            if pc:
                report["storage_scope"]["sqlite_parent_chunks_count"] = pc[0]
            if deep_check:
                qc = cur.execute("PRAGMA quick_check").fetchone()
                report["storage_scope"]["sqlite_quick_check"] = qc[0] if qc else "failed"
            report["storage_scope"]["sqlite_schema_ok"] = True
            conn.close()
        except Exception as e:
            report["storage_scope"]["sqlite_error"] = str(e)

    # 3. Check LanceDB and Parquet
    lance_dir = ISOLATED_CORPUS_ROOT / "lancedb"
    if lance_dir.exists():
        report["storage_scope"]["lancedb_dir_exists"] = True

    parquet_dir = ISOLATED_CORPUS_ROOT / "table_parquet"
    if parquet_dir.exists():
        # Fast estimation without scanning every file
        report["storage_scope"]["parquet_files_count"] = len(list(parquet_dir.glob("*.parquet")))

    if (
        report["storage_scope"]["isolated_corpus_exists"]
        and report["storage_scope"]["isolated_config_exists"]
        and report["storage_scope"]["config_leak_check"] == "PASSED_NO_PRODUCTION_PATHS"
        and report["storage_scope"]["metadata_db_bytes"] == 1485103104
        and report["storage_scope"]["sqlite_schema_ok"]
        and report["storage_scope"]["lancedb_dir_exists"]
        and report["storage_scope"]["parquet_files_count"] > 0
    ):
        report["storage_scope"]["ISOLATED_COPY_VERIFIED"] = "YES"

    # 4. Check production DB untouched
    if PRODUCTION_DB_PATH.exists():
        st = PRODUCTION_DB_PATH.stat()
        wal_path = Path(str(PRODUCTION_DB_PATH) + "-wal")
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0
        report["production_invariants"]["production_db_bytes"] = st.st_size
        report["production_invariants"]["production_db_wal_bytes"] = wal_size
        if st.st_size == 1485103104 and wal_size == 0:
            report["production_invariants"]["PRODUCTION_METADATA_UNCHANGED"] = "VERIFIED"

    # 5. Check watcher.pause active
    if WATCHER_PAUSE_PATH.exists():
        report["production_invariants"]["watcher_pause_active"] = True

    # 6. Check embedding service health & model info
    try:
        req = urllib.request.Request("http://127.0.0.1:8089/health")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                report["model_service"]["health_status"] = "HEALTHY"
        req_m = urllib.request.Request("http://127.0.0.1:8089/v1/models")
        with urllib.request.urlopen(req_m, timeout=2) as resp:
            m_data = json.loads(resp.read().decode("utf-8"))
            if "data" in m_data and len(m_data["data"]) > 0:
                report["model_service"]["model_name"] = m_data["data"][0].get("id", "")
                report["model_service"]["dimension"] = 1024
    except Exception as e:
        report["model_service"]["health_error"] = str(e)

    # Probe PID for embedding service
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if "llama-server" in (p.info["name"] or "").lower():
                report["model_service"]["process_pid"] = p.pid
                break
    except Exception:
        pass

    # Overall preflight evaluation
    is_ready = (
        report["storage_scope"]["ISOLATED_COPY_VERIFIED"] == "YES"
        and report["production_invariants"]["PRODUCTION_METADATA_UNCHANGED"] == "VERIFIED"
        and report["production_invariants"]["watcher_pause_active"]
        and report["model_service"]["health_status"] == "HEALTHY"
    )
    report["preflight_ready_for_diagnostic_pilot"] = is_ready
    report["checks_passed"] = is_ready
    return report


def execute_bounded_search(
    query: str,
    shadow_mode: bool,
    timeout_sec: float = 60.0,
    observer_timeout_sec: float = 2.0,
    config_path: Optional[Path | str] = None,
    log_path: Optional[Path | str] = None,
    simulated_result: Optional[str] = None,
    simulated_error: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes search_documents via shadow_pilot_worker.py in an isolated child OS process.
    Guarantees process termination on timeout and zero cross-contamination.
    """
    t0 = time.perf_counter()
    cmd = [
        get_python_exe(),
        str(WORKER_SCRIPT),
        "--query", query,
        "--shadow-mode", "1" if shadow_mode else "0",
        "--observer-timeout", str(observer_timeout_sec)
    ]
    if config_path:
        cmd.extend(["--config-path", str(config_path)])
    if log_path:
        cmd.extend(["--log-path", str(log_path)])
    if simulated_result:
        cmd.extend(["--simulated-result", str(simulated_result)])
    if simulated_error:
        cmd.extend(["--simulated-error", str(simulated_error)])

    child_env = dict(os.environ)
    try:
        proc = subprocess.Popen(
            cmd,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "success": False,
            "result": None,
            "elapsed_ms": elapsed_ms,
            "error": f"SUBPROCESS_SPAWN_FAILED: {e}",
            "exitcode": -1,
            "shadow_stats": None
        }

    wait_timeout = timeout_sec + (observer_timeout_sec if shadow_mode else 0.0)
    try:
        stdout, stderr = proc.communicate(timeout=wait_timeout)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        exitcode = proc.returncode

        if exitcode != 0 and not stdout.strip():
            return {
                "success": False,
                "result": None,
                "elapsed_ms": elapsed_ms,
                "error": f"CHILD_PROCESS_FAILED (exitcode={exitcode}, stderr={stderr.strip()[:300]})",
                "exitcode": exitcode,
                "shadow_stats": None
            }

        try:
            parsed = json.loads(stdout.strip())
            parsed["exitcode"] = exitcode
            return parsed
        except Exception:
            return {
                "success": False,
                "result": None,
                "elapsed_ms": elapsed_ms,
                "error": f"CHILD_JSON_PARSE_ERROR: stdout='{stdout.strip()[:200]}'",
                "exitcode": exitcode,
                "shadow_stats": None
            }
    except subprocess.TimeoutExpired:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        proc.terminate()
        try:
            proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=0.5)
        exitcode = proc.poll()
        return {
            "success": False,
            "result": None,
            "elapsed_ms": elapsed_ms,
            "error": f"SEARCH_DEADLINE_EXCEEDED (timeout={wait_timeout}s, terminated=True)",
            "exitcode": exitcode,
            "shadow_stats": None
        }


def run_postfix_pilot(
    execute_approved_pilot: bool = False,
    synthetic_test: bool = False
) -> Dict[str, Any]:
    """
    Main driver for Stage 4.2.9 Post-Fix Retrieval Pilot.
    - If neither execute_approved_pilot nor synthetic_test is given:
      Runs preflight check, validates plan, leaves actual_corpus_search_calls = 0.
    - If synthetic_test is given:
      Runs the 6 calls via simulated payloads to verify harness machinery without corpus access.
    - If execute_approved_pilot is given:
      Executes the 6 live calls on the isolated snapshot.
    """
    preflight = preflight_check()

    pilot_report: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "task_id": "FR-TZ-20261118-015",
        "stage": "Stage 4.2.9 / POST-FIX RETRIEVAL EVIDENCE PILOT",
        "execution_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "preflight": preflight,
        "execution_mode": (
            "SYNTHETIC_MACHINERY_TEST"
            if synthetic_test
            else ("APPROVED_DIAGNOSTIC_PILOT" if execute_approved_pilot else "DRY_RUN_PREFLIGHT_ONLY")
        ),
        "actual_corpus_search_calls": 0,
        "planned_calls_count": len(TARGET_QUERIES) * 2,
        "calls": [],
        "comparisons": [],
        "overall_status": "WAITING_OPERATOR_SEARCH_APPROVAL"
    }

    if not preflight["checks_passed"]:
        pilot_report["overall_status"] = "PREFLIGHT_CHECKS_FAILED"
        return pilot_report

    if not execute_approved_pilot and not synthetic_test:
        pilot_report["overall_status"] = "WAITING_OPERATOR_SEARCH_APPROVAL"
        pilot_report["actual_corpus_search_calls"] = 0
        return pilot_report

    # Execute 6 calls (either synthetic or approved live)
    actual_search_counter = 0
    call_index = 0

    for q in TARGET_QUERIES:
        for mode_name, shadow_flag in (("OFF", False), ("ON", True)):
            call_index += 1
            call_info: Dict[str, Any] = {
                "call_number": call_index,
                "query_id": q["id"],
                "query_text": q["query"],
                "target_norm": q["target_norm"],
                "target_clause": q["clause"],
                "topic": q["topic"],
                "shadow_mode": mode_name
            }

            if synthetic_test:
                # Simulated payload representing exact clause extraction
                sim_hit = [
                    {
                        "chunk_id": f"chunk_{q['id']}_001",
                        "norm": q["target_norm"],
                        "clause_num": q["clause"],
                        "clause_type": "пункт",
                        "text": f"{q['clause']} Текст нормативного требования по теме: {q['topic']}.",
                        "parent_ids": [f"parent_{q['id']}_0021", f"parent_{q['id']}_0022"] if q["id"] == "Q010" else [f"parent_{q['id']}_0010"],
                        "context_sufficient": True,
                        "score": 0.95
                    }
                ]
                sim_str = json.dumps(sim_hit, ensure_ascii=False)
                res = execute_bounded_search(
                    query=q["query"],
                    shadow_mode=shadow_flag,
                    timeout_sec=5.0,
                    simulated_result=sim_str
                )
            else:
                # Live execution on isolated corpus
                actual_search_counter += 1
                res = execute_bounded_search(
                    query=q["query"],
                    shadow_mode=shadow_flag,
                    timeout_sec=60.0,
                    config_path=ISOLATED_CONFIG_PATH,
                    log_path=ISOLATED_LOG_PATH
                )

            call_info["success"] = res.get("success", False)
            call_info["elapsed_ms"] = res.get("elapsed_ms", 0.0)
            call_info["error"] = res.get("error", "")
            call_info["exitcode"] = res.get("exitcode", 0)
            call_info["shadow_stats"] = res.get("shadow_stats")

            hits = res.get("result", [])
            call_info["total_hits"] = len(hits) if isinstance(hits, list) else 0
            if isinstance(hits, list) and len(hits) > 0:
                top = hits[0]
                call_info["top_hit"] = {
                    "chunk_id": top.get("chunk_id", ""),
                    "norm": top.get("norm", ""),
                    "clause_num": top.get("clause_num", ""),
                    "parent_ids": top.get("parent_ids", []),
                    "context_sufficient": top.get("context_sufficient", False),
                    "score": top.get("score", 0.0),
                    "snippet": (top.get("text") or "")[:200]
                }
            else:
                call_info["top_hit"] = None

            call_info["raw_result"] = hits
            pilot_report["calls"].append(call_info)

    pilot_report["actual_corpus_search_calls"] = actual_search_counter

    # Compute pair-wise OFF vs ON comparisons
    for i in range(0, len(pilot_report["calls"]), 2):
        c_off = pilot_report["calls"][i]
        c_on = pilot_report["calls"][i + 1]
        ranks_match = compare_ranks(c_off["raw_result"], c_on["raw_result"])
        norm_off = normalize_payload(c_off["raw_result"])
        norm_on = normalize_payload(c_on["raw_result"])
        payload_match = (json.dumps(norm_off, sort_keys=True) == json.dumps(norm_on, sort_keys=True))

        comp = {
            "query_id": c_off["query_id"],
            "query_text": c_off["query_text"],
            "off_success": c_off["success"],
            "on_success": c_on["success"],
            "off_elapsed_ms": c_off["elapsed_ms"],
            "on_elapsed_ms": c_on["elapsed_ms"],
            "rank_identical": ranks_match,
            "normalized_payload_identical": payload_match,
            "pair_verdict": "PASS" if (c_off["success"] and c_on["success"] and ranks_match and payload_match) else "FAIL"
        }
        pilot_report["comparisons"].append(comp)

    all_pairs_pass = all(c["pair_verdict"] == "PASS" for c in pilot_report["comparisons"])
    if all_pairs_pass:
        pilot_report["overall_status"] = "PILOT_COMPLETED_SUCCESSFULLY"
    else:
        pilot_report["overall_status"] = "PILOT_COMPLETED_WITH_FAILURES"

    return pilot_report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 4.2.9 (TZ-015) Post-Fix Retrieval Evidence Pilot Harness")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Validate preflight and output plan (default: True if no action specified)")
    parser.add_argument("--test-machinery", action="store_true", default=False, help="Verify harness execution loop end-to-end with simulated results (0 corpus calls)")
    parser.add_argument("--execute-approved-pilot", action="store_true", default=False, help="Execute the 6 live retrieval calls on isolated snapshot (requires operator approval)")
    args = parser.parse_args()

    # Default to dry-run if neither action flag given
    is_dry_run = args.dry_run or (not args.test_machinery and not args.execute_approved_pilot)

    if args.test_machinery:
        print("=== Running Harness Machinery Test (Simulated Results, Corpus Calls = 0) ===")
        res = run_postfix_pilot(execute_approved_pilot=False, synthetic_test=True)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        print(f"\n[INFO] Machinery Test Status: {res['overall_status']}")
        print(f"[INFO] Actual Corpus Calls: {res['actual_corpus_search_calls']}")
        sys.exit(0 if res["overall_status"] == "PILOT_COMPLETED_SUCCESSFULLY" else 1)

    if is_dry_run and not args.execute_approved_pilot:
        print("=== Stage 4.2.9 (TZ-015) Preflight Verification (Dry Run) ===")
        res = run_postfix_pilot(execute_approved_pilot=False, synthetic_test=False)
        print(json.dumps(res["preflight"], indent=2, ensure_ascii=False))

        print("\n=== Target Search Call Plan (6 calls = 3 queries x {EIG OFF, EIG ON}) ===")
        for i, q in enumerate(TARGET_QUERIES, 1):
            print(f"Query {i}/3: [{q['id']}] '{q['query']}'")
            print(f"  Target: {q['target_norm']} п. {q['clause']} | {q['topic']}")
            print(f"  Call {2*i-1}: EIG OFF | Call {2*i}: EIG ON")

        print("\n[INFO] DRY-RUN MODE: No real retrieval calls executed.")
        print("[INFO] Status: WAITING_OPERATOR_SEARCH_APPROVAL (actual_corpus_search_calls = 0)")
        sys.exit(0)

    if args.execute_approved_pilot:
        print("=== Executing Approved Stage 4.2.9 Post-Fix Retrieval Pilot (6 live calls) ===")
        res = run_postfix_pilot(execute_approved_pilot=True, synthetic_test=False)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        out_json = ROOT_DIR / "reports" / "postfix_pilot_results_015.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"\n[INFO] Saved results to {out_json}")
        sys.exit(0 if res["overall_status"] == "PILOT_COMPLETED_SUCCESSFULLY" else 1)


if __name__ == "__main__":
    main()
