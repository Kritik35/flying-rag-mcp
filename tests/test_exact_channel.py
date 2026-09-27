"""Запрос по шифру не находил фрагменты, где шифр написан ровно.

Живой запрос `П1-TRF-01-01 ХОВС`: точный код есть в 135 фрагментах индекса,
а в пятёрке не было ни одного — там стояли `П1-TRF-01-02`, `-01-03` и пятый
результат с оценкой 0.0. Полнотекстовый канал режет шифр на токены
`п1 / trf / 01 / 01`, и строки ХОВС, где этих токенов много, вытесняют точные
совпадения из пула ещё до того, как сработает тай-брейк по шифру: из 135
фрагментов с кодом в пул попадало 32. Фразовый поиск помог бы, но индекс
построен без позиций.

Поэтому отдельный точный канал: скан подстроки по всем шифрам запроса одним
проходом (0.2 с на 1.39 млн строк), проверка границ тем же правилом, что и у
`exact_hits` (ZX-100 не находится внутри ZX-1000), порядок — сначала по числу
шифров запроса во фрагменте, затем по близости к вектору запроса, чтобы
остальные слова («ХОВС») тоже работали. Результат добавляется отдельным
списком в слияние, как это уже делает защита названной нормы.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from storage import vector_store


def _store(rows):
    """Временное хранилище с настоящей схемой и векторами размерности 4."""
    db = Path(tempfile.mkdtemp())
    _, table = vector_store._get_table(db, dim=4)
    data = []
    for i, (text, vec, path) in enumerate(rows):
        v = np.array(vec, dtype=np.float32)
        v = (v / np.linalg.norm(v)).astype(np.float16).tolist()
        data.append({
            "chunk_id": f"c{i}", "doc_id": f"d{i}", "text": text, "vector": v,
            "source_path": path, "file_name": Path(path).name, "format": "pdf",
            "created_at": "", "modified_at": "", "section": "",
            "namespace": "project", "parent_id": f"p{i}",
        })
    table.add(data)
    return db


Q = [1.0, 0.0, 0.0, 0.0]


class SearchExactTests(unittest.TestCase):
    def test_only_the_exact_code_is_returned_not_its_neighbours(self):
        db = _store([
            ("Система П1-TRF-01-02 аварийный режим", [1, 0, 0, 0], r"C:\p\a.pdf"),
            ("Система П1-TRF-01-01 приточная", [0, 1, 0, 0], r"C:\p\b.pdf"),
            ("Система П1-TRF-01-03", [1, 0, 0, 0], r"C:\p\c.pdf"),
        ])

        rows = vector_store.search_exact(db, Q, ["П1-TRF-01-01"], top_k=10, dim=4)

        self.assertEqual([r["file_name"] for r in rows], ["b.pdf"])

    def test_a_longer_code_is_not_a_match(self):
        db = _store([
            ("поз. П1-TRF-01-012 и П1-TRF-01-01A", [1, 0, 0, 0], r"C:\p\a.pdf"),
            ("П1-TRF-01-01, резерв", [0, 1, 0, 0], r"C:\p\b.pdf"),
        ])

        rows = vector_store.search_exact(db, Q, ["П1-TRF-01-01"], top_k=10, dim=4)

        self.assertEqual([r["file_name"] for r in rows], ["b.pdf"])

    def test_closer_to_the_query_ranks_first(self):
        db = _store([
            ("П1-TRF-01-01 далёкий", [0, 0, 1, 0], r"C:\p\far.pdf"),
            ("П1-TRF-01-01 близкий", [1, 0.1, 0, 0], r"C:\p\near.pdf"),
        ])

        rows = vector_store.search_exact(db, Q, ["П1-TRF-01-01"], top_k=10, dim=4)

        self.assertEqual([r["file_name"] for r in rows], ["near.pdf", "far.pdf"])

    def test_a_chunk_with_more_of_the_codes_ranks_first(self):
        db = _store([
            ("R.L2.15.092", [1, 0, 0, 0], r"C:\p\one.pdf"),
            ("R.L2.15.092 и R.L2.15.093", [0, 0, 1, 0], r"C:\p\two.pdf"),
        ])

        rows = vector_store.search_exact(db, Q, ["R.L2.15.092", "R.L2.15.093"],
                                         top_k=10, dim=4)

        self.assertEqual(rows[0]["file_name"], "two.pdf")

    def test_the_scope_filter_is_respected(self):
        db = _store([
            ("П1-TRF-01-01", [1, 0, 0, 0], r"C:\НТД\norm.pdf"),
            ("П1-TRF-01-01", [1, 0, 0, 0], r"C:\#_Work\ПД_PDF\sheet.pdf"),
        ])

        rows = vector_store.search_exact(db, Q, ["П1-TRF-01-01"], top_k=10, dim=4,
                                         folder_filter="ПД_PDF")

        self.assertEqual([r["file_name"] for r in rows], ["sheet.pdf"])

    def test_a_quote_in_a_code_cannot_break_the_query(self):
        db = _store([("код A'1-B-2", [1, 0, 0, 0], r"C:\p\a.pdf")])

        rows = vector_store.search_exact(db, Q, ["A'1-B-2"], top_k=10, dim=4)

        self.assertEqual(len(rows), 1)

    def test_hitting_the_scan_limit_is_reported(self):
        from unittest.mock import patch

        db = _store([("П1-TRF-01-01", [1, 0, 0, 0], r"C:\p\a.pdf"),
                     ("П1-TRF-01-01", [0, 1, 0, 0], r"C:\p\b.pdf")])
        trace: dict = {}
        with patch.object(vector_store, "EXACT_SCAN_LIMIT", 1):
            vector_store.search_exact(db, Q, ["П1-TRF-01-01"], top_k=10, dim=4, trace=trace)

        self.assertTrue(trace["exact_truncated"])

    def test_no_codes_means_no_scan(self):
        db = _store([("П1-TRF-01-01", [1, 0, 0, 0], r"C:\p\a.pdf")])

        self.assertEqual(vector_store.search_exact(db, Q, [], top_k=10, dim=4), [])

    def test_results_have_the_regular_result_shape(self):
        db = _store([("П1-TRF-01-01", [1, 0, 0, 0], r"C:\p\a.pdf")])

        row = vector_store.search_exact(db, Q, ["П1-TRF-01-01"], top_k=10, dim=4)[0]

        for key in ("chunk_id", "parent_id", "doc_id", "text", "child_text",
                    "context_source", "source_path", "file_name", "section", "score"):
            self.assertIn(key, row)


class CodesForTheChannelTests(unittest.TestCase):
    """В точный канал идут шифры, но не обозначения норм.

    Обозначение нормы («СП 60.13330») в тексте встречается в каждом документе,
    который на неё ссылается; скан подстроки вернул бы 93 ссылающихся документа
    вместо самой нормы. Для норм есть своя защита.
    """

    def test_codes_are_taken_and_norms_are_left_out(self):
        from rag_server.tools import exact_channel_codes

        codes = exact_channel_codes("кратность СП 60.13330 для П1-TRF-01-01 и R.L2.15.114")

        self.assertEqual(codes, ["П1-TRF-01-01", "R.L2.15.114"])

    def test_a_plain_question_has_no_codes(self):
        from rag_server.tools import exact_channel_codes

        self.assertEqual(exact_channel_codes("требования к вентиляции паркинга"), [])


if __name__ == "__main__":
    unittest.main()
