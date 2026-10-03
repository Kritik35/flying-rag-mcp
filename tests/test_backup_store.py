"""A snapshot can be taken, is verified, and brings the store back."""
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


class BackupStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.store, self.meta = base / "lancedb", base / "metadata.db"
        self.dest = base / "backups"
        cfg = base / "config.yaml"
        cfg.write_text(f"storage:\n  lancedb_path: '{self.store.as_posix()}'\n"
                       f"  metadata_db: '{self.meta.as_posix()}'\n", encoding="utf-8")
        self._env = mock.patch.dict(os.environ, {"FLYING_RAG_CONFIG": str(cfg)})
        self._env.start()
        from storage import metadata_db, vector_store
        self.db, self.vs = metadata_db, vector_store
        self.db.init_db(self.meta)
        self._add(r"C:\docs\a.pdf", 3)

    def tearDown(self):
        self._env.stop()
        self.vs._DB_CACHE.pop(str(self.store), None)
        self._tmp.cleanup()

    def _add(self, src, n):
        doc_id = hashlib.sha256(src.encode()).hexdigest()[:8]
        chunks = [Chunk(doc_id, f"{doc_id}_c_{i:04d}", f"t{i}", {"source_path": src})
                  for i in range(n)]
        self.vs.replace_document(self.store, doc_id, chunks,
                                 [Emb(c.chunk_id, [1.0] * DIM) for c in chunks], dim=DIM)
        self.db.commit_document(self.meta, src, file_name=Path(src).name, format="pdf",
                                sha256="s", created_at="", modified_at="", chunk_count=n,
                                status="indexed", dataset="project", parents={}, cache_items=[])

    def _run(self, *argv):
        from scripts import backup_store
        with redirect_stdout(io.StringIO()) as out:
            code = backup_store.main(list(argv))
        return code, out.getvalue()

    def test_backup_is_verified_and_restore_brings_the_store_back(self):
        code, out = self._run("backup", "--dest", str(self.dest), "--lock-wait", "5")
        self.assertEqual(code, 0, out)
        snap = next(self.dest.iterdir())

        self._add(r"C:\docs\b.pdf", 5)              # the store moves on
        self.vs._DB_CACHE.pop(str(self.store), None)

        from scripts import backup_store
        with mock.patch.object(backup_store, "_servers_running", return_value=[]):
            code, out = self._run("restore", "--from", str(snap), "--yes", "--lock-wait", "5")
        self.assertEqual(code, 0, out)

        from scripts.backup_store import _measure
        counts = _measure(self.store, self.meta)
        self.assertEqual(counts["files"], 1)
        self.assertEqual(sum(counts["tables"].values()), 3)
        set_aside = [p.name for p in self.store.parent.iterdir() if ".pre-restore-" in p.name]
        self.assertTrue(any(n.startswith("lancedb.pre-restore-") for n in set_aside))

    def test_restore_refuses_while_servers_hold_the_store(self):
        self._run("backup", "--dest", str(self.dest), "--lock-wait", "5")
        snap = next(self.dest.iterdir())
        from scripts import backup_store
        with mock.patch.object(backup_store, "_servers_running", return_value=["1: main.py"]):
            code, _ = self._run("restore", "--from", str(snap), "--yes")
        self.assertEqual(code, 2)

    def test_old_snapshots_are_rotated(self):
        import time
        for _ in range(3):
            self._run("backup", "--dest", str(self.dest), "--keep", "2", "--lock-wait", "5")
            time.sleep(1.1)  # snapshot names carry the second
        self.assertEqual(len(list(self.dest.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
