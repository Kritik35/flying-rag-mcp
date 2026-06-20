from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


OV2 = "\u041e\u04122"


class VisualScopeTests(unittest.TestCase):
    def test_filter_visual_hits_keeps_folder_matches(self):
        from storage.metadata_db import init_db
        from rag_server.tools import _filter_visual_hits

        hits = [
            {"source_path": f"C:\\Project\\{OV2}\\a.pdf", "file_name": "a.pdf"},
            {"source_path": r"C:\Project\EOM\b.pdf", "file_name": "b.pdf"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            filtered = _filter_visual_hits(hits, db_path, dataset=None, folder_filter=OV2)

        self.assertEqual([h["file_name"] for h in filtered], ["a.pdf"])

    def test_filter_visual_hits_keeps_dataset_matches_from_metadata(self):
        from storage.metadata_db import init_db, upsert_file
        from rag_server.tools import _filter_visual_hits

        project_path = r"C:\Project\OV2\a.pdf"
        norm_path = r"H:\NTD\SP7.pdf"
        hits = [
            {"source_path": project_path, "file_name": "a.pdf"},
            {"source_path": norm_path, "file_name": "SP7.pdf"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            upsert_file(db_path, project_path, "a.pdf", "pdf", "sha1", "2026-01-01", "2026-01-01", 1, dataset="project")
            upsert_file(db_path, norm_path, "SP7.pdf", "pdf", "sha2", "2026-01-01", "2026-01-01", 1, dataset="normative")

            filtered = _filter_visual_hits(hits, db_path, dataset="project", folder_filter=None)

        self.assertEqual([h["file_name"] for h in filtered], ["a.pdf"])

    def test_search_drawings_applies_routed_folder_scope(self):
        import rag_server.tools as tools
        from storage.metadata_db import init_db, upsert_file

        hits = [
            {"source_path": f"C:\\Project\\{OV2}\\a.pdf", "file_name": "a.pdf"},
            {"source_path": r"C:\Project\EOM\b.pdf", "file_name": "b.pdf"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            upsert_file(
                db_path, f"C:\\Project\\{OV2}\\a.pdf", "a.pdf", "pdf",
                "sha1", "2026-01-01", "2026-01-01", 1, dataset="project",
            )
            upsert_file(
                db_path, r"C:\Project\EOM\b.pdf", "b.pdf", "pdf",
                "sha2", "2026-01-01", "2026-01-01", 1, dataset="project",
            )
            Path(tmp, "lancedb").mkdir()
            with patch.object(tools, "_db_paths", return_value=(Path(tmp) / "lancedb", db_path)):
                with patch("embedder.colpali.is_enabled", return_value=True):
                    with patch("embedder.colpali.search_visual", return_value=hits):
                        out = tools.search_drawings(f"smoke ventilation {OV2}", top_k=5)

        self.assertTrue(out["enabled"])
        self.assertEqual([h["file_name"] for h in out["results"]], ["a.pdf"])
        self.assertEqual(out["scope"]["folder_filter"], OV2)


if __name__ == "__main__":
    unittest.main()
