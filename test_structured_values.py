from __future__ import annotations

import unittest

from structured_values.extractor import extract_labeled_values
from structured_values.report import build_markdown_report, rows_to_csv


class StructuredValuesTests(unittest.TestCase):
    def test_extracts_vertical_label_value_for_current_record(self):
        text = """
        В1-DGU-01-01
        Технические данные
        Дорегулирование
        400 Па
        Расход фактический
        1430 м3/ч
        """

        rows = extract_labeled_values(text, labels=["Дорегулирование"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].record, "В1-DGU-01-01")
        self.assertEqual(rows[0].label, "Дорегулирование")
        self.assertEqual(rows[0].value, 400.0)
        self.assertEqual(rows[0].unit, "Па")
        self.assertGreater(rows[0].confidence, 0.7)

    def test_extracts_multiple_labels_without_hardcoding_parameter_name(self):
        text = """
        PV2-OFF-01-01
        Потеря давления
        20.81 Па
        Скорость воздуха
        2.6 м/с
        """

        rows = extract_labeled_values(text, labels=["Потеря давления", "Скорость воздуха"])

        by_label = {row.label: row for row in rows}
        self.assertEqual(by_label["Потеря давления"].value, 20.81)
        self.assertEqual(by_label["Потеря давления"].unit, "Па")
        self.assertEqual(by_label["Скорость воздуха"].value, 2.6)
        self.assertEqual(by_label["Скорость воздуха"].unit, "м/с")

    def test_does_not_cross_record_boundary_for_value(self):
        text = """
        В1-DGU-01-01
        Дорегулирование
        В1-DGU-01-02
        66.75 Па
        """

        rows = extract_labeled_values(text, labels=["Дорегулирование"])

        self.assertEqual(rows, [])

    def test_report_outputs_csv_and_markdown_with_provenance(self):
        rows = extract_labeled_values(
            """
            В1-DGU-01-01
            Дорегулирование
            400 Па
            В1-LAV-03-01
            Дорегулирование
            0 Па
            """,
            labels=["Дорегулирование"],
        )

        csv_text = rows_to_csv(rows)
        report = build_markdown_report(rows, title="Risk probe", source_note="heuristic parent_chunks extraction")

        self.assertIn("record;label;value;unit;confidence;evidence", csv_text.splitlines()[0])
        self.assertIn("В1-DGU-01-01", csv_text)
        self.assertIn("heuristic parent_chunks extraction", report)
        self.assertIn("0 Па", report)
        self.assertIn(">= 300 Па", report)


if __name__ == "__main__":
    unittest.main()
