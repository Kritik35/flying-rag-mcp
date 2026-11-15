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
        # Retrieval returned a completely different parent_id
        retrieval = [
            {"parent_id": "different_doc_p_9999", "file_name": "СП 7.13130.docx", "score": 0.90}
        ]
        res = self.adapter.observe("СП 7.13130 пункт 6.4", retrieval_results=retrieval)
        self.assertIsNotNone(res)
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

        lines = self.log_path.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[-1])
        self.assertEqual(event["divergence"], "RETRIEVAL_PARENT_ID_MISMATCH")

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


if __name__ == "__main__":
    unittest.main()
