from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TableQueryTests(unittest.TestCase):
    def test_resolve_files_respects_dataset_filter_without_source_like(self):
        from storage.metadata_db import init_db, save_parent_chunk, upsert_file
        import rag_server.table_query as table_query

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            upsert_file(
                db_path, r"C:\Docs\Norm\spec.xlsx", "spec.xlsx", "xlsx",
                "sha1", "2026-01-01", "2026-01-01", 1, dataset="normative",
            )
            upsert_file(
                db_path, r"C:\Docs\Project\ov2.xlsx", "ov2.xlsx", "xlsx",
                "sha2", "2026-01-01", "2026-01-01", 1, dataset="project",
            )
            save_parent_chunk(db_path, "p-norm", r"C:\Docs\Norm\spec.xlsx", "параметр настройки 10 Па")
            save_parent_chunk(db_path, "p-proj", r"C:\Docs\Project\ov2.xlsx", "параметр настройки 20 Па")

            original_meta_db = table_query._meta_db
            try:
                table_query._meta_db = lambda: db_path
                files = table_query._resolve_files("параметр настройки", None, "project", 10)
            finally:
                table_query._meta_db = original_meta_db

        self.assertEqual(files, [r"C:\Docs\Project\ov2.xlsx"])

    def test_resolve_files_respects_dataset_filter_with_source_like(self):
        from storage.metadata_db import init_db, save_parent_chunk, upsert_file
        import rag_server.table_query as table_query

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            upsert_file(
                db_path, r"C:\Docs\Norm\OV2\spec.xlsx", "spec.xlsx", "xlsx",
                "sha1", "2026-01-01", "2026-01-01", 1, dataset="normative",
            )
            upsert_file(
                db_path, r"C:\Docs\Project\OV2\ov2.xlsx", "ov2.xlsx", "xlsx",
                "sha2", "2026-01-01", "2026-01-01", 1, dataset="project",
            )
            save_parent_chunk(db_path, "p-norm", r"C:\Docs\Norm\OV2\spec.xlsx", "параметр настройки 10 Па")
            save_parent_chunk(db_path, "p-proj", r"C:\Docs\Project\OV2\ov2.xlsx", "параметр настройки 20 Па")

            original_meta_db = table_query._meta_db
            try:
                table_query._meta_db = lambda: db_path
                files = table_query._resolve_files("параметр настройки", "OV2", "project", 10)
            finally:
                table_query._meta_db = original_meta_db

        self.assertEqual(files, [r"C:\Docs\Project\OV2\ov2.xlsx"])

    def test_resolve_files_prioritizes_subject_hits_with_source_like(self):
        from storage.metadata_db import init_db, save_parent_chunk, upsert_file
        import rag_server.table_query as table_query

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            irrelevant = r"C:\Docs\Project\OV2\01-general.xlsx"
            relevant = r"C:\Docs\Project\OV2\99-doreg.xlsx"
            upsert_file(
                db_path, irrelevant, "01-general.xlsx", "xlsx",
                "sha1", "2026-01-01", "2026-01-01", 1, dataset="project",
            )
            upsert_file(
                db_path, relevant, "99-doreg.xlsx", "xlsx",
                "sha2", "2026-01-01", "2026-01-01", 1, dataset="project",
            )
            save_parent_chunk(db_path, "p1", irrelevant, "общие данные")
            save_parent_chunk(db_path, "p2", relevant, "параметр настройки 20 Па")

            original_meta_db = table_query._meta_db
            try:
                table_query._meta_db = lambda: db_path
                files = table_query._resolve_files("параметр настройки", "OV2", "project", 1)
            finally:
                table_query._meta_db = original_meta_db

        self.assertEqual(files, [relevant])


if __name__ == "__main__":
    unittest.main()
