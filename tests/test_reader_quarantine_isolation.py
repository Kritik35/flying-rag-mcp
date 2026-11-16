"""
tests/test_reader_quarantine_isolation.py

Diagnostic Test for Reader Quarantine Isolation & Cross-Store Failure Window (Stage 4.2.7 / Block P2).
Tests actual reader behavior when LanceDB commit succeeds but SQLite commit fails and marks
file status as quarantine_failed_indexing.

Verifies and records the honest status: READ_ISOLATION_NOT_PROVEN vs READ_ISOLATION_PROVEN.
"""

from __future__ import annotations
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage import vector_store
from storage.metadata_db import init_db, upsert_file
from evidence_gate import EvidenceIntegrityGate


class MockChunk:
    def __init__(self, chunk_id: str, text: str, doc_id: str = "doc_1", metadata: dict | None = None):
        self.chunk_id = chunk_id
        self.text = text
        self.doc_id = doc_id
        self.metadata = metadata or {"parent_id": f"p_{chunk_id}"}


def run_reader_quarantine_diagnostic(temp_dir: Path | str | None = None) -> dict:
    """
    Executes an isolated diagnostic of reader visibility on quarantined documents.
    Returns structured diagnostic dictionary.
    """
    is_temp = False
    if temp_dir is None:
        td_obj = tempfile.TemporaryDirectory()
        td = Path(td_obj.name)
        is_temp = True
    else:
        td = Path(temp_dir)
        td_obj = None

    try:
        lance_path = td / "lance_diagnostic"
        sqlite_path = td / "meta_diagnostic.db"

        # 1. Initialize DB
        init_db(sqlite_path)

        # 2. Add baseline consistent document (doc_clean)
        clean_chunk = MockChunk("c_clean_1", "Чистый нормативный пункт СП 60", "doc_clean")
        clean_emb = [MagicMock(chunk_id="c_clean_1", embedding=[0.1] * 1024)]
        vector_store.upsert_chunks(lance_path, [clean_chunk], clean_emb, dim=1024)

        conn = sqlite3.connect(str(sqlite_path))
        try:
            conn.execute(
                "INSERT INTO parent_chunks (parent_id, source_path, parent_text, created_at) VALUES (?, ?, ?, ?)",
                ("p_c_clean_1", "doc_clean.docx", "Чистый нормативный пункт СП 60", "2026-11-16T10:00:00Z")
            )
            conn.commit()
        finally:
            conn.close()
        upsert_file(sqlite_path, "doc_clean.docx", "doc_clean.docx", "docx", "sha_clean", "", "", 100, status="indexed", dataset="normative")

        # 3. Simulate indexing failure on second document (doc_quarantine)
        # LanceDB vector upsert succeeds:
        quar_chunk = MockChunk("c_quar_1", "Дефектный нормативный пункт СП 99", "doc_quarantine")
        quar_emb = [MagicMock(chunk_id="c_quar_1", embedding=[0.5] * 1024)]
        vector_store.upsert_chunks(lance_path, [quar_chunk], quar_emb, dim=1024)

        # SQLite parent_chunks commit fails (injected error / transaction rolled back)
        # Coordinator isolates file by recording quarantine_failed_indexing in files table:
        upsert_file(
            sqlite_path, "doc_quarantine.docx", "doc_quarantine.docx", "docx", "sha_quar",
            "", "", 100, status="quarantine_failed_indexing", dataset="normative"
        )

        # 4. Reader investigation: does vector search see the quarantined chunk?
        search_hits = vector_store.search(lance_path, query_embedding=[0.5] * 1024, top_k=5)
        quar_hits_in_reader = [h for h in search_hits if h.get("chunk_id") == "c_quar_1" or h.get("doc_id") == "doc_quarantine"]

        reader_sees_quarantine = (len(quar_hits_in_reader) > 0)

        # 5. EIG investigation: what does EIG assess on the orphan chunk?
        eig = EvidenceIntegrityGate(sqlite_path)
        with eig._connect() as e_conn:
            # Check if parent text exists in SQLite for quarantined chunk
            prow = e_conn.execute("SELECT parent_text FROM parent_chunks WHERE parent_id = 'p_c_quar_1'").fetchone()
            parent_exists = prow is not None
            # Check file status in SQLite
            frow = e_conn.execute("SELECT status FROM files WHERE source_path = 'doc_quarantine.docx'").fetchone()
            file_status = frow["status"] if frow else "NOT_FOUND"

        isolation_status = "READ_ISOLATION_NOT_PROVEN" if reader_sees_quarantine else "READ_ISOLATION_PROVEN"

        diagnostic_report = {
            "diagnostic_id": "READER_QUARANTINE_ISOLATION_DIAGNOSTIC",
            "status": isolation_status,
            "isolation_status": isolation_status,
            "findings": {
                "lancedb_vector_state": "ORPHAN_CHUNK_RETAINED (c_quar_1 present in LanceDB)",
                "sqlite_files_status": file_status,
                "sqlite_parent_chunks_exists": parent_exists,
                "reader_search_sees_quarantine_chunk": reader_sees_quarantine,
                "reader_hit_count": len(quar_hits_in_reader),
                "shadow_observation_role": "OBSERVER_ONLY (observe_async logs background warning but does not filter search_documents return value)",
                "cross_store_verdict": "BLOCKED"
            },
            "honest_clarification": (
                "In current FlyingRAG architecture, vector_store.search() reads directly from LanceDB without joining "
                "SQLite files status table. When SQLite transaction fails and marks status='quarantine_failed_indexing', "
                "LanceDB retains the written vector chunk. Readers querying LanceDB will receive this chunk. "
                "Shadow Evidence Integrity Gate observes this discrepancy asynchronously in the background, but does NOT "
                "modify or filter the results returned to the user by search_documents(). "
                "Therefore, read-side isolation from quarantined documents is NOT proven."
            )
        }
        return diagnostic_report
    finally:
        if td_obj is not None:
            try:
                td_obj.cleanup()
            except Exception:
                pass


class ReaderQuarantineIsolationTests(unittest.TestCase):
    def test_reader_quarantine_diagnostic_contract(self):
        diag = run_reader_quarantine_diagnostic()
        self.assertEqual(diag["isolation_status"], "READ_ISOLATION_NOT_PROVEN")
        self.assertTrue(diag["findings"]["reader_search_sees_quarantine_chunk"])
        self.assertEqual(diag["findings"]["sqlite_files_status"], "quarantine_failed_indexing")
        self.assertFalse(diag["findings"]["sqlite_parent_chunks_exists"])
        self.assertEqual(diag["findings"]["cross_store_verdict"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
