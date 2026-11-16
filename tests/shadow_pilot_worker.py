"""
tests/shadow_pilot_worker.py

Isolated child worker process for bounded search execution (Stage 4.2.8 Rev 2 / Block P3-B & P3-D).
Runs in an independent OS process to guarantee that process termination cleans up all worker state,
preventing rogue background threads from surviving a timeout or observing subsequent environment changes.
"""

from __future__ import annotations
import os
import sys
import json
import time
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main():
    parser = argparse.ArgumentParser(description="Isolated shadow pilot search child worker")
    parser.add_argument("--query", type=str, required=True, help="Search query")
    parser.add_argument("--shadow-mode", type=str, default="0", help="Shadow mode: 1 (ON) or 0 (OFF)")
    parser.add_argument("--config-path", type=str, default=None, help="Path to isolated YAML config")
    parser.add_argument("--log-path", type=str, default=None, help="Path to isolated shadow EIG log")
    parser.add_argument("--control-file", type=str, default=None, help="Path to external control file")
    parser.add_argument("--delay-sec", type=float, default=0.0, help="Simulated execution delay in seconds")
    parser.add_argument("--simulated-error", type=str, default=None, help="Simulated error message")
    parser.add_argument("--simulated-result", type=str, default=None, help="Simulated JSON result payload")

    args = parser.parse_args()

    # 1. Apply environment variables before importing runtime modules
    if args.config_path:
        os.environ["FLYING_RAG_CONFIG"] = str(args.config_path)
    os.environ["FLYING_RAG_SHADOW_EIG"] = "1" if args.shadow_mode in ("1", "true", "yes", "on") else "0"
    if args.log_path:
        os.environ["FLYING_RAG_SHADOW_LOG_PATH"] = str(args.log_path)
    if args.control_file:
        os.environ["FLYING_RAG_SHADOW_CONTROL_FILE"] = str(args.control_file)

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
            "env_seen": env_seen
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
        payload = {
            "success": True,
            "result": res_obj,
            "elapsed_ms": elapsed_ms,
            "error": "",
            "env_seen": env_seen
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(0)

    # 5. Real runtime dispatch
    try:
        from rag_server.server import _dispatch, reset_shadow_adapter
        if args.shadow_mode not in ("1", "true", "yes", "on"):
            reset_shadow_adapter()

        res = _dispatch("search_documents", {"query": args.query, "debug": False})
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        # Check for error payload
        is_err = False
        err_msg = ""
        if isinstance(res, dict) and ("error" in res or res.get("status") in ("ERROR", "FAILED")):
            is_err = True
            err_msg = str(res.get("error") or res.get("status"))

        payload = {
            "success": not is_err,
            "result": res,
            "elapsed_ms": elapsed_ms,
            "error": err_msg,
            "env_seen": env_seen
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
            "env_seen": env_seen
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
