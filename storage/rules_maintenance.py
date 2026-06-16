from __future__ import annotations

import sqlite3
from pathlib import Path


def deduplicate_engineering_rules(db_path: Path, apply: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        duplicate_groups = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT source_path, chunk_id, rule_text, COUNT(*) n
                FROM engineering_rules
                GROUP BY source_path, chunk_id, rule_text
                HAVING n > 1
            )
            """
        ).fetchone()[0]
        duplicate_rows = conn.execute(
            """
            SELECT COALESCE(SUM(n - 1), 0) FROM (
                SELECT COUNT(*) n
                FROM engineering_rules
                GROUP BY source_path, chunk_id, rule_text
                HAVING n > 1
            )
            """
        ).fetchone()[0]

        deleted_rows = 0
        if apply and duplicate_rows:
            cur = conn.execute(
                """
                DELETE FROM engineering_rules
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM engineering_rules
                    GROUP BY source_path, chunk_id, rule_text
                )
                """
            )
            deleted_rows = cur.rowcount
            conn.commit()
    finally:
        conn.close()

    return {
        "duplicate_groups": int(duplicate_groups or 0),
        "duplicate_rows": int(duplicate_rows or 0),
        "deleted_rows": int(deleted_rows or 0),
        "applied": bool(apply),
    }
