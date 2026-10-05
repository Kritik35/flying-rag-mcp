"""A completed job is not reported as an error.

Jobs finished before 077c5c2 kept their "[indexer] DONE …" line in the error
column, and the MCP output turns any non-empty error into internal_error: ten
successful jobs on the live store read as failures.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ReindexStatusSummaryTests(unittest.TestCase):
    def test_done_line_of_a_completed_job_becomes_its_summary(self):
        from rag_server import tools
        from storage.metadata_db import create_reindex_job, init_db, update_reindex_job

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "metadata.db"
            init_db(db)
            create_reindex_job(db, job_id="old", path=r"C:\docs\a.pdf", pid=1, force=False,
                               use_cache=True, log_path="a.log")
            update_reindex_job(db, "old", "completed",
                               error="[indexer] DONE chunks=5 skipped=0 errors=0 time=3s")
            create_reindex_job(db, job_id="bad", path=r"C:\docs\b.pdf", pid=2, force=False,
                               use_cache=True, log_path="b.log")
            update_reindex_job(db, "bad", "failed", error="process finished without DONE marker")

            with patch.object(tools, "_db_paths", return_value=(Path(tmp) / "lancedb", db)):
                jobs = {j["job_id"]: j for j in tools.reindex_status()["jobs"]}

        self.assertIsNone(jobs["old"]["error"])
        self.assertIn("DONE chunks=5", jobs["old"]["summary"])
        self.assertEqual(jobs["bad"]["error"], "process finished without DONE marker")


if __name__ == "__main__":
    unittest.main()
