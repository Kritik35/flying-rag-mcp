from __future__ import annotations

import hashlib
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ProductionReadinessTests(unittest.TestCase):
    def _call_reindex_with_cfg(self, tools, root, target, watched_folders):
        cfg = {
            "watched_folders": watched_folders,
            "storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"},
        }
        with patch.object(tools, "ROOT", root), \
                patch.object(tools, "_cfg", return_value=cfg), \
                patch("subprocess.Popen") as popen, \
                patch("storage.metadata_db.create_reindex_job"):
            result = tools.reindex_path(str(target))
        return result, popen

    def test_reindex_path_rejects_file_valued_watched_root(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched_file = root / "watched.txt"
            watched_file.write_text("fixture", encoding="utf-8")

            result, popen = self._call_reindex_with_cfg(
                tools, root, watched_file, [str(watched_file)]
            )

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_rejects_malformed_watched_folders(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "fixture.txt"
            target.write_text("fixture", encoding="utf-8")

            for malformed in (None, "not-a-list", [None], [object()]):
                with self.subTest(watched_folders=repr(malformed)):
                    result, popen = self._call_reindex_with_cfg(
                        tools, root, target, malformed
                    )
                    self.assertEqual(
                        result, {"status": "error", "message": "Path is not allowed."}
                    )
                    popen.assert_not_called()

    def test_reindex_path_rejects_relative_watched_root(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "fixture.txt"
            target.write_text("fixture", encoding="utf-8")

            result, popen = self._call_reindex_with_cfg(tools, root, target, ["."])

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_rejects_nonexistent_watched_root(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "fixture.txt"
            target.write_text("fixture", encoding="utf-8")

            result, popen = self._call_reindex_with_cfg(
                tools, root, target, [str(root / "missing")]
            )

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_rejects_sibling_prefix(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "docs"
            sibling = root / "docs-private" / "fixture.txt"
            watched.mkdir()
            sibling.parent.mkdir()
            sibling.write_text("fixture", encoding="utf-8")

            result, popen = self._call_reindex_with_cfg(
                tools, root, sibling, [str(watched)]
            )

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_rejects_symlink_escape(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "watched"
            outside = root / "outside"
            watched.mkdir()
            outside.mkdir()
            target = outside / "fixture.txt"
            target.write_text("fixture", encoding="utf-8")
            link = watched / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")

            result, popen = self._call_reindex_with_cfg(
                tools, root, link / target.name, [str(watched)]
            )

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_rejects_existing_path_outside_watched_folders(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "watched"
            outside = root / "outside.txt"
            watched.mkdir()
            outside.write_text("fixture", encoding="utf-8")
            cfg = {
                "watched_folders": [str(watched)],
                "storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"},
            }

            with patch.object(tools, "ROOT", root), \
                    patch.object(tools, "_cfg", return_value=cfg), \
                    patch("subprocess.Popen") as popen, \
                    patch("storage.metadata_db.create_reindex_job"):
                result = tools.reindex_path(str(outside))

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_rejects_traversal_outside_watched_folder(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "watched"
            outside = root / "outside.txt"
            watched.mkdir()
            outside.write_text("fixture", encoding="utf-8")
            traversal = watched / ".." / "outside.txt"
            cfg = {
                "watched_folders": [str(watched)],
                "storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"},
            }

            with patch.object(tools, "ROOT", root), \
                    patch.object(tools, "_cfg", return_value=cfg), \
                    patch("subprocess.Popen") as popen, \
                    patch("storage.metadata_db.create_reindex_job"):
                result = tools.reindex_path(str(traversal))

            self.assertEqual(result, {"status": "error", "message": "Path is not allowed."})
            popen.assert_not_called()

    def test_reindex_path_allows_target_when_other_watched_root_is_unavailable(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "watched"
            target = watched / "fixture.txt"
            watched.mkdir()
            target.write_text("fixture", encoding="utf-8")
            unavailable = root / "unmounted-drive"
            process = unittest.mock.Mock(pid=123)

            with patch.object(tools, "ROOT", root), \
                    patch.object(tools, "_cfg", return_value={
                        "watched_folders": [str(unavailable), str(watched)],
                        "storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"},
                    }), \
                    patch("subprocess.Popen", return_value=process) as popen, \
                    patch("storage.metadata_db.create_reindex_job"):
                result = tools.reindex_path(str(target))

            self.assertEqual(result["status"], "started")
            popen.assert_called_once()

    def test_reindex_path_starts_for_descendant_of_watched_folder(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "watched"
            target = watched / "nested" / "fixture.txt"
            target.parent.mkdir(parents=True)
            target.write_text("fixture", encoding="utf-8")
            cfg = {
                "watched_folders": [str(watched)],
                "storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"},
            }
            process = unittest.mock.Mock(pid=123)

            with patch.object(tools, "ROOT", root), \
                    patch.object(tools, "_cfg", return_value=cfg), \
                    patch("subprocess.Popen", return_value=process) as popen, \
                    patch("storage.metadata_db.create_reindex_job"):
                result = tools.reindex_path(str(target))

            self.assertEqual(result["status"], "started")
            self.assertEqual(Path(result["path"]), target.resolve())
            popen.assert_called_once()

    def test_metadata_db_enables_wal_and_reindex_jobs(self):
        from storage.metadata_db import (
            _connect,
            create_reindex_job,
            get_reindex_job,
            init_db,
            list_reindex_jobs,
            update_reindex_job,
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)

            with _connect(db_path) as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

            self.assertEqual(journal_mode.lower(), "wal")
            self.assertGreaterEqual(busy_timeout, 30000)

            create_reindex_job(
                db_path,
                job_id="job-a",
                path=r"C:\docs",
                pid=123,
                force=True,
                use_cache=False,
                log_path=r"C:\logs\job-a.log",
            )
            update_reindex_job(db_path, "job-a", "completed", pid=456)

            job = get_reindex_job(db_path, "job-a")
            self.assertIsNotNone(job)
            self.assertEqual(job["path"], r"C:\docs")
            self.assertEqual(job["pid"], 456)
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["force"], 1)
            self.assertEqual(job["use_cache"], 0)
            self.assertEqual(job["log_path"], r"C:\logs\job-a.log")
            self.assertEqual([j["job_id"] for j in list_reindex_jobs(db_path)], ["job-a"])

    def test_delete_file_removes_metadata_and_doc_edges(self):
        from storage.metadata_db import (
            delete_file,
            init_db,
            save_engineering_rule,
            save_parent_chunk,
            upsert_file,
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            source_path = r"C:\docs\a.docx"
            doc_id = hashlib.sha256(source_path.encode()).hexdigest()[:8]
            init_db(db_path)
            upsert_file(db_path, source_path, "a.docx", "docx", "sha", "c", "m", 1)
            save_parent_chunk(db_path, "p1", source_path, "parent")
            save_engineering_rule(db_path, source_path, "c1", "rule", None, None, None, None, None, None)

            with open(db_path, "rb"):
                pass
            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS doc_edges (doc_id_a TEXT, doc_id_b TEXT, similarity REAL)"
                )
                conn.execute("INSERT INTO doc_edges VALUES (?, ?, ?)", (doc_id, "other", 0.5))
                conn.execute("INSERT INTO doc_edges VALUES (?, ?, ?)", ("other", doc_id, 0.5))
                conn.commit()
            finally:
                conn.close()

            delete_file(db_path, source_path)

            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM parent_chunks").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM doc_edges").fetchone()[0], 0)
            finally:
                conn.close()

    def test_reindex_tools_expose_status_and_force_command(self):
        from rag_server.tools import build_reindex_command, get_tool_definitions

        command = build_reindex_command(
            python_exe="python.exe",
            indexer_script="indexer.py",
            target=Path(r"C:\docs"),
            force=True,
            use_cache=False,
        )

        self.assertEqual(command, ["python.exe", "indexer.py", "--force", "--no-cache", r"C:\docs"])
        self.assertIn("reindex_status", {tool["name"] for tool in get_tool_definitions()})
        search_tool = next(tool for tool in get_tool_definitions() if tool["name"] == "search_documents")
        self.assertIn("use_cache", search_tool["inputSchema"]["properties"])

    def test_search_scope_key_includes_embedding_model(self):
        from rag_server.tools import build_search_scope_key

        qwen_scope = build_search_scope_key(
            dataset="normative",
            folder_filter="GOST",
            alpha=0.7,
            model_name="Qwen3-Embedding-0.6B-GGUF",
        )
        bge_scope = build_search_scope_key(
            dataset="normative",
            folder_filter="GOST",
            alpha=0.7,
            model_name="bge-m3-GGUF",
        )

        self.assertNotEqual(qwen_scope, bge_scope)
        self.assertIn("Qwen3-Embedding-0.6B-GGUF", qwen_scope)

    def test_vector_store_delete_source_escapes_source_path(self):
        import storage.vector_store as vector_store

        calls = []

        class FakeTable:
            def delete(self, predicate):
                calls.append(predicate)

        original_get_table = vector_store._get_table
        try:
            vector_store._get_table = lambda _db_path, _dim=None: (None, FakeTable())
            self.assertEqual(vector_store.delete_source(Path("lancedb"), "C:\\docs\\O'Hara.docx", dim=1024), 1)
        finally:
            vector_store._get_table = original_get_table

        self.assertEqual(calls, ["source_path = 'C:\\docs\\O''Hara.docx'"])

    def test_legacy_mcp_files_are_removed_to_avoid_shadowing_sdk(self):
        self.assertFalse(Path("mcp/tools.py").exists())
        self.assertFalse(Path("mcp/server.py").exists())


if __name__ == "__main__":
    unittest.main()
