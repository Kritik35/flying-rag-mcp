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
            self.adapter.shutdown(wait=True, timeout=1.0)
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
        from evidence_gate.evidence_gate import EvidenceGateResult

        def slow_assess(*args, **kwargs):
            time.sleep(0.3)
            return EvidenceGateResult(
                query_applicability="NORMATIVE_CITATION",
                boundary_integrity="EXACT_BOUNDARIES",
                text_integrity="COMPLETE",
                formula_integrity="NOT_APPLICABLE",
                missing_formulas=[],
                topic_alignment="TOPIC_MATCH",
                source_integrity="SINGLE_EDITION_MATCH",
                answer_evidence_status="USABLE_FOR_ANSWER",
                document_status="EXISTS_IN_INDEX",
                edition_status="LOCAL_INGESTED_EDITION",
                clause_status="FOUND_IN_CORPUS",
                source_path=self.source_path,
                parent_ids=[self.valid_pid],
                source_spans=[],
                certified_text="6.4 Текст пункта о вентиляции.",
                verification_reason="ok",
            )

        with patch.object(self.adapter.gate, "assess_evidence", side_effect=slow_assess):
            retrieval = [{"parent_id": self.valid_pid, "source_path": self.source_path, "file_name": "СП 7.13130.docx"}]
            t0 = time.perf_counter()
            enqueued = self.adapter.observe_async("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
            dt = time.perf_counter() - t0
            self.assertTrue(enqueued)
            # observe_async must return immediately without waiting for slow_assess (0.3s)
            self.assertLess(dt, 0.25)

            # Shutdown wait flushes the worker
            self.adapter.shutdown(wait=True, timeout=3.0)
            self.assertTrue(self.log_path.exists())
            lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(lines), 1)

            # CR-05: Verify background worker actually succeeded without SHADOW_ERROR
            last_event = json.loads(lines[-1])
            self.assertNotEqual(last_event.get("divergence"), "SHADOW_ERROR")
            self.assertEqual(last_event.get("divergence"), "CONGRUENT")
            self.assertEqual(self.adapter.error_count, 0)
            self.assertGreaterEqual(self.adapter.processed_count, 1)

    def test_shadow_adapter_cross_hit_false_congruence_rejected(self):
        # CR-07: Hit 1 has valid parent_id but wrong source; Hit 2 has valid source but wrong parent_id
        retrieval = [
            {"parent_id": self.valid_pid, "source_path": "other/doc.docx", "file_name": "doc.docx"},
            {"parent_id": "other_p_9999", "source_path": self.source_path, "file_name": "СП 7.13130.docx"}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        # Must NOT be falsely classified as CONGRUENT
        self.assertNotEqual(event["divergence"], "CONGRUENT")

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
        # CR-03: Pass private user paths in query and mock result
        import getpass
        import os
        current_username = getpass.getuser()
        private_query = f"СП 7.13130 пункт 6.4 из C:\\Users\\{current_username}\\Documents\\secret.docx и X:\\Archive\\doc.docx"
        retrieval = [
            {"parent_id": self.valid_pid, "source_path": f"C:\\Users\\{current_username}\\secret.docx", "file_name": "secret.docx", "score": 0.9}
        ]

        # 1. Default policy: query_sanitized is OMITTED from telemetry event
        self.adapter.observe(private_query, retrieval_results=retrieval)
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        last_line = lines[-1]
        event = json.loads(last_line)

        self.assertNotIn("query", event)
        self.assertNotIn("query_sanitized", event, "query_sanitized must be omitted by default (CR-03)")
        self.assertIn("query_hash", event)
        self.assertNotIn(current_username.lower(), last_line.lower())
        self.assertNotIn("x:\\", last_line.lower())

        # 2. Opt-in policy: when FLYING_RAG_SHADOW_LOG_QUERY_TEXT=1, query_sanitized is present and sanitized
        os.environ["FLYING_RAG_SHADOW_LOG_QUERY_TEXT"] = "1"
        try:
            self.adapter.observe(private_query, retrieval_results=retrieval)
            lines2 = self.log_path.read_text(encoding="utf-8").strip().splitlines()
            event2 = json.loads(lines2[-1])
            self.assertIn("query_sanitized", event2)
            self.assertNotIn("query", event2)
            self.assertNotIn(current_username.lower(), json.dumps(event2).lower())
            self.assertNotIn("x:\\", json.dumps(event2).lower())
        finally:
            os.environ.pop("FLYING_RAG_SHADOW_LOG_QUERY_TEXT", None)

    def test_sanitize_path_and_text_robustness(self):
        # CR-03: Test UNC paths, quoted paths with spaces, and Russian paths with spaces
        from rag_server.shadow_eig import _sanitize_path, _sanitize_text

        # UNC path
        unc_res = _sanitize_text(r"Обратитесь к \\nas_server\share\normative\SP7.docx")
        self.assertNotIn(r"\\nas_server", unc_res)
        self.assertIn("[UNC_PATH]", unc_res)

        # Quoted Windows path with spaces
        quoted_res = _sanitize_text(r'Документ расположен в "C:\Program Files\App\doc.docx"')
        self.assertNotIn("C:\\Program Files", quoted_res)

        # Russian path with space 'Мой диск'
        disk_res = _sanitize_path(r"C:\Мой диск\НТД\СП 7.docx")
        self.assertTrue(disk_res.startswith("[CORPUS]/"))

    def test_shutdown_bounded_timeout_with_hanging_worker(self):
        # S1: Worker hangs on Event.wait(); shutdown(timeout=0.3) must return <= 0.8s
        import threading
        import time
        hang_event = threading.Event()
        started_event = threading.Event()

        def hanging_assess(*args, **kwargs):
            started_event.set()
            hang_event.wait(timeout=5.0)
            return None

        from unittest.mock import patch
        with patch.object(self.adapter.gate, "assess_evidence", side_effect=hanging_assess):
            enqueued = self.adapter.observe_async("hanging query", [])
            self.assertTrue(enqueued)
            started_event.wait(timeout=2.0)

            t0 = time.perf_counter()
            res = self.adapter.shutdown(wait=True, timeout=0.3)
            dt = time.perf_counter() - t0

            # Must return within bounded time (< 1.0s), not waiting 5s for hanging task
            self.assertLess(dt, 1.0)
            self.assertFalse(res["clean_exit"])
            self.assertEqual(res["hard_stop_status"], "HARD_STOP_UNSUPPORTED")

            # Release hanging thread
            hang_event.set()

    def test_shutdown_idempotent(self):
        # S1: Double shutdown must be safe, idempotent, and non-blocking
        res1 = self.adapter.shutdown(wait=True, timeout=1.0)
        self.assertTrue(isinstance(res1, dict))
        res2 = self.adapter.shutdown(wait=True, timeout=1.0)
        self.assertTrue(isinstance(res2, dict))
        self.assertEqual(res1["clean_exit"], res2["clean_exit"])

    def test_cancel_pending_cancels_queued_tasks(self):
        # S1: Tasks queued behind a slow task are cancelled
        import threading
        import time
        gate_event = threading.Event()

        def slow_worker(*args, **kwargs):
            gate_event.wait(timeout=2.0)
            return None

        from unittest.mock import patch
        with patch.object(self.adapter.gate, "assess_evidence", side_effect=slow_worker):
            # Submit task 1 (will be running)
            self.adapter.observe_async("q1", [])
            # Submit tasks 2-5 (queued)
            for i in range(2, 6):
                self.adapter.observe_async(f"q{i}", [])

            cancelled = self.adapter.cancel_pending()
            # At least one queued task should have been cancelled
            self.assertGreaterEqual(cancelled, 1)
            self.assertGreaterEqual(self.adapter.drop_count, cancelled)

            gate_event.set()
            self.adapter.shutdown(wait=True, timeout=1.0)

    def test_external_control_file_lifecycle(self):
        # S2: External control file disables and re-enables shadow without process restart
        from rag_server.shadow_eig import write_shadow_control, read_shadow_control
        ctrl_path = Path(self.temp_dir.name) / "shadow_control.json"

        adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=Path(self.temp_dir.name) / "ctrl_test.jsonl",
            enabled=True,
            control_file_path=ctrl_path
        )
        try:
            # 1. Missing control file -> fail-safe disable
            self.assertFalse(adapter.is_active())
            ok, reason = read_shadow_control(ctrl_path)
            self.assertFalse(ok)
            self.assertIn("missing", reason)

            # 2. Write enabled: true -> shadow active
            write_shadow_control(ctrl_path, enabled=True, reason="trial enable")
            self.assertTrue(adapter.is_active())
            submitted = adapter.observe_async("query 1", [])
            self.assertTrue(submitted)

            # 3. Write enabled: false -> external kill-switch disabled immediately
            write_shadow_control(ctrl_path, enabled=False, reason="operator kill switch")
            self.assertFalse(adapter.is_active())
            submitted_while_off = adapter.observe_async("query 2", [])
            self.assertFalse(submitted_while_off)

            # 4. Corrupt JSON -> fail-safe disable
            ctrl_path.write_text("{corrupt: json syntax error", encoding="utf-8")
            self.assertFalse(adapter.is_active())

            # 5. Write enabled: true again -> shadow active again
            write_shadow_control(ctrl_path, enabled=True, reason="trial resume")
            self.assertTrue(adapter.is_active())
            submitted_again = adapter.observe_async("query 3", [])
            self.assertTrue(submitted_again)
        finally:
            adapter.shutdown(wait=True, timeout=1.0)

    def test_external_control_file_precedence(self):
        # S2: Startup env var FLYING_RAG_SHADOW_EIG=0 overrides control file enabled: true
        from rag_server.shadow_eig import write_shadow_control
        ctrl_path = Path(self.temp_dir.name) / "shadow_control_prec.json"
        write_shadow_control(ctrl_path, enabled=True)

        import os
        old_val = os.environ.get("FLYING_RAG_SHADOW_EIG")
        try:
            os.environ["FLYING_RAG_SHADOW_EIG"] = "0"
            adapter = ShadowEvidenceIntegrityGate(
                metadata_db_path=self.db_path,
                control_file_path=ctrl_path,
                enabled=True
            )
            self.assertFalse(adapter.is_active(), "Startup env FLYING_RAG_SHADOW_EIG=0 must take precedence over control file")
        finally:
            if old_val is None:
                os.environ.pop("FLYING_RAG_SHADOW_EIG", None)
            else:
                os.environ["FLYING_RAG_SHADOW_EIG"] = old_val

    def test_concurrent_load_and_queue_accounting(self):
        # S4: High concurrency load test verifying exact counter conservation
        import threading
        adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=Path(self.temp_dir.name) / "concurrent.jsonl",
            enabled=True
        )
        try:
            errors = []
            def submitter(tid):
                for i in range(15):
                    try:
                        adapter.observe_async(f"concurrent_q_{tid}_{i}", [])
                    except Exception as ex:
                        errors.append(ex)

            threads = [threading.Thread(target=submitter, args=(t,)) for t in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(errors), 0)
            self.assertEqual(adapter.submitted_count + adapter.drop_count, 5 * 15)

            # Shutdown flushes execution and cancels remaining pending tasks
            res = adapter.shutdown(wait=True, timeout=5.0)
            # Invariant: pending_count must be 0 after shutdown
            self.assertEqual(adapter._pending_count, 0)
            # Invariant: all submitted tasks are accounted for (processed + cancelled)
            self.assertEqual(adapter.submitted_count, adapter.processed_count + res["cancelled_count"])
            # Invariant: total attempts equal submitted + rejected-on-submit
            self.assertEqual(adapter.submitted_count + (adapter.drop_count - res["cancelled_count"]), 5 * 15)
        finally:
            adapter.shutdown(wait=False)

    def test_server_reset_and_shutdown_shadow_adapter(self):
        # S1: Server reset and shutdown functions are idempotent
        from rag_server import server
        server.reset_shadow_adapter()
        self.assertIsNone(server._shadow_adapter)
        server.shutdown_shadow_adapter(timeout=1.0)
        self.assertIsNone(server._shadow_adapter)


if __name__ == "__main__":
    unittest.main()
