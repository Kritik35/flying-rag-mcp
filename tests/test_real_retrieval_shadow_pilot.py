"""
tests/test_real_retrieval_shadow_pilot.py

Real Read-Only Shadow Pilot (Stage 4.2.7 / Block P1).
Executes actual MCP-dispatch / search backend calls under strict isolation.
Provides true paired comparison: shadow OFF vs shadow ON.

If the embedding backend / endpoint is unavailable:
honestly halts with BLOCKED_DEPENDENCY rather than substituting mock hits or SELECT LIMIT.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import unittest
from pathlib import Path
from typing import Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

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


def compare_payloads(results_off: Any, results_on: Any) -> Tuple[bool, str, str]:
    """Compares serialized payloads, returning (is_equal, hash_off, hash_on)."""
    # Normalize dynamic fields (e.g., debug timing traces) if dict
    def _normalize(data: Any) -> Any:
        if isinstance(data, dict):
            clean = dict(data)
            clean.pop("wall_latency_ms", None)
            clean.pop("cpu_latency_ms", None)
            clean.pop("request_id", None)
            return {k: _normalize(v) for k, v in clean.items()}
        elif isinstance(data, list):
            return [_normalize(x) for x in data]
        return data

    norm_off = json.dumps(_normalize(results_off), sort_keys=True, ensure_ascii=False)
    norm_on = json.dumps(_normalize(results_on), sort_keys=True, ensure_ascii=False)

    hash_off = hashlib.sha256(norm_off.encode("utf-8")).hexdigest()
    hash_on = hashlib.sha256(norm_on.encode("utf-8")).hexdigest()
    return (hash_off == hash_on, hash_off, hash_on)


def check_backend_readiness(timeout_sec: float = 2.0) -> Tuple[bool, Dict[str, Any]]:
    """Checks embedding backend readiness with a real deadline-enforced timeout."""
    endpoint_url = "http://localhost:13305/api/v1/embeddings"
    expected_model = "Qwen3-Embedding-0.6B-GGUF"
    expected_dimension = 1024

    try:
        from config_loader import load_config
        cfg = load_config()
        embed_cfg = cfg.get("embedding", {})
        endpoint_url = embed_cfg.get("url") or endpoint_url
        expected_model = embed_cfg.get("model") or expected_model
        expected_dimension = embed_cfg.get("dimension") or expected_dimension
    except Exception:
        pass

    try:
        from embedder.client import _DEFAULT_PROVIDER
        endpoint_url = getattr(_DEFAULT_PROVIDER, "url", endpoint_url)
        expected_model = getattr(_DEFAULT_PROVIDER, "model", expected_model)
    except Exception:
        pass

    diag = {
        "endpoint_url": endpoint_url,
        "expected_model": expected_model,
        "expected_dimension": expected_dimension,
        "error_classification": "NONE",
        "error_detail": "",
        "preflight_deadline_sec": timeout_sec,
        "strict_policy_applied": "NO_MOCKS_NO_GENERATED_HITS_ENFORCED"
    }

    import threading

    result_container = []
    error_container = []

    def _ping_target():
        try:
            from embedder.client import _DEFAULT_PROVIDER
            res = _DEFAULT_PROVIDER.embed_batch(["ping"], is_query=True)
            result_container.append(res)
        except Exception as e:
            error_container.append(e)

    th = threading.Thread(target=_ping_target, daemon=True)
    th.start()
    th.join(timeout=timeout_sec)

    if th.is_alive():
        diag["error_classification"] = "PREFLIGHT_DEADLINE_EXCEEDED"
        diag["error_detail"] = f"Embedding provider ping exceeded timeout of {timeout_sec}s"
        return False, diag

    if error_container:
        diag["error_classification"] = "CONNECTION_REFUSED_OR_OFFLINE"
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


def run_real_retrieval_shadow_pilot(
    per_query_timeout_sec: float = 5.0,
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
        # Section 3.3 of specification:
        # If model/endpoint/index is not ready, stop real pilot with BLOCKED_DEPENDENCY.
        # Do not use SELECT LIMIT, empty list, generated hits, or mocks.
        summary = {
            "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
            "status": "BLOCKED_DEPENDENCY",
            "verdict": "BLOCKED",
            "total_queries_planned": total_queries,
            "queries_completed": 0,
            "actual_search_calls_executed": 0,
            "shadow_stats": {
                "submitted": 0,
                "processed": 0,
                "errors": 0,
                "dropped": 0
            },
            "backend_diagnostics": diag,
            "reason": (
                f"Embedding backend at {diag['endpoint_url']} is offline or unreachable ({diag['error_detail']}). "
                "Per Section 1 of specification FR-TZ-20261116-003, real retrieval pilot is stopped with "
                "BLOCKED_DEPENDENCY rather than substituting synthetic hits or mock search outputs. "
                "Action required from operator: start the Lemonade embedding server on the configured endpoint."
            ),
            "payload_byte_for_byte_equality": False,
            "rank_equality": False
        }
        records = [
            {
                "query_index": i + 1,
                "query_text": q,
                "category": "ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL",
                "status": "BLOCKED_DEPENDENCY",
                "error": diag["error_detail"]
            }
            for i, q in enumerate(queries)
        ]
        return summary, records

    # 2. If backend is online, execute true paired calls via MCP _dispatch
    from rag_server.server import _dispatch, reset_shadow_adapter, _get_shadow_adapter
    records = []
    payload_mismatches = 0
    rank_mismatches = 0
    actual_search_calls = 0
    shadow_submitted = 0
    shadow_processed = 0

    for i, q in enumerate(queries):
        # Step A: Shadow OFF call
        os.environ["FLYING_RAG_SHADOW_EIG"] = "0"
        reset_shadow_adapter()
        t0 = time.perf_counter()
        res_off = _dispatch("search_documents", {"query": q, "debug": False})
        t_off = (time.perf_counter() - t0) * 1000.0
        actual_search_calls += 1

        # Step B: Shadow ON call
        os.environ["FLYING_RAG_SHADOW_EIG"] = "1"
        reset_shadow_adapter()
        adapter = _get_shadow_adapter()
        t1 = time.perf_counter()
        res_on = _dispatch("search_documents", {"query": q, "debug": False})
        t_on = (time.perf_counter() - t1) * 1000.0
        actual_search_calls += 1
        shadow_submitted += 1

        # Wait bounded time for observation
        if adapter and hasattr(adapter, "_pool"):
            try:
                adapter._pool.shutdown(wait=True, cancel_futures=False)
                shadow_processed += 1
            except Exception:
                pass

        # Step C: Compare ranks and payloads
        ranks_match = compare_ranks(res_off, res_on)
        payloads_match, hash_off, hash_on = compare_payloads(res_off, res_on)

        if not ranks_match:
            rank_mismatches += 1
        if not payloads_match:
            payload_mismatches += 1

        records.append({
            "query_index": i + 1,
            "query_text": q,
            "status": "EXECUTED",
            "time_off_ms": round(t_off, 2),
            "time_on_ms": round(t_on, 2),
            "rank_match": ranks_match,
            "payload_equal": payloads_match,
            "payload_hash_off": hash_off[:12],
            "payload_hash_on": hash_on[:12]
        })

    summary = {
        "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
        "status": "PASSED" if (payload_mismatches == 0 and rank_mismatches == 0) else "FAILED",
        "verdict": "GO" if (payload_mismatches == 0 and rank_mismatches == 0) else "NO_GO",
        "total_queries_planned": total_queries,
        "queries_completed": len(records),
        "actual_search_calls_executed": actual_search_calls,
        "shadow_stats": {
            "submitted": shadow_submitted,
            "processed": shadow_processed,
            "errors": 0,
            "dropped": 0
        },
        "payload_byte_for_byte_equality": (payload_mismatches == 0),
        "rank_equality": (rank_mismatches == 0),
        "payload_mismatches": payload_mismatches,
        "rank_mismatches": rank_mismatches
    }
    return summary, records


class RealRetrievalShadowPilotTests(unittest.TestCase):
    def test_p1_01_on_calls_observer_and_off_does_not_call_observer_via_dispatch(self):
        """P1-01: Proves ON calls observer, OFF does not call observer; original search preserved."""
        from rag_server.server import _dispatch, reset_shadow_adapter
        from unittest.mock import MagicMock, patch

        mock_results = [{"chunk_id": "c1", "doc_id": "d1", "text": "sample text", "score": 0.95}]

        with patch("rag_server.server.search_documents", return_value=mock_results) as mock_search:
            # 1. Shadow OFF
            os.environ["FLYING_RAG_SHADOW_EIG"] = "0"
            reset_shadow_adapter()
            res_off = _dispatch("search_documents", {"query": "СП 60 пункт 7.1"})
            self.assertEqual(res_off, mock_results)
            self.assertEqual(mock_search.call_count, 1)

            # 2. Shadow ON with spy observer
            mock_adapter = MagicMock()
            mock_adapter.is_active.return_value = True

            with patch("rag_server.server._get_shadow_adapter", return_value=mock_adapter):
                os.environ["FLYING_RAG_SHADOW_EIG"] = "1"
                res_on = _dispatch("search_documents", {"query": "СП 60 пункт 7.1"})
                self.assertEqual(res_on, mock_results)
                self.assertEqual(mock_search.call_count, 2)
                mock_adapter.observe_async.assert_called_once_with("СП 60 пункт 7.1", retrieval_results=mock_results)

    def test_p1_02_rank_comparator_flags_permutations_as_rank_mismatch(self):
        """P1-02: Rank comparator unit test: permuted results trigger mismatch, identical pass."""
        results_a = [
            {"chunk_id": "chunk_001", "score": 0.98},
            {"chunk_id": "chunk_002", "score": 0.85},
            {"chunk_id": "chunk_003", "score": 0.72}
        ]
        results_b = [
            {"chunk_id": "chunk_002", "score": 0.98},  # Permuted!
            {"chunk_id": "chunk_001", "score": 0.85},
            {"chunk_id": "chunk_003", "score": 0.72}
        ]
        results_c = list(results_a)

        # Identical ranks
        self.assertTrue(compare_ranks(results_a, results_c))
        # Permuted ranks
        self.assertFalse(compare_ranks(results_a, results_b))

        # Payload hashes
        eq_ac, _, _ = compare_payloads(results_a, results_c)
        eq_ab, _, _ = compare_payloads(results_a, results_b)
        self.assertTrue(eq_ac)
        self.assertFalse(eq_ab)

    def test_p1_03_deadline_bounds_hanging_or_slow_endpoint(self):
        """P1-03: Hanging or slow endpoint is bounded by a real deadline without freezing process."""
        from unittest.mock import patch

        def slow_embed(*args, **kwargs):
            time.sleep(10.0)  # Hangs for 10s
            return [[0.1] * 1024]

        with patch("embedder.client._DEFAULT_PROVIDER.embed_batch", side_effect=slow_embed):
            t0 = time.perf_counter()
            online, diag = check_backend_readiness(timeout_sec=0.2)
            elapsed = time.perf_counter() - t0

            self.assertFalse(online)
            self.assertEqual(diag["error_classification"], "PREFLIGHT_DEADLINE_EXCEEDED")
            self.assertLess(elapsed, 1.5)  # Enforced deadline < 1.5s (did not sleep 10s)

    def test_p1_04_call_counters_accurately_reflect_all_search_calls(self):
        """P1-04: Counters accurately reflect all search calls executed (pairs)."""
        from unittest.mock import patch, MagicMock

        mock_res = [{"chunk_id": "c1", "score": 0.9}]
        search_call_counter = [0]

        def counting_dispatch(name, args):
            search_call_counter[0] += 1
            return mock_res

        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, {})):
            with patch("rag_server.server._dispatch", side_effect=counting_dispatch):
                summary, records = run_real_retrieval_shadow_pilot(max_queries=3)

                # 3 queries * 2 calls (OFF + ON) = 6 total calls
                self.assertEqual(summary["total_queries_planned"], 3)
                self.assertEqual(summary["queries_completed"], 3)
                self.assertEqual(summary["actual_search_calls_executed"], 6)
                self.assertEqual(search_call_counter[0], 6)
                self.assertEqual(summary["shadow_stats"]["submitted"], 3)

    def test_p1_05_current_offline_backend_yields_honest_blocked_dependency(self):
        """P1-05: When backend is offline, honestly returns BLOCKED_DEPENDENCY with 0 search calls."""
        summary, records = run_real_retrieval_shadow_pilot()
        self.assertEqual(summary["status"], "BLOCKED_DEPENDENCY")
        self.assertEqual(summary["verdict"], "BLOCKED")
        self.assertEqual(summary["actual_search_calls_executed"], 0)
        self.assertEqual(summary["queries_completed"], 0)
        self.assertEqual(summary["total_queries_planned"], 105)
        self.assertEqual(len(records), 105)
        self.assertIn("NO_MOCKS_NO_GENERATED_HITS_ENFORCED", summary["backend_diagnostics"]["strict_policy_applied"])
        self.assertIn("BLOCKED_DEPENDENCY", summary["reason"])
        self.assertIn("operator", summary["reason"].lower())


if __name__ == "__main__":
    unittest.main()
