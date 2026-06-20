from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path


def _insert_rule_raw(db_path: Path, source_path: str, chunk_id: str, rule_text: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO engineering_rules
            (source_path, chunk_id, rule_text, subject, parameter, operator, value, unit, condition, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_path, chunk_id, rule_text, "s", None, None, None, None, None, "2026-01-01"),
        )
        conn.commit()
    finally:
        conn.close()


class RulesMaintenanceTests(unittest.TestCase):
    def test_save_engineering_rule_is_idempotent_for_exact_duplicate(self):
        from storage.metadata_db import init_db, save_engineering_rule

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)

            for _ in range(3):
                save_engineering_rule(db_path, "a.pdf", "chunk-1", "rule text", "s", None, None, None, None, None)

            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0], 1)
            finally:
                conn.close()

    def test_deduplicate_rules_dry_run_does_not_delete(self):
        from storage.metadata_db import init_db
        from storage.rules_maintenance import deduplicate_engineering_rules

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            for _ in range(3):
                _insert_rule_raw(db_path, "a.pdf", "chunk-1", "rule text")

            result = deduplicate_engineering_rules(db_path, apply=False)

            self.assertEqual(result["duplicate_groups"], 1)
            self.assertEqual(result["duplicate_rows"], 2)
            self.assertEqual(result["deleted_rows"], 0)
            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0], 3)
            finally:
                conn.close()

    def test_deduplicate_rules_apply_keeps_one_row(self):
        from storage.metadata_db import init_db
        from storage.rules_maintenance import deduplicate_engineering_rules

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            for _ in range(3):
                _insert_rule_raw(db_path, "a.pdf", "chunk-1", "rule text")
            _insert_rule_raw(db_path, "a.pdf", "chunk-2", "other rule")

            result = deduplicate_engineering_rules(db_path, apply=True)

            self.assertEqual(result["deleted_rows"], 2)
            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM engineering_rules").fetchone()[0], 2)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
