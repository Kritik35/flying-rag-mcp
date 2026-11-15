"""
tests/test_evidence_gate.py

Self-contained unit tests for EvidenceIntegrityGate (Stage 4.1):
1. Exact document token-boundary resolution (СП 7 vs СП 70).
2. Multi-edition disambiguation (AMBIGUOUS_SOURCE vs VERIFIED_EDITION vs EDITION_NOT_FOUND).
3. SQLite range query hash integrity enforcement.
4. Clause absence vs header match failure.
5. Strict REFUSAL_REQUIRED on topic mismatch.
"""
from __future__ import annotations
import sqlite3
import hashlib
import tempfile
import unittest
from pathlib import Path

from evidence_gate.evidence_gate import EvidenceIntegrityGate


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_meta.db"

        # Build self-contained SQLite test database
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE files (
                source_path TEXT PRIMARY KEY,
                file_name TEXT,
                format TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE parent_chunks (
                parent_id TEXT PRIMARY KEY,
                source_path TEXT,
                parent_text TEXT
            )
        """)

        # Insert test files
        self.doc_sp7 = "docs/СП 7.13130.docx"
        self.doc_sp70 = "docs/СП 70.13330.2012. Свод правил. Несущие.docx"
        self.doc_sp60_2012 = "docs/СП 60.13330.2012. Свод правил. Отопление.pdf"
        self.doc_sp60_2020 = "docs/СП 60.13330.2020. Свод правил. Отопление.docx"

        conn.execute("INSERT INTO files VALUES (?, ?, 'docx', 'active')", (self.doc_sp7, "СП 7.13130.docx"))
        conn.execute("INSERT INTO files VALUES (?, ?, 'docx', 'active')", (self.doc_sp70, "СП 70.13330.2012. Свод правил. Несущие.docx"))
        conn.execute("INSERT INTO files VALUES (?, ?, 'pdf', 'active')", (self.doc_sp60_2012, "СП 60.13330.2012. Свод правил. Отопление.pdf"))
        conn.execute("INSERT INTO files VALUES (?, ?, 'docx', 'active')", (self.doc_sp60_2020, "СП 60.13330.2020. Свод правил. Отопление.docx"))

        # Insert test parent chunks for СП 7
        sp7_did = hashlib.sha256(self.doc_sp7.encode("utf-8")).hexdigest()[:8]
        txt_17 = "Раздел 6.\n6.4 В пределах одного пожарного отсека общие приемные устройства наружного воздуха."
        txt_18 = " наружного воздуха. Допускается предусматривать общие устройства.\n6.5 Общие устройства..."
        txt_55 = "8. Требования к решениям\n8.1 Ограждающие строительные конструкции помещений для оборудования.\n8.2 Помещения..."

        conn.execute("INSERT INTO parent_chunks VALUES (?, ?, ?)", (f"{sp7_did}_p_0017", self.doc_sp7, txt_17))
        conn.execute("INSERT INTO parent_chunks VALUES (?, ?, ?)", (f"{sp7_did}_p_0018", self.doc_sp7, txt_18))
        conn.execute("INSERT INTO parent_chunks VALUES (?, ?, ?)", (f"{sp7_did}_p_0055", self.doc_sp7, txt_55))

        # Insert chunk with forged hash to test integrity check
        conn.execute("INSERT INTO parent_chunks VALUES (?, ?, ?)", (f"forgedid_p_0099", self.doc_sp7, "Нелегитимный текст"))

        conn.commit()
        conn.close()

        self.eig = EvidenceIntegrityGate(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_doc_resolution_isolates_sp7_from_sp70(self):
        integ, row, reason = self.eig.resolve_document("СП 7.13130", None)
        self.assertEqual(integ, "SINGLE_EDITION_MATCH")
        self.assertEqual(row["source_path"], self.doc_sp7)

        integ70, row70, _ = self.eig.resolve_document("СП 70.13330", "2012")
        self.assertEqual(integ70, "VERIFIED_EDITION")
        self.assertEqual(row70["source_path"], self.doc_sp70)

    def test_ambiguous_source_when_multiple_editions_unspecified(self):
        res = self.eig.assess_evidence("СП 60.13330 пункт 7.1.1")
        self.assertEqual(res.source_integrity, "AMBIGUOUS_SOURCE")
        self.assertEqual(res.answer_evidence_status, "REFUSAL_REQUIRED")

    def test_explicit_valid_edition_resolves(self):
        integ, row, _ = self.eig.resolve_document("СП 60.13330", "2020")
        self.assertEqual(integ, "VERIFIED_EDITION")
        self.assertEqual(row["source_path"], self.doc_sp60_2020)

    def test_explicit_invalid_edition_returns_edition_not_found(self):
        res = self.eig.assess_evidence("СП 60.13330.2025 пункт 7.1.1")
        self.assertEqual(res.source_integrity, "EDITION_NOT_FOUND")
        self.assertEqual(res.answer_evidence_status, "REFUSAL_REQUIRED")

    def test_absent_document_returns_document_not_found(self):
        res = self.eig.assess_evidence("ГОСТ Р 99999-9999 пункт 1.2")
        self.assertEqual(res.source_integrity, "DOCUMENT_NOT_FOUND")
        self.assertEqual(res.document_status, "ABSENT_FROM_INDEX")
        self.assertEqual(res.answer_evidence_status, "REFUSAL_REQUIRED")

    def test_hash_integrity_filters_forged_chunks(self):
        status, chunks, reason = self.eig.search_clause_in_document(self.doc_sp7, "6.4", "clause")
        self.assertEqual(status, "FOUND_IN_CORPUS")
        # Ensure forged chunk was rejected by hash validator
        self.assertTrue(all(not c["parent_id"].startswith("forgedid") for c in chunks))

    def test_topic_mismatch_forces_refusal(self):
        # Querying clause 8.1 with mismatched topic "подпор воздуха"
        res = self.eig.assess_evidence("СП 7.13130 пункт 8.1 подпор воздуха")
        self.assertEqual(res.topic_alignment, "TOPIC_MISMATCH")
        self.assertEqual(res.answer_evidence_status, "REFUSAL_REQUIRED")

    def test_readonly_uri_blocks_writes(self):
        with self.eig._connect() as conn:
            with self.assertRaises(sqlite3.OperationalError) as ctx:
                conn.execute("INSERT INTO files (source_path) VALUES ('bad')")
            self.assertIn("readonly", str(ctx.exception).lower())

    def test_non_normative_query_abstains_with_not_applicable(self):
        # Broad semantic query without normative designation (Blocker P1-07)
        res = self.eig.assess_evidence("требования к вытяжной вентиляции автостоянок")
        self.assertEqual(res.query_applicability, "NON_NORMATIVE_QUERY")
        self.assertEqual(res.answer_evidence_status, "NOT_APPLICABLE")
        self.assertIn("abstains", res.verification_reason.lower())

    def test_document_overview_query_abstains_with_not_applicable(self):
        # Query cites document without structural element
        res = self.eig.assess_evidence("СП 60.13330 общие положения")
        self.assertEqual(res.query_applicability, "DOCUMENT_OVERVIEW")
        self.assertEqual(res.answer_evidence_status, "NOT_APPLICABLE")
        self.assertIn("abstains", res.verification_reason.lower())

    def test_topic_not_evaluated_when_topic_absent(self):
        res = self.eig.assess_evidence("СП 7.13130 пункт 6.4")
        self.assertEqual(res.topic_alignment, "TOPIC_NOT_EVALUATED")
        self.assertEqual(res.answer_evidence_status, "USABLE_FOR_ANSWER")

    def test_topic_uncertain_does_not_fatal_refusal(self):
        status, reason = self.eig.verify_topic_alignment(
            certified_text="Текст пункта о вентиляции и противопожарных клапанах",
            query_topic="космический телескоп астрономия",
            element_id="6.4",
            doc_base="СП 7.13130"
        )
        self.assertEqual(status, "TOPIC_UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
