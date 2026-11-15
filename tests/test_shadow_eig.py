"""
tests/test_shadow_eig.py

Unit tests for ShadowEvidenceIntegrityGate (Stage 4.1):
1. Verifies 100% zero-mutation of retrieval results.
2. Verifies divergence detection and structured JSONL logging.
3. Verifies disabled mode.
"""
from __future__ import annotations
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_server.shadow_eig import ShadowEvidenceIntegrityGate


class ShadowEigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_meta.db"
        self.log_path = Path(self.temp_dir.name) / "shadow.jsonl"
        self.source_path = "docs/СП 7.13130.docx"
        import hashlib
        self.doc_id = hashlib.sha256(self.source_path.encode("utf-8")).hexdigest()[:8]
        self.valid_pid = f"{self.doc_id}_p_0001"

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("CREATE TABLE files (source_path TEXT, file_name TEXT, format TEXT, status TEXT)")
        conn.execute("CREATE TABLE parent_chunks (parent_id TEXT, source_path TEXT, parent_text TEXT)")
        conn.execute("INSERT INTO files VALUES (?, 'СП 7.13130.docx', 'docx', 'active')", (self.source_path,))
        conn.execute(
            "INSERT INTO parent_chunks VALUES (?, ?, ?)",
            (self.valid_pid, self.source_path, "6.4 Текст пункта о вентиляции.\n6.5 Следующий пункт.")
        )
        conn.commit()
        conn.close()

        self.adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=self.log_path,
            enabled=True
        )

    def tearDown(self):
        if hasattr(self, "adapter"):
            self.adapter.shutdown(wait=False)
        self.temp_dir.cleanup()

    def test_shadow_adapter_zero_mutation(self):
        retrieval = [
            {"parent_id": self.valid_pid, "score": 0.95},
            {"parent_id": "d0000000_p_0002", "score": 0.80}
        ]
        retrieval_copy = json.loads(json.dumps(retrieval))

        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)

        # Output must be completely untouched
        self.assertEqual(retrieval, retrieval_copy)

    def test_shadow_adapter_divergence_logging(self):
        retrieval = [{"parent_id": self.valid_pid, "score": 0.95}]
        # Query mismatched topic to force divergence
        res = self.adapter.observe("СП 7.13130 пункт 8.1 подпор воздуха", retrieval_results=retrieval)

        self.assertTrue(self.log_path.exists())
        lines = self.log_path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)

        event = json.loads(lines[0])
        self.assertEqual(event["production_action"], "OBSERVED_ONLY_NO_PRODUCTION_EFFECT")
        self.assertEqual(event["divergence"], "RETRIEVAL_WITHOUT_CERTIFIED_EVIDENCE")
        self.assertEqual(event["eig_summary"]["answer_evidence_status"], "REFUSAL_REQUIRED")

    def test_shadow_adapter_disabled(self):
        disabled_adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=self.log_path,
            enabled=False
        )
        res = disabled_adapter.observe("СП 7.13130 пункт 6.4")
        self.assertIsNone(res)

    def test_shadow_adapter_parent_id_mismatch(self):
        # Retrieval returned the same source document but a completely different parent_id
        retrieval = [
            {"parent_id": "different_doc_p_9999", "source_path": self.source_path, "file_name": "СП 7.13130.docx", "score": 0.90}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "RETRIEVAL_PARENT_ID_MISMATCH")

    def test_shadow_adapter_colliding_basenames_different_paths(self):
        # Same basename "СП 7.13130.docx" but different directory -> RETRIEVAL_SOURCE_MISMATCH (P1-06)
        retrieval = [
            {"parent_id": self.valid_pid, "source_path": "archive/СП 7.13130.docx", "file_name": "СП 7.13130.docx", "score": 0.92}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "RETRIEVAL_SOURCE_MISMATCH")

    def test_shadow_adapter_congruent(self):
        # Retrieval returned the exact certified parent_id and source
        retrieval = [
            {"parent_id": self.valid_pid, "file_name": "СП 7.13130.docx", "source_path": self.source_path, "score": 0.99}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

        lines = self.log_path.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "CONGRUENT")

    def test_shadow_adapter_unverifiable_provenance(self):
        # Retrieval has parent_id but no source_path / file_name
        retrieval = [{"parent_id": self.valid_pid, "score": 0.95}]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "UNVERIFIABLE_PROVENANCE")

    def test_shadow_adapter_retrieval_source_mismatch(self):
        # Retrieval returned a completely different document source
        retrieval = [
            {"parent_id": "other_p_0001", "source_path": "other_docs/СП 60.13330.docx", "score": 0.90}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "RETRIEVAL_SOURCE_MISMATCH")

    def test_shadow_adapter_eig_not_applicable_on_broad_query(self):
        # Broad semantic query where EIG abstains (Blocker P1-07)
        retrieval = [{"parent_id": self.valid_pid, "source_path": self.source_path, "score": 0.88}]
        res = self.adapter.observe("требования к вытяжной вентиляции автостоянок", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "NOT_APPLICABLE")

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "EIG_NOT_APPLICABLE")
        self.assertEqual(event["eig_summary"]["query_applicability"], "NON_NORMATIVE_QUERY")

    def test_shadow_adapter_latency_metrics_and_path_sanitization(self):
        # Verify separate wall/cpu latency and sanitized path (Blocker P1-09 & P1-10)
        retrieval = [
            {"parent_id": self.valid_pid, "source_path": self.source_path, "file_name": "СП 7.13130.docx", "score": 0.95}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        perf = event["performance"]
        self.assertIn("wall_latency_ms", perf)
        self.assertIn("cpu_latency_ms", perf)
        self.assertIsInstance(perf["wall_latency_ms"], (int, float))
        self.assertIsInstance(perf["cpu_latency_ms"], (int, float))
        # Ensure path is sanitized (no raw absolute drive letters)
        import re
        src_path = event["eig_summary"]["source_path"]
        self.assertFalse(bool(re.search(r'^[a-zA-Z]:', src_path)))

    def test_shadow_adapter_fail_open_on_exception(self):
        from unittest.mock import patch
        with patch.object(self.adapter.gate, "assess_evidence", side_effect=RuntimeError("Simulated EIG failure")):
            res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=[{"parent_id": "p1"}])
            self.assertIsNone(res)
            self.assertEqual(self.adapter.error_count, 1)

        lines = self.log_path.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "SHADOW_ERROR")
        self.assertEqual(event["error_type"], "RuntimeError")

    def test_shadow_adapter_async_non_blocking(self):
        import time
        from unittest.mock import patch

        def slow_assess(*args, **kwargs):
            time.sleep(0.5)
            from evidence_gate.models import EvidenceAssessmentResult
            return EvidenceAssessmentResult(
                query="q", normalized_topic="СП 7.13130", normalized_clause="6.4",
                answer_evidence_status="USABLE_FOR_ANSWER",
                evidence_completeness="COMPLETE_WITH_CONTINUATION",
                formula_status="NO_FORMULAS",
                query_applicability="NORMATIVE_CLAUSE_QUERY",
                source_status="SOURCE_NOT_VERIFIED",
                source_path=self.source_path,
                parent_id=self.valid_pid,
                extracted_clause_length=50,
                verification_reason="ok",
            )

        with patch.object(self.adapter.gate, "assess_evidence", side_effect=slow_assess):
            retrieval = [{"parent_id": self.valid_pid, "source_path": self.source_path, "file_name": "СП 7.13130.docx"}]
            t0 = time.perf_counter()
            enqueued = self.adapter.observe_async("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
            dt = time.perf_counter() - t0
            self.assertTrue(enqueued)
            # observe_async must return immediately without waiting for slow_assess (0.5s)
            self.assertLess(dt, 0.25)

            # Shutdown wait flushes the worker
            self.adapter.shutdown(wait=True, timeout=3.0)
            self.assertTrue(self.log_path.exists())
            lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(lines), 1)

    def test_shadow_adapter_bounded_queue_drop(self):
        # Fill queue to maximum capacity
        import time
        adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=Path(self.temp_dir.name) / "drop_test.jsonl",
            enabled=True
        )
        try:
            # Simulate saturated queue by setting pending_count to MAX_QUEUE_SIZE
            with adapter._lock:
                adapter._pending_count = 100
            # Next submission must drop because queue is full (max 100)
            res = adapter.observe_async("overflow query", [])
            self.assertFalse(res)
            self.assertGreater(adapter.drop_count, 0)
        finally:
            adapter.shutdown(wait=False)

    def test_shadow_adapter_dynamic_deactivation(self):
        import os
        old_val = os.environ.get("FLYING_RAG_SHADOW_EIG")
        try:
            os.environ["FLYING_RAG_SHADOW_EIG"] = "0"
            self.assertFalse(self.adapter.is_active())
            res = self.adapter.observe_async("СП 7.13130 пункт 6.4", [])
            self.assertFalse(res)

            os.environ["FLYING_RAG_SHADOW_EIG"] = "1"
            self.assertTrue(self.adapter.is_active())
        finally:
            if old_val is None:
                os.environ.pop("FLYING_RAG_SHADOW_EIG", None)
            else:
                os.environ["FLYING_RAG_SHADOW_EIG"] = old_val

    def test_shadow_adapter_privacy_sanitization(self):
        # Pass private user paths in query and mock result
        import getpass
        current_username = getpass.getuser()
        private_query = f"СП 7.13130 пункт 6.4 из C:\\Users\\{current_username}\\Documents\\secret.docx и X:\\Archive\\doc.docx"
        retrieval = [
            {"parent_id": self.valid_pid, "source_path": f"C:\\Users\\{current_username}\\secret.docx", "file_name": "secret.docx", "score": 0.9}
        ]
        self.adapter.observe(private_query, retrieval_results=retrieval)
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        last_line = lines[-1]
        event = json.loads(last_line)

        # Raw query must NOT be stored, query_hash must be present
        self.assertNotIn("query", event)
        self.assertIn("query_hash", event)
        self.assertIn("query_sanitized", event)
        self.assertNotIn(current_username.lower(), last_line.lower())
        self.assertNotIn("x:\\", last_line.lower())


if __name__ == "__main__":
    unittest.main()
