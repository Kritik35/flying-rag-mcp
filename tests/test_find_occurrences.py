"""find_occurrences lists every place an identifier occurs, with the count."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DIM = 8


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Emb:
    chunk_id: str
    embedding: list


class FindOccurrencesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "lancedb"
        from storage import vector_store
        self.vs = vector_store
        self._add(r"C:\docs\ОВ2.pdf", ["Клапан КПУ-1 в системе П1-TRF-01-01, этаж 2.",
                                       "Система п1-trf-01-01 обслуживает коридор.",
                                       "Соседняя система П1-TRF-01-012 — другая."])
        self._add(r"C:\docs\АР.pdf", ["План этажа, ось А, П1-TRF-01-01 в шахте."] +
                  [f"Абзац {i} без шифра." for i in range(3)])

    def tearDown(self):
        self.vs._DB_CACHE.pop(str(self.store), None)
        self._tmp.cleanup()

    def _add(self, src, texts):
        doc_id = hashlib.sha256(src.encode()).hexdigest()[:8]
        chunks = [Chunk(doc_id, f"{doc_id}_c_{i:04d}", t,
                        {"source_path": src, "file_name": Path(src).name})
                  for i, t in enumerate(texts)]
        self.vs.replace_document(self.store, doc_id, chunks,
                                 [Emb(c.chunk_id, [1.0] * DIM) for c in chunks], dim=DIM)

    def _call(self, **kw):
        from rag_server import tools
        with mock.patch.object(tools, "_db_paths", return_value=(self.store, Path("m.db"))), \
                mock.patch("storage.vector_store._DEFAULT_PROVIDER.get_dimension",
                           return_value=DIM):
            return tools.find_occurrences(**kw)

    def test_every_whole_occurrence_is_counted_case_insensitively(self):
        result = self._call(text="П1-TRF-01-01")
        self.assertEqual(result["total_matches"], 3)
        self.assertEqual(result["documents"], {"ОВ2.pdf": 2, "АР.pdf": 1})
        self.assertTrue(all("012" not in m["snippet"] for m in result["matches"]))

    def test_pages_continue_without_gaps(self):
        first = self._call(text="П1-TRF-01-01", limit=2)
        self.assertEqual((first["returned"], first["next_offset"]), (2, 2))
        rest = self._call(text="П1-TRF-01-01", limit=2, offset=2)
        self.assertEqual(rest["returned"], 1)
        self.assertNotIn("next_offset", rest)
        ids = [m["chunk_id"] for m in first["matches"] + rest["matches"]]
        self.assertEqual(len(set(ids)), 3)

    def test_too_short_a_needle_is_refused(self):
        self.assertIn("error", self._call(text="П1"))


if __name__ == "__main__":
    unittest.main()
