from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class McpStructuredValuesTests(unittest.TestCase):
    def test_extract_structured_values_tool_reads_parent_chunks(self):
        from storage.metadata_db import init_db, save_parent_chunk
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            save_parent_chunk(
                db_path,
                "parent-1",
                r"C:\Project\OV2\sheet.pdf",
                """
                SYS-AUX-01-01
                Параметр настройки
                400 Па
                """,
            )

            original_db_paths = tools._db_paths
            try:
                tools._db_paths = lambda: (Path(tmp) / "lancedb", db_path)
                result = tools.extract_structured_values(
                    label="Параметр настройки",
                    source_like="OV2",
                    limit=10,
                    max_rows=5,
                )
            finally:
                tools._db_paths = original_db_paths

        self.assertEqual(result["summary"]["total_rows"], 1)
        self.assertEqual(result["rows"][0]["record"], "SYS-AUX-01-01")
        self.assertEqual(result["rows"][0]["value"], 400.0)
        self.assertEqual(result["rows"][0]["unit"], "Па")

    def test_lowercase_cyrillic_label_matches_capitalized_text(self):
        # Regression: SQLite LIKE is not case-insensitive for Cyrillic, so a
        # lowercase label must still match capitalized corpus text.
        from storage.metadata_db import init_db, save_parent_chunk
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            save_parent_chunk(
                db_path, "p1", r"C:\Project\OV\s.pdf",
                "SYS-AUX-01-01\nПараметр настройки\n400 Па\n",  # capitalized in corpus
            )
            original = tools._db_paths
            try:
                tools._db_paths = lambda: (Path(tmp) / "lancedb", db_path)
                result = tools.extract_structured_values(label="параметр настройки")  # lowercase
            finally:
                tools._db_paths = original

        self.assertEqual(result["summary"]["total_rows"], 1)
        self.assertEqual(result["rows"][0]["value"], 400.0)

    def test_tool_definitions_include_structured_extraction(self):
        from rag_server.tools import get_tool_definitions

        tools = {tool["name"]: tool for tool in get_tool_definitions()}

        self.assertIn("extract_structured_values", tools)
        schema = tools["extract_structured_values"]["inputSchema"]["properties"]
        self.assertIn("label", schema)
        self.assertIn("source_like", schema)

    def test_every_advertised_tool_is_routed_by_dispatch(self):
        # Guards against advertising a tool that the server can't actually call.
        from rag_server.tools import get_tool_definitions
        from rag_server.server import _dispatch

        for tool in get_tool_definitions():
            name = tool["name"]
            with self.subTest(tool=name):
                # Missing required args raise inside the tool (KeyError/etc.),
                # but the dispatcher must NOT return "Unknown tool".
                try:
                    result = _dispatch(name, {})
                except Exception:
                    continue  # routed, failed later on missing args — acceptable here
                if isinstance(result, dict):
                    self.assertNotEqual(
                        result.get("error", ""), f"Unknown tool: {name}",
                        f"{name} is advertised but not wired in _dispatch",
                    )

    def test_dispatch_routes_structured_extraction(self):
        from storage.metadata_db import init_db, save_parent_chunk
        import rag_server.tools as tools
        from rag_server.server import _dispatch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            init_db(db_path)
            save_parent_chunk(
                db_path, "p1", r"C:\Project\OV2\s.pdf",
                "SYS-AUX-01-01\nПараметр настройки\n400 Па\n",
            )
            original = tools._db_paths
            try:
                tools._db_paths = lambda: (Path(tmp) / "lancedb", db_path)
                result = _dispatch(
                    "extract_structured_values",
                    {"label": "Параметр настройки", "source_like": "OV2"},
                )
            finally:
                tools._db_paths = original

        self.assertEqual(result["summary"]["total_rows"], 1)
        self.assertEqual(result["rows"][0]["value"], 400.0)


if __name__ == "__main__":
    unittest.main()
