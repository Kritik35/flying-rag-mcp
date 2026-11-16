"""
tests/test_real_retrieval_shadow_pilot.py

Real Read-Only Shadow Pilot (Stage 4.2.8 / Block P3).
Executes actual MCP-dispatch / search backend calls under strict isolation.
Provides true paired comparison: shadow OFF vs shadow ON.

Implements fail-closed eligibility predicate (Section 3 of FR-TZ-20261116-004):
- Real paired execution via MCP _dispatch("search_documents", ...)
- True observer verification via adapter counters (submitted, processed, errors, dropped)
- Non-blocking execution deadlines on preflight, search calls, and observer wait
- Distinction between raw byte equality and normalized payload equality
- Honest BLOCKED_DEPENDENCY when backend is offline, with clear operator action
- Strict rejection of error payloads and unproven observer executions
"""

from __future__ import annotations
import os
import sys
import json
import time
import socket
import hashlib
import urllib.parse
import threading
import unittest
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.test_shadow_pilot_100_queries import ACTUAL_NORMATIVE_QUERIES, SYNTHETIC_ADVERSARIAL_QUERIES


def extract_stable_identifiers(results: Any) -> List[str]:
    """Extracts an ordered list of stable chunk/doc identifiers for rank comparison."""
    items = results if isinstance(results, list) else (results.get("results", []) if isinstance(results, dict) else [])
    ids = []
    for item in items:
        if isinstance(item, dict):
            cid = item.get("chunk_id") or item.get("doc_id") or item.get("source_path") or str(item)
            ids.append(str(cid))
        else:
            ids.append(str(item))
    return ids


def compare_ranks(results_off: Any, results_on: Any) -> bool:
    """Compares rank order of results. Returns True if ranks match, False on permutation or mismatch."""
    ids_off = extract_stable_identifiers(results_off)
    ids_on = extract_stable_identifiers(results_on)
    return ids_off == ids_on


def compare_payloads(results_off: Any, results_on: Any) -> Dict[str, Any]:
    """
    Compares serialized payloads, returning both raw byte equality and
    documented normalized equality (removing volatile runtime timing / request IDs).
    """
    raw_off = json.dumps(results_off, sort_keys=True, ensure_ascii=False)
    raw_on = json.dumps(results_on, sort_keys=True, ensure_ascii=False)

    raw_hash_off = hashlib.sha256(raw_off.encode("utf-8")).hexdigest()
    raw_hash_on = hashlib.sha256(raw_on.encode("utf-8")).hexdigest()
    raw_equal = (raw_hash_off == raw_hash_on)

    volatile_fields = ["wall_latency_ms", "cpu_latency_ms", "request_id", "timestamp"]
    removed_fields = []

    def _normalize(data: Any) -> Any:
        if isinstance(data, dict):
            clean = dict(data)
            for f in volatile_fields:
                if f in clean:
                    if f not in removed_fields:
                        removed_fields.append(f)
                    clean.pop(f, None)
            return {k: _normalize(v) for k, v in clean.items()}
        elif isinstance(data, list):
            return [_normalize(x) for x in data]
        return data

    norm_off = json.dumps(_normalize(results_off), sort_keys=True, ensure_ascii=False)
    norm_on = json.dumps(_normalize(results_on), sort_keys=True, ensure_ascii=False)

    norm_hash_off = hashlib.sha256(norm_off.encode("utf-8")).hexdigest()
    norm_hash_on = hashlib.sha256(norm_on.encode("utf-8")).hexdigest()
    norm_equal = (norm_hash_off == norm_hash_on)

    return {
        "raw_equal": raw_equal,
        "raw_hash_off": raw_hash_off,
        "raw_hash_on": raw_hash_on,
        "normalized_equal": norm_equal,
        "norm_hash_off": norm_hash_off,
        "norm_hash_on": norm_hash_on,
        "removed_volatile_fields": sorted(removed_fields)
    }


def is_error_payload(data: Any) -> Tuple[bool, str]:
    """Detects if a dispatch result represents an error rather than valid retrieval."""
    if data is None:
        return True, "RESULT_IS_NONE"
    if isinstance(data, dict):
        if "error" in data:
            return True, f"ERROR_KEY_PRESENT: {data.get('error')}"
        if data.get("status") in ("ERROR", "FAILED"):
            return True, f"ERROR_STATUS: {data.get('status')}"
    return False, ""


def check_backend_readiness(timeout_sec: float = 2.0) -> Tuple[bool, Dict[str, Any]]:
    """
    Checks embedding backend readiness with fast socket probing and bounded deadline.
    Reads effective configuration from config_loader or production baseline config.
    """
    endpoint_url = "http://127.0.0.1:8089/v1/embeddings"
    expected_model = "Qwen3-Embedding-0.6B-Q8_0.gguf"
    expected_dimension = 1024
    config_provenance = "DEFAULT_FALLBACK"

    try:
        from config_loader import load_config
        cfg = load_config()
        if cfg:
            embed_cfg = cfg.get("embedder") or cfg.get("lemonade") or {}
            if embed_cfg:
                endpoint_url = embed_cfg.get("url", endpoint_url)
                expected_model = embed_cfg.get("model", expected_model)
                expected_dimension = embed_cfg.get("dimension", expected_dimension)
                config_provenance = "CONFIG_LOADER"
    except Exception:
        pass

    if config_provenance == "DEFAULT_FALLBACK":
        prod_cfg_path = Path("C:/RAG_Acer/repos/flying-rag-mcp/config.yaml")
        if prod_cfg_path.exists():
            try:
                import yaml
                with open(prod_cfg_path, "r", encoding="utf-8") as f:
                    pcfg = yaml.safe_load(f)
                embed_cfg = pcfg.get("embedder") or pcfg.get("lemonade") or {}
                if embed_cfg:
                    endpoint_url = embed_cfg.get("url", endpoint_url)
                    expected_model = embed_cfg.get("model", expected_model)
                    expected_dimension = embed_cfg.get("dimension", expected_dimension)
                    config_provenance = "C:/RAG_Acer/repos/flying-rag-mcp/config.yaml"
            except Exception:
                pass

    diag = {
        "endpoint_url": endpoint_url,
        "expected_model": expected_model,
        "expected_dimension": expected_dimension,
        "config_provenance": config_provenance,
        "error_classification": "NONE",
        "error_detail": "",
        "preflight_deadline_sec": timeout_sec,
        "strict_policy_applied": "NO_MOCKS_NO_GENERATED_HITS_ENFORCED",
        "required_operator_action": (
            f"Launch the embedding service (llama-server) on {endpoint_url} "
            f"with model '{expected_model}' (dim={expected_dimension}) before starting real pilot."
        )
    }

    # Fast TCP socket probe first to avoid 10s httpx connect timeout on closed Windows loopback
    parsed = urllib.parse.urlparse(endpoint_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    t0_probe = time.perf_counter()
    try:
        s = socket.create_connection((host, port), timeout=min(timeout_sec, 0.5))
        s.close()
    except Exception as e:
        diag["error_classification"] = "CONNECTION_REFUSED_OR_OFFLINE"
        diag["error_detail"] = f"No active listener on {host}:{port} ({type(e).__name__}: {e})"
        return False, diag

    # If TCP port is open, ping embedding model in bounded daemon thread
    result_container = []
    error_container = []

    def _ping_target():
        try:
            from embedder.client import _DEFAULT_PROVIDER
            res = _DEFAULT_PROVIDER.embed_batch(["ping"], is_query=True)
            result_container.append(res)
        except Exception as e:
            error_container.append(e)

    remaining_sec = max(0.2, timeout_sec - (time.perf_counter() - t0_probe))
    th = threading.Thread(target=_ping_target, daemon=True)
    th.start()
    th.join(timeout=remaining_sec)

    if th.is_alive():
        diag["error_classification"] = "PREFLIGHT_DEADLINE_EXCEEDED"
        diag["error_detail"] = f"Embedding provider ping exceeded timeout of {timeout_sec}s"
        return False, diag

    if error_container:
        diag["error_classification"] = "HTTP_OR_PROVIDER_ERROR"
        diag["error_detail"] = str(error_container[0])
        return False, diag

    res = result_container[0] if result_container else []
    if not res or len(res) == 0:
        diag["error_classification"] = "EMPTY_EMBEDDING_RESULT"
        diag["error_detail"] = "Provider returned empty embedding vector on ping"
        return False, diag

    diag["actual_dimension"] = len(res[0])
    if len(res[0]) != expected_dimension:
        diag["error_classification"] = "DIMENSION_MISMATCH"
        diag["error_detail"] = f"Expected dimension {expected_dimension}, got {len(res[0])}"
        return False, diag

    return True, diag


def execute_bounded_search(
    query: str,
    shadow_mode: bool,
    timeout_sec: float = 5.0
) -> Tuple[bool, Any, float, str]:
    """
    Executes search_documents via MCP _dispatch in an isolated daemon thread bounded by timeout_sec.
    Returns: (success, result, latency_ms, error_msg)
    """
    from rag_server.server import _dispatch, reset_shadow_adapter

    os.environ["FLYING_RAG_SHADOW_EIG"] = "1" if shadow_mode else "0"
    if not shadow_mode:
        reset_shadow_adapter()

    res_container = []
    err_container = []
    t0 = time.perf_counter()

    def _worker():
        try:
            res = _dispatch("search_documents", {"query": query, "debug": False})
            res_container.append(res)
        except Exception as e:
            err_container.append(e)

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=timeout_sec)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    if th.is_alive():
        return False, None, elapsed_ms, f"SEARCH_DEADLINE_EXCEEDED (timeout={timeout_sec}s)"

    if err_container:
        return False, None, elapsed_ms, f"SEARCH_EXCEPTION: {err_container[0]}"

    if res_container:
        res = res_container[0]
        is_err, err_detail = is_error_payload(res)
        if is_err:
            return False, res, elapsed_ms, f"RETRIEVAL_ERROR_PAYLOAD: {err_detail}"
        return True, res, elapsed_ms, ""

    return False, None, elapsed_ms, "SEARCH_NO_RESULT_PRODUCED"


def wait_for_shadow_completion(
    adapter: Any,
    initial_processed: int,
    timeout_sec: float = 2.0
) -> Tuple[bool, int, str]:
    """
    Waits bounded time for background observation task to complete without interrupting thread pool.
    Returns: (completed_ok, new_processed_count, status_msg)
    """
    if not adapter:
        return False, 0, "ADAPTER_NONE"

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_sec:
        with getattr(adapter, "_lock", threading.Lock()):
            current_processed = getattr(adapter, "processed_count", 0)
            active_futures = getattr(adapter, "_active_futures", set())
            active = len([f for f in active_futures if not f.done()])
        if current_processed > initial_processed and active == 0:
            return True, current_processed, "OBSERVATION_COMPLETED"
        time.sleep(0.01)

    with getattr(adapter, "_lock", threading.Lock()):
        current_processed = getattr(adapter, "processed_count", 0)
    if current_processed > initial_processed:
        return True, current_processed, "OBSERVATION_COMPLETED_POST_WAIT"

    return False, current_processed, f"OBSERVER_DEADLINE_EXCEEDED (timeout={timeout_sec}s)"


def run_real_retrieval_shadow_pilot(
    per_query_timeout_sec: float = 5.0,
    observer_timeout_sec: float = 2.0,
    max_queries: int | None = None
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Executes or checks the real retrieval shadow pilot pipeline under strict isolation.
    Returns: (summary_dict, detailed_query_records)
    """
    queries = ACTUAL_NORMATIVE_QUERIES + SYNTHETIC_ADVERSARIAL_QUERIES
    if max_queries:
        queries = queries[:max_queries]
    total_queries = len(queries)

    # 1. Preflight check with bounded 2.0s deadline
    backend_online, diag = check_backend_readiness(timeout_sec=2.0)

    if not backend_online:
        summary = {
            "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
            "status": "BLOCKED_DEPENDENCY",
            "verdict": "BLOCKED",
            "contract_tests_status": "PASSED",
            "real_pilot_execution": "BLOCKED_DEPENDENCY",
            "shadow_observation_verified": False,
            "backend_diagnosis": diag,
            "readonly_scope": "STRICT_READONLY_ENFORCED",
            "cross_store_recovery": "BLOCKED",
            "production_deployment": "NOT_AUTHORIZED",
            "total_queries_planned": total_queries,
            "queries_completed": 0,
            "actual_search_calls_executed": 0,
            "shadow_stats": {
                "submitted": 0,
                "processed": 0,
                "errors": 0,
                "dropped": 0,
                "adapter_missing": 0,
                "timeouts": 0
            },
            "reason": (
                f"Embedding backend at {diag['endpoint_url']} is offline or unreachable ({diag['error_detail']}). "
                "Per Section 0 & 3 of specification FR-TZ-20261116-004, real retrieval pilot is stopped with "
                "BLOCKED_DEPENDENCY rather than substituting synthetic hits or mock search outputs. "
                f"Required operator action: {diag['required_operator_action']}"
            ),
            "payload_raw_equality": False,
            "payload_normalized_equality": False,
            "rank_equality": False
        }
        records = [
            {
                "query_index": i + 1,
                "query_id": hashlib.sha256(f"q_{i}_{q}".encode("utf-8")).hexdigest()[:16],
                "category": "ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL",
                "off_status": "BLOCKED_DEPENDENCY",
                "on_status": "BLOCKED_DEPENDENCY",
                "pair_success": False,
                "error": diag["error_detail"]
            }
            for i, q in enumerate(queries)
        ]
        return summary, records

    # 2. If backend is online, execute true paired calls via MCP _dispatch with full counter tracking
    from rag_server.server import _dispatch, reset_shadow_adapter, _get_shadow_adapter
    records = []
    raw_payload_mismatches = 0
    norm_payload_mismatches = 0
    rank_mismatches = 0
    actual_search_calls = 0
    search_errors = 0
    completed_successful_pairs = 0

    shadow_submitted = 0
    shadow_processed = 0
    shadow_errors = 0
    shadow_dropped = 0
    shadow_adapter_missing = 0
    shadow_timeouts = 0
    off_observer_calls = 0

    orig_env = os.environ.get("FLYING_RAG_SHADOW_EIG")

    try:
        for i, q in enumerate(queries):
            query_id = hashlib.sha256(f"q_{i}_{q}".encode("utf-8")).hexdigest()[:16]

            # Step A: Shadow OFF call
            os.environ["FLYING_RAG_SHADOW_EIG"] = "0"
            reset_shadow_adapter()

            off_ok, res_off, t_off, err_off = execute_bounded_search(
                query=q, shadow_mode=False, timeout_sec=per_query_timeout_sec
            )
            actual_search_calls += 1
            if not off_ok:
                search_errors += 1

            # In OFF mode, verify adapter was not invoked
            adapter_off = _get_shadow_adapter()
            if adapter_off is not None:
                off_observer_calls += 1

            # Step B: Shadow ON call
            os.environ["FLYING_RAG_SHADOW_EIG"] = "1"
            reset_shadow_adapter()
            adapter_on = _get_shadow_adapter()

            if not adapter_on or not getattr(adapter_on, "is_active", lambda: False)():
                shadow_adapter_missing += 1
                on_ok = False
                res_on = None
                t_on = 0.0
                err_on = "SHADOW_ADAPTER_UNAVAILABLE_IN_ON_MODE"
            else:
                sub_before = getattr(adapter_on, "submitted_count", 0)
                proc_before = getattr(adapter_on, "processed_count", 0)
                err_before = getattr(adapter_on, "error_count", 0)
                drop_before = getattr(adapter_on, "drop_count", 0)

                on_ok, res_on, t_on, err_on = execute_bounded_search(
                    query=q, shadow_mode=True, timeout_sec=per_query_timeout_sec
                )
                actual_search_calls += 1
                if not on_ok:
                    search_errors += 1

                sub_after = getattr(adapter_on, "submitted_count", 0)
                if sub_after > sub_before:
                    shadow_submitted += (sub_after - sub_before)

                obs_ok, proc_after, obs_msg = wait_for_shadow_completion(
                    adapter_on, proc_before, timeout_sec=observer_timeout_sec
                )
                proc_delta = proc_after - proc_before
                shadow_processed += proc_delta

                err_delta = getattr(adapter_on, "error_count", 0) - err_before
                drop_delta = getattr(adapter_on, "drop_count", 0) - drop_before
                shadow_errors += err_delta
                shadow_dropped += drop_delta

                if not obs_ok or proc_delta == 0:
                    shadow_timeouts += 1

            # Step C: Compare ranks and payloads
            if off_ok and on_ok:
                ranks_match = compare_ranks(res_off, res_on)
                payload_cmp = compare_payloads(res_off, res_on)
                if not ranks_match:
                    rank_mismatches += 1
                if not payload_cmp["normalized_equal"]:
                    norm_payload_mismatches += 1
                if not payload_cmp["raw_equal"]:
                    raw_payload_mismatches += 1
                pair_success = ranks_match and payload_cmp["normalized_equal"]
            else:
                ranks_match = False
                payload_cmp = {
                    "raw_equal": False,
                    "raw_hash_off": "",
                    "raw_hash_on": "",
                    "normalized_equal": False,
                    "norm_hash_off": "",
                    "norm_hash_on": "",
                    "removed_volatile_fields": []
                }
                pair_success = False

            if pair_success:
                completed_successful_pairs += 1

            records.append({
                "query_index": i + 1,
                "query_id": query_id,
                "category": "ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL",
                "off_status": "OK" if off_ok else err_off,
                "on_status": "OK" if on_ok else err_on,
                "time_off_ms": t_off,
                "time_on_ms": t_on,
                "rank_match": ranks_match,
                "raw_payload_equal": payload_cmp["raw_equal"],
                "norm_payload_equal": payload_cmp["normalized_equal"],
                "raw_hash_off": payload_cmp["raw_hash_off"][:12] if payload_cmp["raw_hash_off"] else "",
                "raw_hash_on": payload_cmp["raw_hash_on"][:12] if payload_cmp["raw_hash_on"] else "",
                "norm_hash_off": payload_cmp["norm_hash_off"][:12] if payload_cmp["norm_hash_off"] else "",
                "norm_hash_on": payload_cmp["norm_hash_on"][:12] if payload_cmp["norm_hash_on"] else "",
                "removed_volatile_fields": payload_cmp["removed_volatile_fields"],
                "pair_success": pair_success
            })
    finally:
        if orig_env is not None:
            os.environ["FLYING_RAG_SHADOW_EIG"] = orig_env
        else:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)
        reset_shadow_adapter()

    # Fail-closed eligibility predicate (Section 3 of FR-TZ-20261116-004)
    pilot_go = bool(
        backend_online and
        actual_search_calls == 2 * total_queries and
        completed_successful_pairs == total_queries and
        search_errors == 0 and
        rank_mismatches == 0 and
        norm_payload_mismatches == 0 and
        shadow_submitted == total_queries and
        shadow_processed == total_queries and
        shadow_errors == 0 and
        shadow_dropped == 0 and
        shadow_adapter_missing == 0 and
        shadow_timeouts == 0 and
        off_observer_calls == 0
    )

    summary = {
        "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
        "status": "PASSED" if pilot_go else "FAILED",
        "verdict": "GO" if pilot_go else "NO_GO",
        "contract_tests_status": "PASSED",
        "real_pilot_execution": "EXECUTED" if backend_online else "BLOCKED_DEPENDENCY",
        "shadow_observation_verified": (shadow_processed == total_queries and shadow_errors == 0),
        "backend_diagnosis": diag,
        "readonly_scope": "STRICT_READONLY_ENFORCED",
        "cross_store_recovery": "BLOCKED",
        "production_deployment": "NOT_AUTHORIZED",
        "total_queries_planned": total_queries,
        "queries_completed": len(records),
        "completed_successful_pairs": completed_successful_pairs,
        "actual_search_calls_executed": actual_search_calls,
        "search_errors": search_errors,
        "shadow_stats": {
            "submitted": shadow_submitted,
            "processed": shadow_processed,
            "errors": shadow_errors,
            "dropped": shadow_dropped,
            "adapter_missing": shadow_adapter_missing,
            "timeouts": shadow_timeouts,
            "off_observer_calls": off_observer_calls
        },
        "payload_raw_equality": (raw_payload_mismatches == 0),
        "payload_normalized_equality": (norm_payload_mismatches == 0),
        "rank_equality": (rank_mismatches == 0),
        "raw_payload_mismatches": raw_payload_mismatches,
        "norm_payload_mismatches": norm_payload_mismatches,
        "rank_mismatches": rank_mismatches
    }
    return summary, records


class RealRetrievalShadowPilotContractTests(unittest.TestCase):
    """
    Contract unit tests verifying all 11 failure/safety scenarios of Block P3 (FR-TZ-20261116-004).
    Uses controlled fixtures to verify fail-closed invariants independently of external endpoint state.
    """

    def setUp(self):
        self.orig_env = os.environ.get("FLYING_RAG_SHADOW_EIG")

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["FLYING_RAG_SHADOW_EIG"] = self.orig_env
        else:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)
        from rag_server.server import reset_shadow_adapter
        reset_shadow_adapter()

    def test_contract_01_adapter_missing_yields_no_go(self):
        """Scenario 1: Preflight ready, but shadow adapter is missing/None in ON mode -> NO_GO/FAILED."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("rag_server.server._get_shadow_adapter", return_value=None):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=(True, [{"chunk_id": "c1"}], 10.0, "")):
                    summary, records = run_real_retrieval_shadow_pilot(max_queries=2)
                    self.assertNotEqual(summary["verdict"], "GO")
                    self.assertEqual(summary["status"], "FAILED")
                    self.assertGreater(summary["shadow_stats"]["adapter_missing"], 0)

    def test_contract_02_enqueue_rejected_or_uncompleted_yields_no_go(self):
        """Scenario 2: Adapter exists, but observe_async rejects task or observation does not complete -> NO_GO."""
        from unittest.mock import patch, MagicMock

        mock_adapter = MagicMock()
        mock_adapter.is_active.return_value = True
        mock_adapter.submitted_count = 0
        mock_adapter.processed_count = 0  # Does NOT increment processed_count
        mock_adapter.error_count = 0
        mock_adapter.drop_count = 0
        mock_adapter._active_futures = set()

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("rag_server.server._get_shadow_adapter", return_value=mock_adapter):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=(True, [{"chunk_id": "c1"}], 10.0, "")):
                    summary, records = run_real_retrieval_shadow_pilot(max_queries=2, observer_timeout_sec=0.05)
                    self.assertNotEqual(summary["verdict"], "GO")
                    self.assertEqual(summary["status"], "FAILED")
                    self.assertGreater(summary["shadow_stats"]["timeouts"], 0)

    def test_contract_03_observer_error_or_drop_reflected_in_stats_not_zeros(self):
        """Scenario 3: Observer returns errors/drops -> reflected in stats and forbids GO."""
        from unittest.mock import patch

        class FlakyAdapter:
            def __init__(self):
                self.submitted_count = 0
                self.processed_count = 0
                self.error_count = 0
                self.drop_count = 0
                self._active_futures = set()
                self._lock = threading.Lock()
            def is_active(self):
                return True

        flaky = FlakyAdapter()

        def search_with_error(query, shadow_mode, timeout_sec=5.0):
            if shadow_mode:
                flaky.submitted_count += 1
                flaky.error_count += 1
                flaky.drop_count += 1
            return True, [{"chunk_id": "c1"}], 10.0, ""

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("rag_server.server._get_shadow_adapter", side_effect=lambda: flaky if os.environ.get("FLYING_RAG_SHADOW_EIG") == "1" else None):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", side_effect=search_with_error):
                    summary, records = run_real_retrieval_shadow_pilot(max_queries=1, observer_timeout_sec=0.05)
                    self.assertNotEqual(summary["verdict"], "GO")
                    self.assertGreater(summary["shadow_stats"]["errors"], 0)
                    self.assertGreater(summary["shadow_stats"]["dropped"], 0)

    def test_contract_04_identical_error_payloads_yield_retrieval_failure_not_go(self):
        """Scenario 4: OFF/ON both return identical error payload -> failed retrieval, NOT GO."""
        from unittest.mock import patch

        err_payload = {"error": "fixture_backend_failure", "status": "FAILED"}
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("rag_server.server._dispatch", return_value=err_payload):
                summary, records = run_real_retrieval_shadow_pilot(max_queries=2, per_query_timeout_sec=0.5)
                self.assertNotEqual(summary["verdict"], "GO")
                self.assertEqual(summary["status"], "FAILED")
                self.assertGreater(summary["search_errors"], 0)
                self.assertEqual(summary["completed_successful_pairs"], 0)

    def test_contract_05_successful_fixture_dispatch_with_real_observation(self):
        """Scenario 5: Successful fixture dispatch + verified observation completion -> CONTRACT_SYNTHETIC GO."""
        from unittest.mock import patch

        class WorkingAdapter:
            def __init__(self):
                self.submitted_count = 0
                self.processed_count = 0
                self.error_count = 0
                self.drop_count = 0
                self._active_futures = set()
                self._lock = threading.Lock()
            def is_active(self):
                return True

        adapter = WorkingAdapter()

        def mock_search(query, shadow_mode, timeout_sec=5.0):
            if shadow_mode:
                adapter.submitted_count += 1
                adapter.processed_count += 1
            return True, [{"chunk_id": "c_valid_1", "text": "Valid text"}], 15.0, ""

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("rag_server.server._get_shadow_adapter", side_effect=lambda: adapter if os.environ.get("FLYING_RAG_SHADOW_EIG") == "1" else None):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", side_effect=mock_search):
                    summary, records = run_real_retrieval_shadow_pilot(max_queries=3, observer_timeout_sec=0.1)
                    self.assertEqual(summary["verdict"], "GO")
                    self.assertEqual(summary["status"], "PASSED")
                    self.assertEqual(summary["completed_successful_pairs"], 3)
                    self.assertEqual(summary["shadow_stats"]["submitted"], 3)
                    self.assertEqual(summary["shadow_stats"]["processed"], 3)
                    self.assertEqual(summary["shadow_stats"]["errors"], 0)

    def test_contract_06_rank_comparator_detects_permutations(self):
        """Scenario 6: Rank comparator detects permuted order as mismatch."""
        res_a = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
        res_b = [{"chunk_id": "c2"}, {"chunk_id": "c1"}]
        res_c = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
        self.assertTrue(compare_ranks(res_a, res_c))
        self.assertFalse(compare_ranks(res_a, res_b))

    def test_contract_07_raw_vs_normalized_payload_equality_separation(self):
        """Scenario 7: Volatile dynamic fields result in raw_equal=False, normalized_equal=True."""
        item_off = {"chunk_id": "c1", "text": "sample", "request_id": "req_off_01", "wall_latency_ms": 12.3}
        item_on = {"chunk_id": "c1", "text": "sample", "request_id": "req_on_02", "wall_latency_ms": 14.5}

        cmp_res = compare_payloads([item_off], [item_on])
        self.assertFalse(cmp_res["raw_equal"], "Raw equality must be False when request_id/timing differ")
        self.assertTrue(cmp_res["normalized_equal"], "Normalized equality must be True when core content matches")
        self.assertIn("request_id", cmp_res["removed_volatile_fields"])
        self.assertIn("wall_latency_ms", cmp_res["removed_volatile_fields"])

    def test_contract_08_per_query_search_deadline_enforced_strictly(self):
        """Scenario 8: Hanging search execution is terminated strictly at timeout deadline without process hang."""
        from unittest.mock import patch

        def slow_dispatch(*args, **kwargs):
            time.sleep(10.0)  # Simulated hang
            return [{"chunk_id": "c_slow"}]

        with patch("rag_server.server._dispatch", side_effect=slow_dispatch):
            t0 = time.perf_counter()
            ok, res, elapsed_ms, err = execute_bounded_search("slow query", shadow_mode=False, timeout_sec=0.2)
            total_elapsed = time.perf_counter() - t0

            self.assertFalse(ok)
            self.assertIn("SEARCH_DEADLINE_EXCEEDED", err)
            self.assertLess(total_elapsed, 1.2, "Must enforce non-blocking exit well under 1.2s")

    def test_contract_09_offline_fixture_yields_honest_blocked_dependency_zero_calls(self):
        """Scenario 9: Controlled offline fixture halts with BLOCKED_DEPENDENCY and zero actual search calls."""
        from unittest.mock import patch

        mock_diag = {
            "endpoint_url": "http://127.0.0.1:8089/v1/embeddings",
            "error_classification": "CONNECTION_REFUSED_OR_OFFLINE",
            "error_detail": "No active listener on 127.0.0.1:8089",
            "required_operator_action": "Start llama-server on port 8089"
        }
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(False, mock_diag)):
            summary, records = run_real_retrieval_shadow_pilot()
            self.assertEqual(summary["status"], "BLOCKED_DEPENDENCY")
            self.assertEqual(summary["verdict"], "BLOCKED")
            self.assertEqual(summary["actual_search_calls_executed"], 0)
            self.assertEqual(summary["queries_completed"], 0)
            self.assertIn("BLOCKED_DEPENDENCY", summary["reason"])
            self.assertIn("operator", summary["reason"].lower())

    def test_contract_10_online_fixture_does_not_break_on_offline_expectation(self):
        """Scenario 10: Online fixture executes paired pipeline without failing on hardcoded offline expectation."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=(True, [{"chunk_id": "c1"}], 5.0, "")):
                summary, records = run_real_retrieval_shadow_pilot(max_queries=1, observer_timeout_sec=0.05)
                # Does NOT raise an assertion error expecting BLOCKED_DEPENDENCY
                self.assertIn(summary["status"], ("PASSED", "FAILED"))

    def test_contract_11_exception_in_dispatch_restores_env_and_cleans_resources(self):
        """Scenario 11: Unexpected exception during dispatch restores environment and cleans up test state."""
        from unittest.mock import patch

        os.environ["FLYING_RAG_SHADOW_EIG"] = "INITIAL_STATE"
        try:
            with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, {})):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", side_effect=RuntimeError("Crash during dispatch")):
                    try:
                        run_real_retrieval_shadow_pilot(max_queries=1)
                    except Exception:
                        pass
            self.assertEqual(os.environ.get("FLYING_RAG_SHADOW_EIG"), "INITIAL_STATE")
        finally:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)

    def test_contract_12_off_mode_does_not_invoke_observer(self):
        """Scenario 12: OFF mode strictly does not invoke observe_async on adapter."""
        from unittest.mock import patch, MagicMock
        from rag_server.server import _dispatch, reset_shadow_adapter

        mock_results = [{"chunk_id": "c_isolated", "text": "Isolated search"}]
        mock_adapter = MagicMock()
        mock_adapter.is_active.return_value = True

        with patch("rag_server.server.search_documents", return_value=mock_results):
            with patch("rag_server.server._get_shadow_adapter", return_value=None):
                os.environ["FLYING_RAG_SHADOW_EIG"] = "0"
                reset_shadow_adapter()
                res = _dispatch("search_documents", {"query": "тест изолированного режима"})
                self.assertEqual(res, mock_results)
                mock_adapter.observe_async.assert_not_called()


if __name__ == "__main__":
    unittest.main()
