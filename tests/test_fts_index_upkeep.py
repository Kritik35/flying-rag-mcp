"""The FTS index is kept up to date, not rebuilt, and old ones do not pile up.

Every server start and every watcher run ended in a full FTS rebuild over the
whole store (1.4 million rows), even for one new chunk. `replace=True` writes
a new index beside the old, and LanceDB's version cleanup prunes manifests but
leaves the replaced index directories on disk: by 2026-10-08 the store held
3.97 GB of data, 0.32 GB of live indices and 70 GB of dead ones, growing
about 30 GB a day.
"""
from __future__ import annotations

import hashlib
import math
import os
import tempfile
import time
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

DIM = 16


def _vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in str(text or "").casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vec[int.from_bytes(digest[:4], "big") % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _add(lance_path: Path, key: str, text: str) -> None:
    from chunker.semantic import Chunk
    from embedder.batcher import EmbeddingResult
    from storage.vector_store import upsert_chunks

    chunk_id = f"doc{key}_c0"
    upsert_chunks(lance_path, [Chunk(
        doc_id=f"doc{key}", chunk_id=chunk_id, text=text,
        metadata={"source_path": rf"C:\corpus\{key}.docx", "file_name": f"{key}.docx",
                  "namespace": "normative"},
    )], [EmbeddingResult(chunk_id=chunk_id, embedding=_vector(text))], dim=DIM)


class FtsUpkeepTests(unittest.TestCase):
    def setUp(self):
        from storage.vector_store import ensure_fts_index

        self.tmp = tempfile.TemporaryDirectory()
        self.lance = Path(self.tmp.name) / "lancedb"
        for i in range(30):
            _add(self.lance, f"k{i}", f"Клапан противопожарный номер {i} нормально открытый")
        self.assertTrue(ensure_fts_index(self.lance, dim=DIM))
        self.indices = self.lance / f"documents_{DIM}.lance" / "_indices"

    def tearDown(self):
        self.tmp.cleanup()

    def _dirs(self) -> set[str]:
        return {p.name for p in self.indices.iterdir()}

    def _fts(self, query: str) -> set[str]:
        import lancedb

        table = lancedb.connect(str(self.lance)).open_table(f"documents_{DIM}")
        return {r["chunk_id"] for r in table.search(query, query_type="fts").limit(50).to_list()}

    def test_a_server_start_does_not_rebuild_an_existing_index(self):
        from storage.vector_store import ensure_fts_index

        before = self._dirs()
        self.assertTrue(ensure_fts_index(self.lance, dim=DIM))
        self.assertEqual(self._dirs(), before)

    def test_new_chunks_are_added_to_the_index_not_rebuilt_into_it(self):
        import lancedb
        from storage.vector_store import refresh_indices

        _add(self.lance, "new", "Шумоглушитель пластинчатый на приточном воздуховоде")
        refresh_indices(self.lance, dim=DIM)

        table = lancedb.connect(str(self.lance)).open_table(f"documents_{DIM}")
        self.assertEqual(table.index_stats("text_idx").num_unindexed_rows, 0)
        self.assertIn("docnew_c0", self._fts("шумоглушители"))
        self.assertIn("dock3_c0", self._fts("клапаны"))

    def test_replaced_indices_are_removed_once_no_version_needs_them(self):
        from storage.vector_store import ensure_fts_index, refresh_indices

        for _ in range(3):
            ensure_fts_index(self.lance, dim=DIM, rebuild=True)
        self.assertGreaterEqual(len(self._dirs()), 4)
        time.sleep(1.1)
        report = refresh_indices(self.lance, dim=DIM, keep=timedelta(0),
                                 orphan_min_age=timedelta(0))

        self.assertGreaterEqual(report["orphans_removed"], 3)
        self.assertLessEqual(len(self._dirs()), 2)
        self.assertIn("dock3_c0", self._fts("клапаны"))

    def test_a_fresh_unreferenced_directory_is_left_alone(self):
        """It may belong to a write that has not committed its manifest yet."""
        from storage.vector_store import remove_orphan_indices

        pending = self.indices / str(uuid.uuid4())
        pending.mkdir()
        (pending / "part_0_docs.lance").write_bytes(b"x")
        removed = remove_orphan_indices(self.lance / f"documents_{DIM}.lance",
                                        min_age=timedelta(hours=1))
        self.assertEqual(removed["removed"], 0)
        self.assertTrue(pending.exists())

        old = time.time() - 7200
        os.utime(pending, (old, old))
        removed = remove_orphan_indices(self.lance / f"documents_{DIM}.lance",
                                        min_age=timedelta(hours=1))
        self.assertEqual(removed["removed"], 1)
        self.assertFalse(pending.exists())


if __name__ == "__main__":
    unittest.main()
