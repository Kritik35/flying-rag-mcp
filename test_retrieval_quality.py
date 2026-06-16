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
                "file_name": "ОВ2-С-00_Система общеобменной и противодымной вентиляции.pdf",
                "source_path": (
                    r"C:\Project\PD_PDF"
                    r"\ОВ2-С-00_Система общеобменной и противодымной вентиляции\pdf"
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
                    'ООО "АТП ТЛП" Ленинградский пр. info@atp-tlp.ru '
                    "Формат: А1х3 Copyright by ATP TLP Изм. Лист Кол.уч. "
                    "Подп. Дата №док. Лист Листов Стадия Инв.№подп. "
                    "Заказчик: Акционерное общество."
                ),
                "file_name": "ОВ2-С-00-32.16-04.pdf",
                "source_path": r"C:\Project\ОВ2_система\ОВ2-лист.pdf",
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
                "file_name": "ОВ2-С-00_Пояснительная записка.pdf",
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
                    "ППК.НО.187 двойного действия ВИНГС-М ППК.НО.81 ПВ2-OFF-10-01 "
                    "1200x700 -8,900 L33490 Вытяжная решетка без ППК.ДД 1700x950 "
                    "L17270 -11,125 11.ФВК -7,230 -8,200"
                ),
                "file_name": "ОВ2-40.13-04.pdf",
                "source_path": r"C:\Project\ОВ2_система\ОВ2-40.13-04.pdf",
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
        # Real fragment from ОВ2-С-00-П1 (silencer octave-band table +
        # duct dimensions), even though it literally contains the query terms.
        from rag_server.retrieval_quality import apply_retrieval_quality

        results = [
            {
                "chunk_id": "acoustic-dump",
                "doc_id": "p1-doc",
                "text": (
                    "PV2-OFF-01-01\nШГ- 918\nHz\n63\n125\n250\n500\n1000\n2000\n4000\n"
                    "8000\ndB\n4\n9\n18\n20\n24\n17\n12\n10\n20 Па\n3300\nx\n1500\n2шт\n"
                    "3290\nx\n1510\n2 Па\nСекция шумоглушителя\nМарка шумоглушителя\n"
                    "Потеря давления"
                ),
                "file_name": "ОВ2-С-00-П1_part1.txt",
                "source_path": r"C:\Project\ОВ2\ОВ2-С-00-П1_part1.txt",
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
                "file_name": "ОВ2-С-00_Пояснительная записка.pdf",
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
