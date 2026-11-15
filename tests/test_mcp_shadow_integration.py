"""
tests/test_mcp_shadow_integration.py

Integration test for Shadow Evidence Integrity Gate via MCP dispatch path (Blocker 8):
1. Verifies byte-for-byte serialized JSON response equality with shadow enabled vs disabled.
2. Verifies passive background logging with zero production payload mutation.
3. Verifies complete fail-open isolation when shadow adapter encounters errors.
"""
from __future__ import annotations
import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import rag_server.server as server_module
from rag_server.shadow_eig import ShadowEvidenceIntegrityGate


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


if __name__ == "__main__":
    unittest.main()
