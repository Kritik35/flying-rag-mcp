"""
tests/shadow_pilot_worker.py

Isolated child worker process for bounded search execution (Stage 4.2.8 Rev 3 / Block P3-B & P3-D).
Runs in an independent OS process to guarantee that process termination cleans up all worker state,
preventing rogue background threads from surviving a timeout or observing subsequent environment changes.
"""

from __future__ import annotations
import os
import sys
import json
import time
import argparse
import hashlib
import threading
from pathlib import Path
from typing import Any, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def is_error_payload(data: Any) -> Tuple[bool, str]:
    """
    Detects if a dispatch result represents an error rather than valid retrieval (Block C-error).
    Inspects top-level dicts and list-wrapped envelopes like blocked_result() [{'error': ..., 'status': 'blocked'}].
    """
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


def main():
    parser = argparse.ArgumentParser(description="Isolated shadow pilot search child worker")
    parser.add_argument("--query", type=str, required=True, help="Search query")
    parser.add_argument("--shadow-mode", type=str, default="0", help="Shadow mode: 1 (ON) or 0 (OFF)")
    parser.add_argument("--config-path", type=str, default=None, help="Path to isolated YAML config")
    parser.add_argument("--log-path", type=str, default=None, help="Path to isolated shadow EIG log")
    parser.add_argument("--control-file", type=str, default=None, help="Path to external control file")
    parser.add_argument("--delay-sec", type=float, default=0.0, help="Simulated execution delay in seconds")
    parser.add_argument("--observer-timeout", type=float, default=2.0, help="Observer drain timeout in seconds")
    parser.add_argument("--no-cache", action="store_true", help="Bypass exact/semantic retrieval cache for the authorized diagnostic search")
    parser.add_argument("--simulated-error", type=str, default=None, help="Simulated error message")
    parser.add_argument("--simulated-result", type=str, default=None, help="Simulated JSON result payload")

    args = parser.parse_args()

    # 1. P0-R3: Complete sanitization of host FLYING_RAG_* environment variables
    # Scrub ALL FLYING_RAG_* keys from os.environ upfront
    for k in list(os.environ.keys()):
        if k.startswith("FLYING_RAG_"):
            os.environ.pop(k, None)

    # Apply only explicit command-line arguments
    if args.config_path:
        os.environ["FLYING_RAG_CONFIG"] = str(Path(args.config_path).resolve())
    os.environ["FLYING_RAG_SHADOW_EIG"] = "1" if args.shadow_mode in ("1", "true", "yes", "on") else "0"
    if args.log_path:
        os.environ["FLYING_RAG_SHADOW_LOG_PATH"] = str(Path(args.log_path).resolve())
    if args.control_file:
        os.environ["FLYING_RAG_SHADOW_CONTROL_FILE"] = str(Path(args.control_file).resolve())

    # Ensure storage overrides can never leak into worker
    os.environ.pop("FLYING_RAG_METADATA_DB", None)
    os.environ.pop("FLYING_RAG_LANCEDB_PATH", None)
    os.environ.pop("FLYING_RAG_TABLE_PARQUET", None)

    t0 = time.perf_counter()
    env_seen = os.environ.get("FLYING_RAG_SHADOW_EIG", "0")

    # 2. Simulated delay (for testing deadline bounding and termination)
    if args.delay_sec > 0:
        time.sleep(args.delay_sec)

    # 3. Simulated error payload
    if args.simulated_error:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        payload = {
            "success": False,
            "result": {"error": args.simulated_error, "status": "FAILED"},
            "elapsed_ms": elapsed_ms,
            "error": args.simulated_error,
            "env_seen": env_seen,
            "shadow_stats": None
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(0)

    # 4. Simulated result payload
    if args.simulated_result:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        try:
            res_obj = json.loads(args.simulated_result)
        except Exception:
            res_obj = [{"chunk_id": "c_sim", "text": args.simulated_result}]
        
        is_err, err_detail = is_error_payload(res_obj)
        payload = {
            "success": not is_err,
            "result": res_obj,
            "elapsed_ms": elapsed_ms,
            "error": err_detail,
            "env_seen": env_seen,
            "shadow_stats": None
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(0)

    # 5. Real runtime dispatch
    try:
        from rag_server.server import _dispatch, reset_shadow_adapter
        from rag_server import tools as rag_tools
        from rag_server import norm_resolver as norm_module
        runtime_code_sha256 = {
            "rag_server_tools": hashlib.sha256(Path(rag_tools.__file__).read_bytes()).hexdigest(),
            "rag_server_norm_resolver": hashlib.sha256(Path(norm_module.__file__).read_bytes()).hexdigest(),
        }
        if args.shadow_mode not in ("1", "true", "yes", "on"):
            reset_shadow_adapter()

        res = _dispatch("search_documents", {"query": args.query, "debug": False, "use_cache": not args.no_cache})
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        # Check for error payload (including list-wrapped blocked_result)
        is_err, err_msg = is_error_payload(res)

        # In shadow mode ON: wait bounded time for background observation task to complete
        adapter = None
        if args.shadow_mode in ("1", "true", "yes", "on"):
            try:
                from rag_server.server import _get_shadow_adapter
                adapter = _get_shadow_adapter()
                if adapter and args.observer_timeout > 0:
                    t0_obs = time.perf_counter()
                    while time.perf_counter() - t0_obs < args.observer_timeout:
                        with getattr(adapter, "_lock", threading.Lock()):
                            proc = getattr(adapter, "processed_count", 0)
                            active = len([f for f in getattr(adapter, "_active_futures", set()) if not f.done()])
                        if proc > 0 and active == 0:
                            break
                        time.sleep(0.01)
            except Exception:
                pass

        shadow_stats = None
        if adapter:
            with getattr(adapter, "_lock", threading.Lock()):
                shadow_stats = {
                    "submitted": getattr(adapter, "submitted_count", 0),
                    "processed": getattr(adapter, "processed_count", 0),
                    "errors": getattr(adapter, "error_count", 0),
                    "dropped": getattr(adapter, "drop_count", 0)
                }

        payload = {
            "success": not is_err,
            "result": res,
            "elapsed_ms": elapsed_ms,
            "error": err_msg,
            "env_seen": env_seen,
            "shadow_stats": shadow_stats,
            "cache_disabled": bool(args.no_cache),
            "runtime_code_sha256": runtime_code_sha256
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(0)
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        payload = {
            "success": False,
            "result": None,
            "elapsed_ms": elapsed_ms,
            "error": f"{type(e).__name__}: {e}",
            "env_seen": env_seen,
            "shadow_stats": None
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
