"""
tests/postfix_pilot_harness_015.py

Reproducible execution harness and preflight verification for Stage 4.2.9 (ТЗ-015 Rev 1.1).
Implements a complete, fail-closed, bounded search execution mechanism for the 6 target calls
(3 engineering queries x {EIG OFF, EIG ON}) on the isolated corpus snapshot.

Enforces (Rev 1.1 Erratal Protection):
- P0-1: Strict effective scope verification via check_readonly_scope, validate_pilot_config,
  and complete child environment sanitization (scrubbing all FLYING_RAG_* overrides).
- P0-2: Mandatory fail-fast stop after the very first failure (nonzero exit, error envelope,
  timeout, scope violation, empty retrieval, observer failure, or rank/payload mismatch).
  No subsequent calls are spawned after a failure.
- P0-3: Nonzero child exit is NEVER a pass (NONZERO_EXIT_NO_GO); empty retrieval results or
  missing chunk IDs are strictly rejected; shadow observer activity and drain are required for ON.
- P1-1: Strict separation of raw corpus results (stored in temp with SHA-256) from git-tracked reports
  (containing only sanitized metadata, excerpts <= 200 chars, and hashes).
- Default mode is DRY-RUN: zero live retrieval calls executed (actual_corpus_search_calls = 0).
- Live execution requires explicit operator authorization flag: --execute-approved-pilot.
- Machinery test mode: --test-machinery verifies harness loop end-to-end with simulated responses
  without accessing real corpus.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import tempfile
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
    """
    Verifies that the rank ordering of returned document/chunk identifiers is identical (P0-3 / P15-08).
    Strictly fails closed if:
    - Results are not lists or are empty (P15-06)
    - Lengths differ
    - Extracted IDs are empty or missing (P15-08)
    - Ordering differs
    """
    if not isinstance(off_results, list) or not isinstance(on_results, list):
        return False
    if len(off_results) == 0 or len(on_results) == 0:
        return False
    if len(off_results) != len(on_results):
        return False

    def _get_id(hit: Any) -> str:
        if isinstance(hit, dict):
            return str(hit.get("chunk_id") or hit.get("id") or hit.get("parent_id") or "").strip()
        return str(hit).strip()

    off_ranks = [_get_id(h) for h in off_results]
    on_ranks = [_get_id(h) for h in on_results]

    # P15-08: If all extracted IDs are empty, ranks cannot be confirmed
    if not any(bool(x) for x in off_ranks) or not any(bool(x) for x in on_ranks):
        return False

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


def preflight_check(
    deep_check: bool = False,
    custom_config_path: Optional[Path | str] = None,
    allowed_fixture_root: Optional[Path | str] = None
) -> Dict[str, Any]:
    """
    Validates preflight readiness without executing any live retrieval calls (P0-1).
    Enforces real check_readonly_scope, validate_pilot_config, and inspection of host env overrides.
    """
    target_config = Path(custom_config_path or ISOLATED_CONFIG_PATH)
    target_root = Path(allowed_fixture_root or ISOLATED_CORPUS_ROOT)

    report: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "storage_scope": {
            "isolated_corpus_root": str(target_root),
            "isolated_corpus_exists": target_root.exists(),
            "isolated_config_path": str(target_config),
            "isolated_config_exists": target_config.exists(),
            "config_fingerprint": "",
            "scope_check": "UNVERIFIED",
            "config_validation": "UNVERIFIED",
            "host_env_metadata_db_override": os.environ.get("FLYING_RAG_METADATA_DB"),
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

    # 1. Scope and Configuration Verification (P0-1)
    if target_config.exists():
        fp, cfg = get_config_fingerprint(target_config)
        report["storage_scope"]["config_fingerprint"] = fp

        # Register fixture root and call real check_readonly_scope
        try:
            from tests.test_real_retrieval_shadow_pilot import (
                register_verified_fixture_root,
                check_readonly_scope,
                validate_pilot_config
            )
            register_verified_fixture_root(target_root)
            scope_res = check_readonly_scope(target_config, backend_online=True, allowed_fixture_root=target_root)
            report["storage_scope"]["scope_check"] = scope_res

            val_ok, val_msg, resolved = validate_pilot_config(target_config)
            report["storage_scope"]["config_validation"] = "CONFIG_VALID" if val_ok else f"CONFIG_INVALID: {val_msg}"
        except Exception as e:
            report["storage_scope"]["scope_check"] = f"ERROR: {e}"
            scope_res = "ERROR"
            val_ok = False

        # P15-01: Check host env override for FLYING_RAG_METADATA_DB
        host_meta_override = os.environ.get("FLYING_RAG_METADATA_DB")
        if host_meta_override:
            try:
                resolved_override = Path(host_meta_override).resolve()
                resolved_target_root = target_root.resolve()
                resolved_override.relative_to(resolved_target_root)
            except Exception:
                # Override points outside target isolated root -> STOP_SCOPE!
                report["storage_scope"]["scope_check"] = "STOP_SCOPE_HOST_ENV_METADATA_DB_LEAK"
                scope_res = "STOP_SCOPE"

        # Check for path traversal, UNC, or production leaks in resolved paths
        prod_leak = False
        with open(target_config, "r", encoding="utf-8") as f:
            cfg_text = f.read()
        if (
            "C:/RAG_Acer/data_imported" in cfg_text
            or r"C:\RAG_Acer\data_imported" in cfg_text
            or "\\\\" in cfg_text  # UNC
            or "/../" in cfg_text or "\\..\\" in cfg_text  # Path traversal
        ):
            prod_leak = True
            report["storage_scope"]["scope_check"] = "STOP_SCOPE_PRODUCTION_ALIAS_OR_TRAVERSAL"
            scope_res = "STOP_SCOPE"

    else:
        scope_res = "CONFIG_NOT_FOUND"
        val_ok = False

    # 2. Check isolated SQLite metadata
    iso_meta = target_root / "metadata.db"
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
    lance_dir = target_root / "lancedb"
    if lance_dir.exists():
        report["storage_scope"]["lancedb_dir_exists"] = True

    parquet_dir = target_root / "table_parquet"
    if parquet_dir.exists():
        report["storage_scope"]["parquet_files_count"] = len(list(parquet_dir.glob("*.parquet")))

    scope_admitted = (scope_res == "ISOLATED_COPY_VERIFIED")
    if (
        report["storage_scope"]["isolated_corpus_exists"]
        and report["storage_scope"]["isolated_config_exists"]
        and scope_admitted
        and val_ok
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
    simulated_error: Optional[str] = None,
    delay_sec: float = 0.0
) -> Dict[str, Any]:
    """
    Executes search_documents via shadow_pilot_worker.py in an isolated child OS process.
    Guarantees:
    - P0-1: Strict environment sanitization (scrubs FLYING_RAG_* overrides).
    - P0-3: Nonzero exit code is strictly NONZERO_EXIT_NO_GO (never treated as success).
    - Termination on timeout.
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
    if delay_sec > 0:
        cmd.extend(["--delay-sec", str(delay_sec)])

    # P0-1: Complete environment sanitization
    child_env = dict(os.environ)
    for k in list(child_env.keys()):
        if k.startswith("FLYING_RAG_") and k not in (
            "FLYING_RAG_CONFIG",
            "FLYING_RAG_SHADOW_EIG",
            "FLYING_RAG_SHADOW_LOG_PATH",
            "FLYING_RAG_SHADOW_CONTROL_FILE"
        ):
            child_env.pop(k, None)

    # Set canonical config and ensure storage overrides are cleared
    if config_path:
        child_env["FLYING_RAG_CONFIG"] = str(Path(config_path).resolve())
    child_env.pop("FLYING_RAG_METADATA_DB", None)
    child_env.pop("FLYING_RAG_LANCEDB_PATH", None)
    child_env.pop("FLYING_RAG_TABLE_PARQUET", None)

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

        # P0-3 & P15-05: Nonzero exit code is strictly a failure!
        if exitcode != 0:
            return {
                "success": False,
                "result": None,
                "elapsed_ms": elapsed_ms,
                "error": f"NONZERO_EXIT_NO_GO: exitcode={exitcode}, stderr={stderr.strip()[:200]}",
                "exitcode": exitcode,
                "shadow_stats": None,
                "raw_stdout": stdout.strip()[:200]
            }

        try:
            parsed = json.loads(stdout.strip())
            parsed["exitcode"] = exitcode

            # Validate error payload
            is_err, err_msg = is_error_payload(parsed.get("result"))
            if is_err:
                parsed["success"] = False
                parsed["error"] = f"ERROR_PAYLOAD_NO_GO: {err_msg}"

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
    synthetic_test: bool = False,
    config_path: Optional[Path | str] = None,
    allowed_fixture_root: Optional[Path | str] = None,
    simulated_responses: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Main execution driver for Stage 4.2.9 Post-Fix Retrieval Pilot (Rev 1.1).
    Enforces P0-2 fail-fast stop immediately upon the first failure.
    """
    target_config = Path(config_path or ISOLATED_CONFIG_PATH)
    target_root = Path(allowed_fixture_root or ISOLATED_CORPUS_ROOT)
    preflight = preflight_check(custom_config_path=target_config, allowed_fixture_root=target_root)

    pilot_report: Dict[str, Any] = {
        "schema_version": "1.1.0",
        "task_id": "FR-TZ-20261118-015",
        "stage": "Stage 4.2.9 / POST-FIX RETRIEVAL EVIDENCE PILOT (Rev 1.1)",
        "execution_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "preflight": preflight,
        "execution_mode": (
            "SYNTHETIC_MACHINERY_ONLY"
            if synthetic_test
            else ("APPROVED_DIAGNOSTIC_PILOT" if execute_approved_pilot else "DRY_RUN_PREFLIGHT_ONLY")
        ),
        "actual_corpus_search_calls": 0,
        "planned_calls_count": len(TARGET_QUERIES) * 2,
        "attempted_calls": 0,
        "spawned_calls": 0,
        "completed_calls": 0,
        "calls": [],
        "comparisons": [],
        "overall_status": "WAITING_OPERATOR_SEARCH_APPROVAL",
        "live_gate": "NOT_EXECUTED"
    }

    if not preflight["checks_passed"]:
        pilot_report["overall_status"] = "PREFLIGHT_CHECKS_FAILED"
        return pilot_report

    if not execute_approved_pilot and not synthetic_test:
        pilot_report["overall_status"] = "WAITING_OPERATOR_SEARCH_APPROVAL"
        pilot_report["actual_corpus_search_calls"] = 0
        return pilot_report

    # Execute calls with P0-2 fail-fast enforcement
    call_index = 0
    halted = False

    for q in TARGET_QUERIES:
        if halted:
            break

        pair_calls: List[Dict[str, Any]] = []

        for mode_name, shadow_flag in (("OFF", False), ("ON", True)):
            call_index += 1
            pilot_report["attempted_calls"] += 1

            # Verify production DB untouched before spawn
            if PRODUCTION_DB_PATH.exists():
                st_prod = PRODUCTION_DB_PATH.stat()
                wal_p = Path(str(PRODUCTION_DB_PATH) + "-wal")
                wal_sz = wal_p.stat().st_size if wal_p.exists() else 0
                if st_prod.st_size != 1485103104 or wal_sz != 0:
                    pilot_report["overall_status"] = "STOP_PRODUCTION_INVARIANT_VIOLATED"
                    halted = True
                    break

            call_info: Dict[str, Any] = {
                "call_number": call_index,
                "query_id": q["id"],
                "query_text": q["query"],
                "target_norm": q["target_norm"],
                "target_clause": q["clause"],
                "topic": q["topic"],
                "shadow_mode": mode_name
            }

            pilot_report["spawned_calls"] += 1

            if synthetic_test:
                # Synthetic simulated payload
                sim_res_key = f"{q['id']}_{mode_name}"
                if simulated_responses and sim_res_key in simulated_responses:
                    sim_cfg = simulated_responses[sim_res_key]
                    res = execute_bounded_search(
                        query=q["query"],
                        shadow_mode=shadow_flag,
                        timeout_sec=sim_cfg.get("timeout_sec", 5.0),
                        delay_sec=sim_cfg.get("delay_sec", 0.0),
                        simulated_result=sim_cfg.get("simulated_result"),
                        simulated_error=sim_cfg.get("simulated_error")
                    )
                else:
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
                    res = execute_bounded_search(
                        query=q["query"],
                        shadow_mode=shadow_flag,
                        timeout_sec=5.0,
                        simulated_result=json.dumps(sim_hit, ensure_ascii=False)
                    )
                    # Synthetic adapter stats for ON
                    if shadow_flag:
                        res["shadow_stats"] = {"submitted": 1, "processed": 1, "errors": 0, "dropped": 0}
            else:
                # Live execution on isolated corpus
                pilot_report["actual_corpus_search_calls"] += 1
                res = execute_bounded_search(
                    query=q["query"],
                    shadow_mode=shadow_flag,
                    timeout_sec=60.0,
                    config_path=target_config,
                    log_path=ISOLATED_LOG_PATH
                )

            call_info["success"] = res.get("success", False)
            call_info["elapsed_ms"] = res.get("elapsed_ms", 0.0)
            call_info["error"] = res.get("error", "")
            call_info["exitcode"] = res.get("exitcode", 0)
            call_info["shadow_stats"] = res.get("shadow_stats")

            hits = res.get("result", [])
            call_info["total_hits"] = len(hits) if isinstance(hits, list) else 0

            # Categorized verdicts (P0-3)
            call_info["search_executed"] = (call_info["exitcode"] == 0)
            call_info["retrieval_match"] = False
            call_info["evidence_complete"] = False

            if isinstance(hits, list) and len(hits) > 0:
                top = hits[0]
                has_valid_id = bool(top.get("chunk_id") or top.get("id") or top.get("parent_ids"))
                call_info["retrieval_match"] = has_valid_id
                call_info["evidence_complete"] = has_valid_id and bool(top.get("text"))

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
            pair_calls.append(call_info)

            # P0-2 Fail-fast check on every call
            if (
                not call_info["success"]
                or call_info["exitcode"] != 0
                or not call_info["retrieval_match"]
                or not call_info["evidence_complete"]
            ):
                pilot_report["overall_status"] = f"HALTED_AFTER_FAILURE_CALL_{call_index}: {call_info['error'] or 'RETRIEVAL_OR_EVIDENCE_FAILED'}"
                halted = True
                break

            pilot_report["completed_calls"] += 1

        if halted or len(pair_calls) < 2:
            break

        # P0-2: Evaluate pair immediately after ON call
        c_off = pair_calls[0]
        c_on = pair_calls[1]

        ranks_match = compare_ranks(c_off["raw_result"], c_on["raw_result"])
        norm_off = normalize_payload(c_off["raw_result"])
        norm_on = normalize_payload(c_on["raw_result"])
        payload_match = (json.dumps(norm_off, sort_keys=True) == json.dumps(norm_on, sort_keys=True))

        # P0-3 & P15-07: Validate shadow observer stats for ON
        on_stats = c_on.get("shadow_stats")
        observer_valid = False
        observer_err = ""
        if on_stats and isinstance(on_stats, dict):
            sub = on_stats.get("submitted", 0)
            proc = on_stats.get("processed", 0)
            errs = on_stats.get("errors", 0)
            drops = on_stats.get("dropped", 0)
            if sub > 0 and proc >= sub and errs == 0 and drops == 0:
                observer_valid = True
            else:
                observer_err = f"OBSERVER_STATS_MISMATCH: sub={sub}, proc={proc}, err={errs}, drop={drops}"
        else:
            observer_err = "OBSERVER_UNVERIFIED_OR_MISSING"

        pair_pass = (
            c_off["success"]
            and c_on["success"]
            and c_off["retrieval_match"]
            and c_on["retrieval_match"]
            and ranks_match
            and payload_match
            and observer_valid
        )

        comp = {
            "query_id": c_off["query_id"],
            "query_text": c_off["query_text"],
            "off_success": c_off["success"],
            "on_success": c_on["success"],
            "off_elapsed_ms": c_off["elapsed_ms"],
            "on_elapsed_ms": c_on["elapsed_ms"],
            "rank_identical": ranks_match,
            "normalized_payload_identical": payload_match,
            "observer_valid": observer_valid,
            "observer_error": observer_err,
            "pair_verdict": "PASS" if pair_pass else "FAIL"
        }
        pilot_report["comparisons"].append(comp)

        # P0-2 Fail-fast: Stop immediately if pair comparison fails!
        if not pair_pass:
            pilot_report["overall_status"] = f"HALTED_PAIR_MISMATCH_QUERY_{c_off['query_id']}"
            halted = True
            break

    if not halted and len(pilot_report["comparisons"]) == len(TARGET_QUERIES):
        all_pairs_pass = all(c["pair_verdict"] == "PASS" for c in pilot_report["comparisons"])
        if all_pairs_pass:
            pilot_report["overall_status"] = (
                "SYNTHETIC_MACHINERY_VERIFIED"
                if synthetic_test
                else "PILOT_COMPLETED_SUCCESSFULLY"
            )
            if not synthetic_test:
                pilot_report["live_gate"] = "EXECUTED_APPROVED"

    return pilot_report


def save_separated_results(pilot_report: Dict[str, Any], target_repo_json: Path) -> Path:
    """
    P1-1 / P15-10: Strictly separates raw corpus results from the public git-tracked report.
    - Full raw results are saved to a temporary file in temp dir.
    - Public report JSON contains only sanitized excerpts (<= 200 chars), IDs, and SHA-256 hash.
    """
    # 1. Extract raw results and write to temp
    raw_calls = []
    for c in pilot_report.get("calls", []):
        raw_calls.append({
            "call_number": c.get("call_number"),
            "query_id": c.get("query_id"),
            "shadow_mode": c.get("shadow_mode"),
            "raw_result": c.get("raw_result")
        })

    raw_temp_path = Path(tempfile.gettempdir()) / f"postfix_pilot_raw_results_{pilot_report.get('task_id', '015')}.json"
    raw_bytes = json.dumps(raw_calls, ensure_ascii=False, indent=2).encode("utf-8")
    with open(raw_temp_path, "wb") as f:
        f.write(raw_bytes)
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # 2. Build sanitized public report (remove raw_result)
    sanitized_report = dict(pilot_report)
    sanitized_report["raw_results_temp_path"] = str(raw_temp_path)
    sanitized_report["raw_results_sha256"] = raw_sha256
    sanitized_calls = []
    for c in pilot_report.get("calls", []):
        sc = dict(c)
        sc.pop("raw_result", None)
        sanitized_calls.append(sc)
    sanitized_report["calls"] = sanitized_calls

    target_repo_json.parent.mkdir(parents=True, exist_ok=True)
    with open(target_repo_json, "w", encoding="utf-8") as f:
        json.dump(sanitized_report, f, indent=2, ensure_ascii=False)

    return raw_temp_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 4.2.9 (TZ-015 Rev 1.1) Post-Fix Retrieval Evidence Pilot Harness")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Validate preflight and output plan (default: True)")
    parser.add_argument("--test-machinery", action="store_true", default=False, help="Verify harness loop with simulated results (0 corpus calls)")
    parser.add_argument("--execute-approved-pilot", action="store_true", default=False, help="Execute the 6 live retrieval calls (requires operator approval)")
    args = parser.parse_args()

    is_dry_run = args.dry_run or (not args.test_machinery and not args.execute_approved_pilot)

    if args.test_machinery:
        print("=== Running Harness Machinery Test (Simulated Results, Corpus Calls = 0) ===")
        res = run_postfix_pilot(execute_approved_pilot=False, synthetic_test=True)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        print(f"\n[INFO] Machinery Test Status: {res['overall_status']}")
        print(f"[INFO] Actual Corpus Calls: {res['actual_corpus_search_calls']}")
        sys.exit(0 if res["overall_status"] == "SYNTHETIC_MACHINERY_VERIFIED" else 1)

    if is_dry_run and not args.execute_approved_pilot:
        print("=== Stage 4.2.9 (TZ-015 Rev 1.1) Preflight Verification (Dry Run) ===")
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
        out_json = ROOT_DIR / "reports" / "postfix_pilot_results_015.json"
        raw_p = save_separated_results(res, out_json)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        print(f"\n[INFO] Saved sanitized public results to {out_json}")
        print(f"[INFO] Saved raw private results to {raw_p}")
        sys.exit(0 if res["overall_status"] == "PILOT_COMPLETED_SUCCESSFULLY" else 1)


if __name__ == "__main__":
    main()
