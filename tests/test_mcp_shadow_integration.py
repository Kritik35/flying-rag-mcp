"""
tests/test_mcp_shadow_integration.py

Integration test for Shadow Evidence Integrity Gate via MCP dispatch path (Blocker 8):
1. Verifies byte-for-byte serialized JSON response equality with shadow enabled vs disabled.
2. Verifies passive background logging with zero production payload mutation.
3. Verifies complete fail-open isolation when shadow adapter encounters errors.
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import rag_server.server as server_module
from rag_server.shadow_eig import ShadowEvidenceIntegrityGate, write_shadow_control, read_shadow_control


class McpShadowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_meta.db"
        self.log_path = Path(self.temp_dir.name) / "shadow_telemetry.jsonl"
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

        # Simulated production search_documents results
        self.mock_retrieval_output = [
            {
                "chunk_id": f"{self.doc_id}_c_0001",
                "parent_id": self.valid_pid,
                "doc_id": self.doc_id,
                "text": "6.4 Текст пункта о вентиляции.",
                "score": 0.942,
                "source_path": self.source_path,
                "file_name": "СП 7.13130.docx"
            },
            {
                "chunk_id": f"{self.doc_id}_c_0002",
                "parent_id": f"{self.doc_id}_p_0002",
                "doc_id": self.doc_id,
                "text": "Дополнительный контекст.",
                "score": 0.781,
                "source_path": self.source_path,
                "file_name": "СП 7.13130.docx"
            }
        ]

    def tearDown(self):
        server_module.shutdown_shadow_adapter(timeout=2.0)
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_real_bootstrap_success_via_env(self):
        # Test real _get_shadow_adapter without mock bypass (Blocker P0-01)
        with patch.dict(os.environ, {
            "FLYING_RAG_SHADOW_EIG": "1",
            "FLYING_RAG_METADATA_DB": str(self.db_path)
        }):
            adapter = server_module._get_shadow_adapter(force_reload=True)
            self.assertIsNotNone(adapter, "Real bootstrap should succeed with valid DB and env=1")
            self.assertTrue(adapter.enabled)
            self.assertEqual(adapter.metadata_db_path, self.db_path)

            # Test actual dispatch through real adapter
            query_args = {"query": "СП 7.13130 пункт 6.4", "top_k": 5}
            with patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
                res = server_module._dispatch("search_documents", query_args)
                self.assertEqual(res, self.mock_retrieval_output)

    def test_real_bootstrap_disabled_via_env(self):
        # Strict precedence: FLYING_RAG_SHADOW_EIG=0 forces disabled (Blocker P1-09)
        with patch.dict(os.environ, {
            "FLYING_RAG_SHADOW_EIG": "0",
            "FLYING_RAG_METADATA_DB": str(self.db_path)
        }):
            adapter = server_module._get_shadow_adapter(force_reload=True)
            self.assertIsNone(adapter, "FLYING_RAG_SHADOW_EIG=0 must unconditionally disable adapter")

    def test_real_bootstrap_missing_db_fails_visible(self):
        # Non-existent DB must emit warning and return None (Blocker P0-01)
        non_existent_db = Path(self.temp_dir.name) / "does_not_exist.db"
        with patch.dict(os.environ, {
            "FLYING_RAG_SHADOW_EIG": "1",
            "FLYING_RAG_METADATA_DB": str(non_existent_db)
        }):
            with self.assertLogs("rag_server", level="WARNING") as cm:
                adapter = server_module._get_shadow_adapter(force_reload=True)
                self.assertIsNone(adapter)
                self.assertTrue(any("Metadata database not found" in log for log in cm.output))

    def test_byte_for_byte_serialized_mcp_output_equality(self):
        query_args = {
            "query": "СП 7.13130 пункт 6.4",
            "top_k": 5
        }

        # 1. Execute dispatch with SHADOW DISABLED
        with patch.object(server_module, "_shadow_adapter", None), \
             patch.object(server_module, "_shadow_initialized", True), \
             patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
            res_disabled = server_module._dispatch("search_documents", query_args)
            safe_disabled = server_module._safe_result(res_disabled)
            json_disabled = json.dumps(safe_disabled, sort_keys=True, ensure_ascii=False)

        # 2. Execute dispatch with SHADOW ENABLED
        shadow_adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=self.log_path,
            enabled=True
        )

        with patch.object(server_module, "_shadow_adapter", shadow_adapter), \
             patch.object(server_module, "_shadow_initialized", True), \
             patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
            res_enabled = server_module._dispatch("search_documents", query_args)
            safe_enabled = server_module._safe_result(res_enabled)
            json_enabled = json.dumps(safe_enabled, sort_keys=True, ensure_ascii=False)

        # 3. Assert Byte-for-Byte Equality
        self.assertEqual(
            json_disabled,
            json_enabled,
            "MCP serialized output must be byte-for-byte identical with shadow enabled vs disabled"
        )
        self.assertEqual(res_disabled, res_enabled)

        # Flush async worker before asserting on log output (B1)
        shadow_adapter.shutdown(wait=True, timeout=2.0)

        # 4. Verify shadow telemetry log was written
        self.assertTrue(self.log_path.exists())
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["production_action"], "OBSERVED_ONLY_NO_PRODUCTION_EFFECT")
        self.assertEqual(event["divergence"], "CONGRUENT")

    def test_mcp_dispatch_fail_open_on_shadow_crash(self):
        query_args = {"query": "СП 7.13130 пункт 6.4"}
        failing_shadow = MagicMock()
        failing_shadow.observe.side_effect = RuntimeError("Catastrophic shadow error")

        with patch.object(server_module, "_shadow_adapter", failing_shadow), \
             patch.object(server_module, "_shadow_initialized", True), \
             patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
            # Must NOT raise exception to MCP client
            res = server_module._dispatch("search_documents", query_args)
            self.assertEqual(res, self.mock_retrieval_output)

    def test_byte_for_byte_equality_across_all_payload_shapes(self):
        # S4: Prove byte-for-byte serialized output equality across list, dict with results, empty, error
        shapes = [
            ("list_results", self.mock_retrieval_output),
            ("dict_results", {"results": self.mock_retrieval_output, "query": "q", "total": 2}),
            ("empty_results", []),
            ("error_dict", {"error": "internal_search_failure", "status": "failed"})
        ]

        query_args = {"query": "СП 7.13130 пункт 6.4", "top_k": 5}

        for shape_name, payload in shapes:
            with self.subTest(shape=shape_name):
                # 1. Shadow disabled
                with patch.object(server_module, "_shadow_adapter", None), \
                     patch.object(server_module, "_shadow_initialized", True), \
                     patch.object(server_module, "search_documents", return_value=payload):
                    res_off = server_module._dispatch("search_documents", query_args)
                    json_off = json.dumps(server_module._safe_result(res_off), sort_keys=True, ensure_ascii=False)

                # 2. Shadow enabled
                log_p = Path(self.temp_dir.name) / f"shadow_{shape_name}.jsonl"
                adapter = ShadowEvidenceIntegrityGate(
                    metadata_db_path=self.db_path,
                    log_path=log_p,
                    enabled=True
                )
                try:
                    with patch.object(server_module, "_shadow_adapter", adapter), \
                         patch.object(server_module, "_shadow_initialized", True), \
                         patch.object(server_module, "search_documents", return_value=payload):
                        res_on = server_module._dispatch("search_documents", query_args)
                        json_on = json.dumps(server_module._safe_result(res_on), sort_keys=True, ensure_ascii=False)

                    self.assertEqual(
                        json_off, json_on,
                        f"Shape '{shape_name}' failed byte-for-byte equality with shadow enabled vs disabled"
                    )
                finally:
                    adapter.shutdown(wait=True, timeout=1.0)

    def test_dispatch_overhead_under_slow_eig_100_runs(self):
        # S4: Benchmark 100 runs with simulated slow EIG (300ms).
        # Client dispatch must be non-blocking and overhead must be minimal (< 20ms).
        import time

        def slow_observe(*args, **kwargs):
            time.sleep(0.3)
            return None

        adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=Path(self.temp_dir.name) / "perf.jsonl",
            enabled=True
        )
        adapter.observe = slow_observe

        query_args = {"query": "СП 7.13130 пункт 6.4", "top_k": 5}

        try:
            # 1. Warm-up
            with patch.object(server_module, "_shadow_adapter", None), \
                 patch.object(server_module, "_shadow_initialized", True), \
                 patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
                for _ in range(5):
                    server_module._dispatch("search_documents", query_args)

            # 2. Measure 100 runs with SHADOW DISABLED
            off_latencies = []
            with patch.object(server_module, "_shadow_adapter", None), \
                 patch.object(server_module, "_shadow_initialized", True), \
                 patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
                for _ in range(100):
                    t0 = time.perf_counter()
                    server_module._dispatch("search_documents", query_args)
                    off_latencies.append((time.perf_counter() - t0) * 1000.0)

            # 3. Measure 100 runs with SHADOW ENABLED (worker sleeps 300ms)
            on_latencies = []
            with patch.object(server_module, "_shadow_adapter", adapter), \
                 patch.object(server_module, "_shadow_initialized", True), \
                 patch.object(server_module, "search_documents", return_value=self.mock_retrieval_output):
                for _ in range(100):
                    t0 = time.perf_counter()
                    server_module._dispatch("search_documents", query_args)
                    on_latencies.append((time.perf_counter() - t0) * 1000.0)

            # Assert client did NOT wait 300ms on each call
            p50_on = sorted(on_latencies)[50]
            p95_on = sorted(on_latencies)[95]
            self.assertLess(p50_on, 25.0, f"p50 dispatch latency with shadow ({p50_on:.2f}ms) must not block on EIG")
            self.assertLess(p95_on, 50.0, f"p95 dispatch latency with shadow ({p95_on:.2f}ms) must not block on EIG")

            # Verify queue saturation handled cleanly without exceptions
            self.assertGreater(adapter.drop_count + adapter.submitted_count, 0)
        finally:
            adapter.shutdown(wait=False)

    def test_external_control_file_multiprocess_kill_switch(self):
        # S2: Test external kill switch via separate process without modifying os.environ in MCP
        from rag_server.shadow_eig import write_shadow_control
        import multiprocessing
        import time

        ctrl_path = Path(self.temp_dir.name) / "multi_ctrl.json"
        log_path = Path(self.temp_dir.name) / "multi_log.jsonl"
        write_shadow_control(ctrl_path, enabled=True, reason="initial")

        # Worker script executed as isolated separate process
        code = f"""
import sys, time, json
from pathlib import Path
from rag_server.shadow_eig import ShadowEvidenceIntegrityGate, write_shadow_control, read_shadow_control

ctrl_p = Path(r'{ctrl_path}')
log_p = Path(r'{log_path}')
meta_p = Path(r'{self.db_path}')

adapter = ShadowEvidenceIntegrityGate(
    metadata_db_path=meta_p,
    log_path=log_p,
    enabled=True,
    control_file_path=ctrl_p
)

# Loop processing 20 queries, 50ms apart
for i in range(20):
    adapter.observe_async(f'proc_q_{{i}}', [])
    time.sleep(0.05)

adapter.shutdown(wait=True, timeout=2.0)
"""
        import subprocess
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parent.parent))

        # While child process is running, change control file from parent process:
        time.sleep(0.2)
        write_shadow_control(ctrl_path, enabled=False, reason="external parent kill switch")
        time.sleep(0.3)
        write_shadow_control(ctrl_path, enabled=True, reason="external parent resume")

        proc.wait(timeout=10.0)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(log_path.exists())

    def test_control_file_relative_path_resolution_independent_of_foreign_cwd(self):
        """Block S5: Verifies relative control-file path binds to ROOT, not foreign CWD."""
        from config_loader import ROOT
        foreign_dir = tempfile.mkdtemp(prefix="foreign_cwd_")
        original_cwd = os.getcwd()
        rel_ctrl = "config/shadow_test_control.json"
        target_ctrl = ROOT / rel_ctrl
        target_ctrl.parent.mkdir(parents=True, exist_ok=True)
        write_shadow_control(target_ctrl, enabled=True, reason="test foreign cwd")

        try:
            os.chdir(foreign_dir)
            server_module.reset_shadow_adapter()

            with patch.dict(os.environ, {
                "FLYING_RAG_SHADOW_EIG": "1",
                "FLYING_RAG_SHADOW_CONTROL_FILE": rel_ctrl,
                "FLYING_RAG_METADATA_DB": str(self.db_path)
            }):
                with patch("config_loader.load_config", return_value={"storage": {"metadata_db": str(self.db_path)}}):
                    adapter = server_module._get_shadow_adapter()
                    self.assertIsNotNone(adapter)
                    expected_p = target_ctrl.resolve()
                    self.assertEqual(adapter.control_file_path, expected_p)
                    self.assertNotEqual(adapter.control_file_path, (Path(foreign_dir) / rel_ctrl).resolve())
        finally:
            os.chdir(original_cwd)
            server_module.reset_shadow_adapter()
            if target_ctrl.exists():
                try:
                    target_ctrl.unlink()
                except Exception:
                    pass
            try:
                shutil.rmtree(foreign_dir)
            except Exception:
                pass

    def test_missing_or_corrupt_configured_control_file_fails_safe_disabled(self):
        """Block S5: Configured missing/corrupt control file defaults to disabled."""
        missing_ctrl = Path(self.temp_dir.name) / "non_existent_control.json"
        adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=self.log_path,
            enabled=True,
            control_file_path=missing_ctrl
        )
        self.assertFalse(adapter.is_active())

        # Corrupt file
        corrupt_ctrl = Path(self.temp_dir.name) / "corrupt_control.json"
        corrupt_ctrl.write_text("{not valid json!!!}", encoding="utf-8")
        adapter_corrupt = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=self.log_path,
            enabled=True,
            control_file_path=corrupt_ctrl
        )
        self.assertFalse(adapter_corrupt.is_active())

    def test_no_control_file_configured_allows_env_shadow_enabled(self):
        """Block S5: Absence of configured control file permits shadow when env=1."""
        adapter = ShadowEvidenceIntegrityGate(
            metadata_db_path=self.db_path,
            log_path=self.log_path,
            enabled=True,
            control_file_path=None
        )
        with patch.dict(os.environ, {"FLYING_RAG_SHADOW_EIG": "1"}):
            self.assertTrue(adapter.is_active())


if __name__ == "__main__":
    unittest.main()
