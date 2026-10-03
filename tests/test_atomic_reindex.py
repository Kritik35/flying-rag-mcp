"""Reindexing a document must not leave half of it behind.

The indexer deleted a document's metadata before parsing and embedding it —
hours, for a large PDF — and replaced its vectors with a delete followed by an
add. A killed process, a sleeping laptop or a lost embedding server left parent
chunks without a file record, vectors without metadata, or nothing at all, and
each of these had to be cleaned up by hand.
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

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


def _doc(source: str, n: int, tag: str):
    doc_id = hashlib.sha256(source.encode()).hexdigest()[:8]
    chunks = [Chunk(doc_id, f"{doc_id}_c_{i:04d}", f"{tag} text {i}",
                    {"source_path": source, "file_name": Path(source).name,
                     "parent_id": f"{doc_id}_p_0000"}) for i in range(n)]
    embs = [Emb(c.chunk_id, [float(i + 1)] * DIM) for i, c in enumerate(chunks)]
    return doc_id, chunks, embs


class ReplaceDocumentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "lancedb"
        from storage import vector_store
        self.vs = vector_store

    def tearDown(self):
        self.vs._DB_CACHE.pop(str(self.store), None)
        self._tmp.cleanup()

    def _rows(self, doc_id):
        _, table = self.vs._get_table(self.store, DIM)
        return table.search().where(f"doc_id = '{doc_id}'").limit(1000).to_list()

    def test_a_document_is_replaced_in_one_commit(self):
        a_id, a1, a1e = _doc(r"C:\docs\a.pdf", 3, "old")
        b_id, b, be = _doc(r"C:\docs\b.pdf", 2, "other")
        self.vs.replace_document(self.store, a_id, a1, a1e, dim=DIM)
        self.vs.replace_document(self.store, b_id, b, be, dim=DIM)
        _, table = self.vs._get_table(self.store, DIM)
        before = table.version

        _, a2, a2e = _doc(r"C:\docs\a.pdf", 2, "new")
        self.vs.replace_document(self.store, a_id, a2, a2e, dim=DIM)

        _, table = self.vs._get_table(self.store, DIM)
        self.assertEqual(table.version, before + 1)
        rows = self._rows(a_id)
        self.assertEqual(sorted(r["text"] for r in rows), ["new text 0", "new text 1"])
        self.assertEqual(len(self._rows(b_id)), 2)

    def test_duplicate_ids_are_refused_before_anything_is_written(self):
        a_id, a1, a1e = _doc(r"C:\docs\a.pdf", 2, "old")
        self.vs.replace_document(self.store, a_id, a1, a1e, dim=DIM)

        _, dup, dupe = _doc(r"C:\docs\a.pdf", 2, "new")
        dup[1].chunk_id = dup[0].chunk_id
        dupe[1].chunk_id = dupe[0].chunk_id
        with self.assertRaises(ValueError):
            self.vs.replace_document(self.store, a_id, dup, dupe, dim=DIM)
        self.assertEqual(sorted(r["text"] for r in self._rows(a_id)), ["old text 0", "old text 1"])

    def test_an_empty_new_version_removes_the_document(self):
        a_id, a1, a1e = _doc(r"C:\docs\a.pdf", 2, "old")
        self.vs.replace_document(self.store, a_id, a1, a1e, dim=DIM)
        self.vs.replace_document(self.store, a_id, [], [], dim=DIM)
        self.assertEqual(self._rows(a_id), [])


class CommitDocumentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.meta = Path(self._tmp.name) / "metadata.db"
        from storage import metadata_db
        self.db = metadata_db
        self.db.init_db(self.meta)

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, source, sha, parents):
        self.db.commit_document(
            self.meta, source, file_name=Path(source).name, format="pdf", sha256=sha,
            created_at="", modified_at="", chunk_count=len(parents), status="indexed",
            dataset="project", parents=parents, cache_items=[("h1", "x_c_0000", "x_p_0000")])

    def _parents(self, source):
        with closing(sqlite3.connect(self.meta)) as con:
            return sorted(r[0] for r in con.execute(
                "SELECT parent_id FROM parent_chunks WHERE source_path = ?", (source,)))

    def test_metadata_is_swapped_whole(self):
        src = r"C:\docs\a.pdf"
        self._commit(src, "sha1", {"p1": "one", "p2": "two"})
        self._commit(src, "sha2", {"p1": "one again"})

        self.assertEqual(self._parents(src), ["p1"])
        rec = self.db.get_file(self.meta, src)
        self.assertEqual((rec["sha256"], rec["status"]), ("sha2", "indexed"))

    def test_rules_survive_a_metadata_commit(self):
        src = r"C:\docs\norm.docx"
        self.db.replace_engineering_rules(self.meta, src, [{
            "chunk_id": "c1", "rule_text": "t", "subject": "s", "parameter": "p",
            "operator": ">=", "value": 1.0, "unit": "м", "condition": ""}])
        self._commit(src, "sha1", {"p1": "one"})
        with closing(sqlite3.connect(self.meta)) as con:
            n = con.execute("SELECT COUNT(*) FROM engineering_rules WHERE source_path = ?",
                            (src,)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_an_interrupted_commit_is_redone_even_for_unchanged_bytes(self):
        src = r"C:\docs\a.pdf"
        self._commit(src, "sha1", {"p1": "one"})
        self.assertFalse(self.db.file_changed(self.meta, src, "sha1"))

        self.db.mark_reindexing(self.meta, src)   # ... and the process dies here
        self.assertTrue(self.db.file_changed(self.meta, src, "sha1"))

        self._commit(src, "sha1", {"p1": "one"})
        self.assertFalse(self.db.file_changed(self.meta, src, "sha1"))


if __name__ == "__main__":
    unittest.main()
