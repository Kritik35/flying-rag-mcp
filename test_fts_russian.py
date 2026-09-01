"""The lexical half of the hybrid has to speak the corpus's language.

`create_fts_index` defaults to `language="English"` with `stem=True`, so a
Russian corpus was indexed with an English stemmer and English stop words. Each
inflected form became an unrelated token. Measured on the live index, top-40 per
query:

    «воздуховод» ∩ «воздуховодов»      0 shared of 38/33
    «клапан» ∩ «клапаны»               0 shared of 40/37
    «шумоглушитель» ∩ «шумоглушители»  1 shared of 37/25

Russian inflects across six cases and two numbers, so the FTS channel was
finding one form's worth of matches instead of the word's, and the hybrid was
running on roughly half of what it claimed.
"""
from __future__ import annotations

import hashlib
import math
import tempfile
import unittest
from pathlib import Path

DIM = 16

CORPUS = {
    "a": "Шумоглушитель пластинчатый устанавливается на приточном воздуховоде",
    "b": "Шумоглушители применяются для снижения уровня шума в системах",
    "c": "Огнезадерживающий клапан устанавливается в месте пересечения преграды",
    "d": "Клапаны противопожарные нормально открытые с электроприводом",
    "e": "Расчёт воздухообмена выполняется по кратности для каждого помещения",
    "f": "Воздухообмены помещений приняты по нормативным кратностям",
}


def _vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in str(text or "").casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vec[int.from_bytes(digest[:4], "big") % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class RussianStemmingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chunker.semantic import Chunk
        from embedder.batcher import EmbeddingResult
        from storage.vector_store import ensure_fts_index, upsert_chunks

        cls.tmp = tempfile.TemporaryDirectory()
        cls.lance_path = Path(cls.tmp.name) / "lancedb"
        chunks, embeddings = [], []
        for key, text in CORPUS.items():
            chunk_id = f"doc{key}_c0"
            chunks.append(Chunk(
                doc_id=f"doc{key}", chunk_id=chunk_id, text=text,
                metadata={"source_path": rf"C:\corpus\{key}.docx",
                          "file_name": f"{key}.docx", "namespace": "normative"},
            ))
            embeddings.append(EmbeddingResult(chunk_id=chunk_id,
                                              embedding=_vector(text)))
        upsert_chunks(cls.lance_path, chunks, embeddings, dim=DIM)
        cls.built = ensure_fts_index(cls.lance_path, dim=DIM)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _fts(self, query: str) -> set[str]:
        import lancedb

        table = lancedb.connect(str(self.lance_path)).open_table("documents_16")
        return {r["chunk_id"]
                for r in table.search(query, query_type="fts").limit(10).to_list()}

    def test_the_index_was_built(self):
        self.assertTrue(self.built)

    def test_a_plural_query_finds_the_singular(self):
        self.assertIn("doca_c0", self._fts("шумоглушители"))

    def test_a_singular_query_finds_the_plural(self):
        self.assertIn("docd_c0", self._fts("клапан"))

    def test_a_declined_form_finds_the_nominative(self):
        """Not every form merges: the Russian Snowball stemmer leaves the
        genitive plural of some compounds alone — «воздухообменов» finds
        nothing while «воздухообмена» and «воздухообмены» both reach every
        chunk about воздухообмен. Good enough is the claim being made here,
        not perfect."""
        self.assertIn("doce_c0", self._fts("воздухообмены"))
        self.assertIn("docf_c0", self._fts("воздухообмена"))

    def test_an_unrelated_word_still_does_not_match(self):
        hits = self._fts("бетон")
        self.assertNotIn("doca_c0", hits)
        self.assertNotIn("docc_c0", hits)


if __name__ == "__main__":
    unittest.main()
