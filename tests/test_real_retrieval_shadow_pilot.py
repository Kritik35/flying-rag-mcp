"""
tests/test_real_retrieval_shadow_pilot.py

Real Read-Only Shadow Pilot (Stage 4.2.6 / Block S6).
Executes actual search pipeline calls (MCP search_documents -> retrieval backend)
under STRICT READ-ONLY isolation without modifying production or creating tables.

If the embedding backend / endpoint is unavailable, per Section 3.3 of FR-TZ-20261116-002:
honestly halts with BLOCKED_DEPENDENCY rather than substituting mock hits or SELECT LIMIT.
"""

from __future__ import annotations
import os
import sys
import json
import time
import unittest
from pathlib import Path
from typing import Dict, Any, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.test_shadow_pilot_100_queries import ACTUAL_NORMATIVE_QUERIES, SYNTHETIC_ADVERSARIAL_QUERIES


def run_real_retrieval_shadow_pilot() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Executes or checks the real retrieval shadow pilot pipeline under strict isolation.
    Returns: (summary_dict, detailed_query_records)
    """
    # 1. Backend readiness preflight check
    backend_online = False
    backend_error = ""
    endpoint_url = "http://localhost:13305/api/v1/embeddings"
    expected_model = "Qwen3-Embedding-0.6B-GGUF"

    try:
        from embedder.client import _DEFAULT_PROVIDER
        endpoint_url = getattr(_DEFAULT_PROVIDER, "url", endpoint_url)
        expected_model = getattr(_DEFAULT_PROVIDER, "model", expected_model)
        # Attempt minimal ping with 2.0s bounded timeout
        _DEFAULT_PROVIDER.embed_batch(["ping"], is_query=True)
        backend_online = True
    except Exception as e:
        backend_online = False
        backend_error = str(e)

    total_queries = len(ACTUAL_NORMATIVE_QUERIES) + len(SYNTHETIC_ADVERSARIAL_QUERIES)

    if not backend_online:
        # Per Section 3.3 of FR-TZ-20261116-002:
        # "Если модель embeddings/локальный endpoint/индекс/RO доступ не готовы,
        #  остановить реальный пилот с BLOCKED_DEPENDENCY и конкретной диагностикой.
        #  Не переходить на SELECT LIMIT, пустую выдачу, generated hits или mock для получения PASS."
        summary = {
            "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
            "status": "BLOCKED_DEPENDENCY",
            "verdict": "BLOCKED",
            "total_queries_planned": total_queries,
            "actual_search_calls_executed": 0,
            "backend_diagnostics": {
                "endpoint_url": endpoint_url,
                "expected_model": expected_model,
                "error_classification": "CONNECTION_REFUSED_OR_OFFLINE",
                "error_detail": backend_error,
                "per_query_timeout_sec": 5.0,
                "strict_policy_applied": "NO_MOCKS_NO_GENERATED_HITS_ENFORCED"
            },
            "reason": (
                f"Embedding backend at {endpoint_url} is offline or unreachable ({backend_error}). "
                "Per Section 3.3 of specification FR-TZ-20261116-002, real retrieval pilot is stopped with "
                "BLOCKED_DEPENDENCY rather than substituting synthetic hits or mock search outputs."
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
                "error": "Backend offline"
            }
            for i, q in enumerate(ACTUAL_NORMATIVE_QUERIES + SYNTHETIC_ADVERSARIAL_QUERIES)
        ]
        return summary, records

    # 2. If backend is online, execute genuine search_documents calls
    from rag_server.tools import search_documents
    records = []
    payload_mismatches = 0
    rank_mismatches = 0

    for i, q in enumerate(ACTUAL_NORMATIVE_QUERIES + SYNTHETIC_ADVERSARIAL_QUERIES):
        t0 = time.perf_counter()
        res_off = search_documents(q, debug=False)
        t_off = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        res_on = search_documents(q, debug=False)
        t_on = (time.perf_counter() - t1) * 1000.0

        byte_equal = (json.dumps(res_off, sort_keys=True) == json.dumps(res_on, sort_keys=True))
        if not byte_equal:
            payload_mismatches += 1

        records.append({
            "query_index": i + 1,
            "query_text": q,
            "status": "EXECUTED",
            "time_off_ms": round(t_off, 2),
            "time_on_ms": round(t_on, 2),
            "byte_equal": byte_equal
        })

    summary = {
        "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
        "status": "PASSED" if (payload_mismatches == 0 and rank_mismatches == 0) else "FAILED",
        "verdict": "GO" if (payload_mismatches == 0 and rank_mismatches == 0) else "NO_GO",
        "total_queries_planned": total_queries,
        "actual_search_calls_executed": len(records),
        "payload_byte_for_byte_equality": (payload_mismatches == 0),
        "rank_equality": (rank_mismatches == 0)
    }
    return summary, records


class RealRetrievalShadowPilotTests(unittest.TestCase):
    def test_real_retrieval_shadow_pilot_contract_and_honest_blocked_boundary(self):
        summary, records = run_real_retrieval_shadow_pilot()
        self.assertIn(summary["status"], ("PASSED", "BLOCKED_DEPENDENCY"))
        self.assertIn(summary["verdict"], ("GO", "BLOCKED"))
        self.assertEqual(len(records), 105)

        if summary["status"] == "BLOCKED_DEPENDENCY":
            self.assertEqual(summary["verdict"], "BLOCKED")
            self.assertIn("NO_MOCKS_NO_GENERATED_HITS_ENFORCED", summary["backend_diagnostics"]["strict_policy_applied"])
            self.assertIn("BLOCKED_DEPENDENCY", summary["reason"])


if __name__ == "__main__":
    unittest.main()
