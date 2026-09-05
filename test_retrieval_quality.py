from __future__ import annotations

import unittest


class RetrievalQualityTests(unittest.TestCase):
    def test_normative_title_page_is_ranked_below_substantive_rule_text(self):
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": "title",
                "doc_id": "doc-title",
                "text": (
                    "Утвержден и введен в действие приказом. "
                    "НАЦИОНАЛЬНЫЙ СТАНДАРТ РОССИЙСКОЙ ФЕДЕРАЦИИ. "
                    "Предисловие. Дата введения. ОКС 91.140."
                ),
                "file_name": "ГОСТ Р 21.621-2023.docx",
                "source_path": r"H:\Мой диск\НТД\384-ФЗ\ГОСТ Р 21.621-2023.docx",
                "score": 0.95,
            },
            {
                "chunk_id": "rule",
                "doc_id": "doc-rule",
                "text": (
                    "Воздуховоды систем противодымной вентиляции должны иметь "
                    "предел огнестойкости не менее EI 60. Требования следует "
                    "принимать по таблице 1."
                ),
                "file_name": "СП 7.13130.2013.docx",
                "source_path": r"H:\Мой диск\НТД\123-ФЗ\СП 7.13130.2013.docx",
                "score": 0.72,
            },
        ]

        ranked = apply_retrieval_quality(
            "предел огнестойкости воздуховодов",
            results,
            dataset="normative",
            top_k=2,
        )

        self.assertEqual(ranked[0]["chunk_id"], "rule")
        self.assertLess(ranked[1]["score"], ranked[0]["score"])
        self.assertGreater(ranked[1]["quality"]["title_penalty"], 0)

    def test_project_ventilation_query_prefers_ov_source_over_table_noise(self):
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": "eom-table",
                "doc_id": "doc-eom",
                "text": (
                    "| А | А | А | А | А | А | А | А | А | А |\n"
                    "| SLICK.PRS ECO LED 30 HFD | 400лк | 1х31Вт | 3м |\n"
                    "| шт. | шт. | шт. | шт. | шт. | шт. |"
                ),
                "file_name": "Раздел ПД №5. Подраздел 1. ЭОМ. Изм.3.pdf",
                "source_path": r"C:\Project\PD_PDF\ЭОМ.pdf",
                "score": 0.93,
            },
            {
                "chunk_id": "ov-content",
                "doc_id": "doc-ov",
                "text": (
                    "Система ОВ2 обеспечивает общеобменную и противодымную "
                    "вентиляцию. Дымоудаление и подпор воздуха выполняются "
                    "для защищаемых помещений."
                ),
                "file_name": "project-discipline-summary.pdf",
                "source_path": (
                    r"C:\Project\PD_PDF"
                    r"\ОВ2_project\pdf"
                ),
                "score": 0.68,
            },
        ]

        ranked = apply_retrieval_quality(
            "противодымная вентиляция ОВ2",
            results,
            dataset="project",
            top_k=2,
        )

        self.assertEqual(ranked[0]["chunk_id"], "ov-content")
        self.assertGreater(ranked[1]["quality"]["table_penalty"], 0)
        self.assertGreater(ranked[0]["quality"]["path_bonus"], 0)

    def test_project_stamp_block_is_ranked_below_content_from_same_discipline(self):
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": "ov-stamp",
                "doc_id": "stamp-doc",
                "text": (
                    'ООО "Проектная организация" адрес организации example@example.com '
                    "Формат: А1х3 Copyright by Project Team Изм. Лист Кол.уч. "
                    "Подп. Дата №док. Лист Листов Стадия Инв.№подп. "
                    "Заказчик: Заказчик."
                ),
                "file_name": "project-stamp-sheet.pdf",
                "source_path": r"C:\Project\ОВ2_система\project-sheet.pdf",
                "score": 0.88,
            },
            {
                "chunk_id": "ov-rule",
                "doc_id": "content-doc",
                "text": (
                    "Противодымная вентиляция ОВ2 предусматривает дымоудаление "
                    "из коридоров и подпор воздуха. Система должна включаться "
                    "при пожаре по сигналу автоматики."
                ),
                "file_name": "project-explanatory-note.pdf",
                "source_path": r"C:\Project\ОВ2_система\ПЗ.pdf",
                "score": 0.62,
            },
        ]

        ranked = apply_retrieval_quality(
            "противодымная вентиляция ОВ2",
            results,
            dataset="project",
            top_k=2,
        )

        self.assertEqual(ranked[0]["chunk_id"], "ov-rule")
        self.assertGreater(ranked[1]["quality"]["table_penalty"], 0.2)

    def test_project_equipment_schedule_noise_is_ranked_below_sentences(self):
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": "equipment-schedule",
                "doc_id": "schedule-doc",
                "text": (
                    "НС регулирования TROX РНС Клапан противопожарный L30100 L17270 "
                    "ППК.НО.187 двойного действия ВИНГС-М ППК.НО.81 SYS-SMK-10-01 "
                    "1200x700 -8,900 L33490 Вытяжная решетка без ППК.ДД 1700x950 "
                    "L17270 -11,125 11.ФВК -7,230 -8,200"
                ),
                "file_name": "project-equipment-schedule.pdf",
                "source_path": r"C:\Project\ОВ2_система\project-equipment-schedule.pdf",
                "score": 0.96,
            },
            {
                "chunk_id": "project-sentence",
                "doc_id": "sentence-doc",
                "text": (
                    "При совместном действии систем приточной и вытяжной противодымной "
                    "вентиляции отрицательный дисбаланс в защищаемом помещении принят "
                    "не более 30%. Подпор воздуха выполняется системой ПВ."
                ),
                "file_name": "Раздел ПД №5. Подраздел 4. Часть 6. ПВ.pdf",
                "source_path": r"C:\Project\ПД_PDF\Раздел ПД №5. Подраздел 4. Часть 6. ПВ.pdf",
                "score": 0.70,
            },
        ]

        ranked = apply_retrieval_quality(
            "противодымная вентиляция ОВ2",
            results,
            dataset="project",
            top_k=2,
        )

        self.assertEqual(ranked[0]["chunk_id"], "project-sentence")
        self.assertGreater(ranked[1]["quality"]["table_penalty"], 0.35)

    def test_project_acoustic_dimension_dump_is_ranked_below_sentence(self):
        # Real fragment from project-table-fragment (silencer octave-band table +
        # duct dimensions), even though it literally contains the query terms.
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": "acoustic-dump",
                "doc_id": "p1-doc",
                "text": (
                    "SYS-FAN-01-01\nШГ- 918\nHz\n63\n125\n250\n500\n1000\n2000\n4000\n"
                    "8000\ndB\n4\n9\n18\n20\n24\n17\n12\n10\n20 Па\n3300\nx\n1500\n2шт\n"
                    "3290\nx\n1510\n2 Па\nСекция шумоглушителя\nМарка шумоглушителя\n"
                    "Потеря давления"
                ),
                "file_name": "project-table-fragment.txt",
                "source_path": r"C:\Project\ОВ2\project-table-fragment.txt",
                # noisy chunk even slightly leads on raw retrieval score; the
                # quality penalty must still pull it below the real sentence.
                "score": 0.82,
            },
            {
                "chunk_id": "pv-sentence",
                "doc_id": "pz-doc",
                "text": (
                    "Потеря давления в системе приточной противодымной вентиляции ПВ "
                    "учитывается при подборе вентилятора и шумоглушителя. Система "
                    "обеспечивает подпор воздуха в лестничную клетку."
                ),
                "file_name": "project-explanatory-note.pdf",
                "source_path": r"C:\Project\ОВ2\ПЗ.pdf",
                "score": 0.78,
            },
        ]

        ranked = apply_retrieval_quality(
            "потеря давления шумоглушитель ПВ",
            results,
            dataset="project",
            top_k=2,
        )

        self.assertEqual(ranked[0]["chunk_id"], "pv-sentence")
        self.assertGreater(ranked[1]["quality"]["table_penalty"], 0.2)

    def test_project_schematic_dimension_dump_is_penalized(self):
        # Real fragment: schematic node/dimension dump (no real sentences),
        # the table_noise heuristic must penalize it on its own.
        from rag_server.retrieval_quality import table_noise_penalty

        noisy = (
            "теплоноситель\nК5\nК4\nК1\nМ\nМ\nК3\nК2\nф\n3\n2\nМ\n1\nОпора\nОпора\n"
            "3\n3\n3\n3\n3\n5\n5\n7\n7\nТ1\nТ2\nМ\n5\nТ\n6\n45\n2\n3440\nх\n1640\n"
            "3440\nх\n1640\n3300\nx\n1500\n2шт\n3290\nx\n1510\n2 Па\nФГ- 50\n2,54 м/с\n66 Па"
        )
        self.assertGreater(table_noise_penalty(noisy), 0.2)

    def test_copies_of_one_document_share_the_per_document_budget(self):
        """The cap counted source paths, so copies multiplied a document's slots.

        The same norm is indexed as .docx and as .pdf under different paths and
        different doc_ids. With max_per_doc=2 that gave it four slots while a
        document held in one copy got two — the more copies, the higher it rode.
        """
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = []
        for fmt in ("docx", "pdf"):
            for i in range(3):
                results.append({
                    "chunk_id": f"{fmt}-{i}",
                    "doc_id": f"doc-{fmt}-{i}",
                    "text": f"системы вытяжной противодымной вентиляции коридоров {i}",
                    "file_name": f"СП 120.13330.{fmt}",
                    "source_path": rf"H:\НТД\СП 120.13330.{fmt}",
                    "score": 0.90 - i * 0.01,
                })
        results.append({
            "chunk_id": "right-1",
            "doc_id": "doc-right",
            "text": "удаление продуктов горения из коридоров предусматривают",
            "file_name": "СП 7.13130.docx",
            "source_path": r"H:\НТД\СП 7.13130.docx",
            "score": 0.80,
        })

        ranked = apply_retrieval_quality(
            "удаление дыма из коридоров", results,
            dataset="normative", top_k=6, max_per_doc=2,
        )

        copies = sum(1 for r in ranked if "120.13330" in r["file_name"])
        self.assertLessEqual(copies, 2)
        self.assertIn("СП 7.13130.docx", {r["file_name"] for r in ranked})

    def test_a_numbered_copy_is_the_same_document(self):
        from rag_server.retrieval_quality import document_key

        self.assertEqual(
            document_key({"source_path": r"H:\НТД\СП 7.13130.docx"}),
            document_key({"source_path": r"H:\НТД\СП 7.13130.pdf"}),
        )
        self.assertEqual(
            document_key({"source_path": r"H:\НТД\СП 120 (1).docx"}),
            document_key({"source_path": r"H:\НТД\СП 120.docx"}),
        )
        self.assertNotEqual(
            document_key({"source_path": r"H:\НТД\СП 7.13130.docx"}),
            document_key({"source_path": r"H:\НТД\СП 1.13130.docx"}),
        )

    def test_the_score_saturates_and_the_ceiling_is_load_bearing(self):
        """This looks like a bug and was measured not to be one.

        The displayed score is clamped to 1.0, and on the golden set 31 of 100
        returned results carry exactly that, with 8 of 20 queries showing ties
        inside their own top-5 — four of them returning five results all at
        1.000. The bonuses put them there: a lexical bonus fires on 92 of 100
        results and a substantive one on 82, so several near-constants land on
        top of a base score of 0.66 and go over the edge.

        Ordering those ties by the unclamped sum was tried and measured, three
        repeats each:

            clamped (this)   hit@5 0.7500 (spread 0.0000)   mrr 0.5392 (0.0025)
            unclamped        hit@5 0.7500 (spread 0.0500)   mrr 0.4783 (0.0525)

        It got worse and noisier. The reason is that the unclamped sum carries
        the retrieval score, which moves with the embedding server's jitter,
        while the tie-breakers below the ceiling — lexical and path bonuses —
        are deterministic functions of the query and the text. The ceiling was
        acting as a noise filter.

        So the saturation is a real weakness of the scoring function and the
        clamp is not the place to address it. Anyone rewriting this should
        reduce what the bonuses hand out, and measure.
        """
        from rag_server.retrieval_quality import score_result

        item = score_result(
            "предел огнестойкости воздуховодов",
            {"chunk_id": "a", "doc_id": "d1", "file_name": "СП 7.docx",
             "source_path": "c/СП 7.docx", "score": 0.99,
             "text": "предел огнестойкости воздуховодов принимается не менее EI 30 "
                     "для транзитных участков систем противодымной вентиляции"},
            dataset="normative",
        )

        self.assertEqual(item["quality"]["adjusted_score"], 1.0)
        self.assertLessEqual(item["score"], 1.0)
        self.assertGreaterEqual(item["score"], 0.0)

    def test_ties_are_broken_by_something_deterministic(self):
        """Two results that both hit the ceiling must still come back in a
        stable order, or the answer changes between identical runs."""
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {"chunk_id": "a", "doc_id": "d1", "file_name": "a.docx",
             "source_path": "c/a.docx", "score": 0.99,
             "text": "предел огнестойкости воздуховодов не менее EI 30 транзитных"},
            {"chunk_id": "b", "doc_id": "d2", "file_name": "b.docx",
             "source_path": "c/b.docx", "score": 0.99,
             "text": "предел огнестойкости воздуховодов не менее EI 30 транзитных"},
        ]
        order = [
            [r["chunk_id"] for r in apply_retrieval_quality(
                "предел огнестойкости воздуховодов",
                [dict(x) for x in results],
                dataset="normative", top_k=2, max_per_doc=2)]
            for _ in range(5)
        ]

        self.assertEqual(len(set(map(tuple, order))), 1, order)

    def test_a_chunk_carrying_the_asked_code_outranks_prose_without_it(self):
        """The scorer prefers prose over tables, and that loses code lookups.

        A norm is prose and earns the substantive bonus; a project sheet is a
        table and takes the table penalty. So for «С.П2.15.114» the store
        returned 11 chunks carrying the code out of 40, and after this function
        only 6 survived with СП 326 and СП 53 — which do not contain it — sitting
        at ranks two and three.

        A verbatim identifier is the strongest signal available. Whatever the
        surrounding text reads like, the chunk that has what was asked for
        belongs above the chunk that does not.
        """
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {"chunk_id": "prose", "doc_id": "d1", "file_name": "СП 326.pdf",
             "source_path": "c/СП 326.pdf", "score": 0.95,
             "text": "Помещения категории В следует оборудовать системами "
                     "приточно-вытяжной вентиляции с механическим побуждением "
                     "в соответствии с требованиями настоящего свода правил"},
            {"chunk_id": "sheet", "doc_id": "d2", "file_name": "АТ-РД-ОВ2-10.04.pdf",
             "source_path": "c/АТ-РД-ОВ2-10.04.pdf", "score": 0.70,
             "text": "С.П2.15.114 | венткамера | 48,3 | П2-CAF-02-03 | 1200"},
        ]

        ranked = apply_retrieval_quality("С.П2.15.114", results,
                                         dataset=None, top_k=2, max_per_doc=2)

        self.assertEqual(ranked[0]["chunk_id"], "sheet")

    def test_the_number_of_verbatim_hits_is_recorded(self):
        from rag_server.retrieval_quality import score_result

        item = score_result(
            "1.02.11.024 1.02.11.025 1.02.11.026",
            {"chunk_id": "a", "doc_id": "d1", "file_name": "лист.pdf",
             "source_path": "c/лист.pdf", "score": 0.6,
             "text": "1.02.11.024 1.02.11.025 кабинет 1.02.11.099"},
            dataset=None,
        )

        self.assertEqual(item["quality"]["exact_hits"], 2)

    def test_a_question_without_identifiers_scores_as_before(self):
        """Nothing changes for the queries that already work."""
        from rag_server.retrieval_quality import score_result

        item = score_result(
            "требования к противодымной вентиляции коридоров",
            {"chunk_id": "a", "doc_id": "d1", "file_name": "СП 7.docx",
             "source_path": "c/СП 7.docx", "score": 0.8,
             "text": "системы вытяжной противодымной вентиляции коридоров"},
            dataset="normative",
        )

        self.assertEqual(item["quality"]["exact_hits"], 0)
        self.assertEqual(item["quality"]["exact_bonus"], 0.0)

    def test_final_results_are_diversified_by_document(self):
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": f"a-{i}",
                "doc_id": "same-doc",
                "text": f"противодымная вентиляция расчет требования раздел {i}",
                "file_name": "ОВ.pdf",
                "source_path": r"C:\Project\ОВ.pdf",
                "score": 0.95 - i * 0.01,
            }
            for i in range(4)
        ]
        results.append(
            {
                "chunk_id": "b-0",
                "doc_id": "other-doc",
                "text": "противодымная вентиляция требования",
                "file_name": "ОВ2.pdf",
                "source_path": r"C:\Project\ОВ2.pdf",
                "score": 0.6,
            }
        )

        ranked = apply_retrieval_quality(
            "противодымная вентиляция",
            results,
            dataset="project",
            top_k=3,
            max_per_doc=2,
        )

        self.assertEqual(len(ranked), 3)
        self.assertLessEqual(
            sum(1 for r in ranked if r["doc_id"] == "same-doc"),
            2,
        )
        self.assertIn("other-doc", {r["doc_id"] for r in ranked})

    def test_final_results_are_diversified_by_source_path_before_doc_id(self):
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": f"same-source-{i}",
                "doc_id": f"doc-{i}",
                "text": "предел огнестойкости воздуховодов не менее EI 30",
                "file_name": "СП 60.docx",
                "source_path": r"H:\НТД\СП 60.docx",
                "score": 0.9 - i * 0.01,
            }
            for i in range(4)
        ]
        results.append(
            {
                "chunk_id": "other-source",
                "doc_id": "other-doc",
                "text": "предел огнестойкости воздуховодов следует принимать по таблице",
                "file_name": "СП 7.docx",
                "source_path": r"H:\НТД\СП 7.docx",
                "score": 0.5,
            }
        )

        ranked = apply_retrieval_quality(
            "предел огнестойкости воздуховодов",
            results,
            dataset="normative",
            top_k=3,
            max_per_doc=2,
        )

        self.assertLessEqual(
            sum(1 for r in ranked if r["source_path"] == r"H:\НТД\СП 60.docx"),
            2,
        )
        self.assertIn(r"H:\НТД\СП 7.docx", {r["source_path"] for r in ranked})


if __name__ == "__main__":
    unittest.main()
