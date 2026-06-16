from __future__ import annotations

import unittest

from storage.vector_store import build_search_result


class VectorStoreContextTests(unittest.TestCase):
    def test_build_search_result_keeps_child_text_when_parent_context_exists(self):
        row = {
            "chunk_id": "child-1",
            "parent_id": "parent-1",
            "doc_id": "doc-1",
            "text": "short child hit",
            "source_path": "C:/docs/sp7.pdf",
            "file_name": "sp7.pdf",
            "section": "",
            "_score": 0.75,
        }

        result = build_search_result(row, parent_text="long parent context")

        self.assertEqual(result["text"], "long parent context")
        self.assertEqual(result["child_text"], "short child hit")
        self.assertEqual(result["context_source"], "parent")
        self.assertEqual(result["context_chars"], len("long parent context"))

    def test_build_search_result_marks_child_context_when_parent_missing(self):
        row = {
            "chunk_id": "child-1",
            "doc_id": "doc-1",
            "text": "short child hit",
            "source_path": "C:/docs/sp7.pdf",
            "file_name": "sp7.pdf",
            "section": "",
            "_distance": 0.2,
        }

        result = build_search_result(row, parent_text=None)

        self.assertEqual(result["text"], "short child hit")
        self.assertEqual(result["child_text"], "short child hit")
        self.assertEqual(result["context_source"], "child")
        self.assertEqual(result["context_chars"], len("short child hit"))
        self.assertEqual(result["score"], 0.8)

    def test_build_search_result_trims_oversized_parent_context(self):
        row = {
            "chunk_id": "child-1",
            "parent_id": "parent-1",
            "doc_id": "doc-1",
            "text": "child",
            "source_path": "C:/docs/sp7.pdf",
            "file_name": "sp7.pdf",
            "section": "",
            "_score": 0.9,
        }

        result = build_search_result(row, parent_text="abcdef", max_context_chars=4)

        self.assertEqual(result["text"], "abcd")
        self.assertEqual(result["context_source"], "parent_truncated")
        self.assertEqual(result["context_chars"], 4)


if __name__ == "__main__":
    unittest.main()
