"""The recovery sweep removes what a vanished document left, and nothing else.

A document that lost its metadata but whose file is still on disk must stay
searchable until it is reindexed; only remains of files that no longer exist
are deleted.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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


class StoreRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.store, self.meta = base / "lancedb", base / "metadata.db"
        cfg = base / "config.yaml"
        cfg.write_text(f"storage:\n  lancedb_path: '{self.store.as_posix()}'\n"
                       f"  metadata_db: '{self.meta.as_posix()}'\n", encoding="utf-8")
        self._env = mock.patch.dict(os.environ, {"FLYING_RAG_CONFIG": str(cfg)})
        self._env.start()
        from storage import metadata_db, vector_store
        self.db, self.vs = metadata_db, vector_store
        self.db.init_db(self.meta)

        self.kept = base / "kept.pdf"          # indexed normally
        self.lost = base / "lost.pdf"          # metadata lost, file still there
        self.gone = str(base / "gone.pdf")     # file deleted, remains in the store
        self.kept.write_bytes(b"k")
        self.lost.write_bytes(b"l")
        for src in (str(self.kept), str(self.lost), self.gone):
            self._index(src)
        self._commit(str(self.kept))

    def tearDown(self):
        self._env.stop()
        self.vs._DB_CACHE.pop(str(self.store), None)
        self._tmp.cleanup()

    def _index(self, src):
        doc_id = hashlib.sha256(src.encode()).hexdigest()[:8]
        chunks = [Chunk(doc_id, f"{doc_id}_c_0000", "text", {"source_path": src,
                                                             "parent_id": f"{doc_id}_p_0000"})]
        self.vs.replace_document(self.store, doc_id, chunks, [Emb(chunks[0].chunk_id, [1.0] * DIM)],
                                 dim=DIM)
        with self.db._connect(self.meta) as conn:
            conn.execute("INSERT INTO parent_chunks (parent_id, source_path, parent_text, created_at) "
                         "VALUES (?, ?, 'p', '')", (f"{doc_id}_p_0000", src))

    def _commit(self, src):
        self.db.commit_document(self.meta, src, file_name=Path(src).name, format="pdf",
                                sha256="s", created_at="", modified_at="", chunk_count=1,
                                status="indexed", dataset="project",
                                parents={hashlib.sha256(src.encode()).hexdigest()[:8] + "_p_0000": "p"},
                                cache_items=[])

    def _sources(self):
        _, table = self.vs._get_table(self.store, DIM)
        return sorted(set(table.search().select(["source_path"]).limit(100).to_arrow()
                          .column("source_path").to_pylist()))

    def test_dry_run_changes_nothing(self):
        from scripts import store_recovery

        with redirect_stdout(io.StringIO()) as out:
            store_recovery.main([])
        self.assertIn("сухой прогон", out.getvalue())
        self.assertEqual(len(self._sources()), 3)

    def test_apply_removes_only_remains_of_vanished_files(self):
        from scripts import store_recovery

        with redirect_stdout(io.StringIO()):
            self.assertEqual(store_recovery.main(["--apply", "--lock-wait", "5"]), 0)

        self.assertEqual(self._sources(), sorted([str(self.kept), str(self.lost)]))
        with self.db._connect(self.meta) as conn:
            parents = {r[0] for r in conn.execute("SELECT source_path FROM parent_chunks")}
        self.assertEqual(parents, {str(self.kept), str(self.lost)})


if __name__ == "__main__":
    unittest.main()
