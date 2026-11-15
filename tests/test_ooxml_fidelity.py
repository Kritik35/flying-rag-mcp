"""
tests/test_ooxml_fidelity.py

Independent fixture test for OOXML OMML (<m:oMath>) formula ingestion fidelity (Blocker P1-05):
1. Proves that Office Open XML mathematical equations (<m:oMath> / <m:t>) are present in original DOCX.
2. Proves that standard python-docx paragraph extraction (parsers/office.py) inspects only <w:t>,
   dropping <m:oMath> content while retaining adjacent plain text labels like "(А.3)".
3. Proves that EIG stitcher.check_formula_integrity() correctly detects this ingestion loss,
   returning FORMULA_MISSING and preventing silent false-certification of incomplete formulas.
"""
from __future__ import annotations
import zipfile
import tempfile
import unittest
from pathlib import Path

from parsers.office import _parse_docx
from evidence_gate.stitcher import check_formula_integrity


DOC_XML_WITH_OMML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <w:body>
    <w:p><w:r><w:t>Приложение А. Расчет параметров противодымной вентиляции.</w:t></w:r></w:p>
    <w:p><w:r><w:t>А.3 Расход удаляемых продуктов горения определяется по формуле (А.3):</w:t></w:r></w:p>
    <w:p>
      <m:oMath>
        <m:r><m:t>G = 1.2 * A * sqrt(h)</m:t></m:r>
      </m:oMath>
    </w:p>
    <w:p><w:r><w:t>(А.3)</w:t></w:r></w:p>
    <w:p><w:r><w:t>где А - площадь, м2; h - высота, м.</w:t></w:r></w:p>
  </w:body>
</w:document>"""

DOC_XML_WITH_TEXT_EQUATION = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Приложение А. Расчет параметров противодымной вентиляции.</w:t></w:r></w:p>
    <w:p><w:r><w:t>А.3 Расход удаляемых продуктов горения определяется по формуле (А.3):</w:t></w:r></w:p>
    <w:p><w:r><w:t>G = 1.2 * A * sqrt(h)</w:t></w:r></w:p>
    <w:p><w:r><w:t>(А.3)</w:t></w:r></w:p>
    <w:p><w:r><w:t>где А - площадь, м2; h - высота, м.</w:t></w:r></w:p>
  </w:body>
</w:document>"""

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _create_docx(target_path: Path, doc_xml: str):
    with zipfile.ZipFile(target_path, "w") as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("word/document.xml", doc_xml)


class OoxmlFidelityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_raw_docx_contains_omml_math_tags(self):
        # 1. Verify original DOCX XML contains the physical <m:oMath> element
        docx_file = self.temp_path / "formula_omml.docx"
        _create_docx(docx_file, DOC_XML_WITH_OMML)

        with zipfile.ZipFile(docx_file, "r") as zf:
            raw_xml = zf.read("word/document.xml").decode("utf-8")

        self.assertIn("<m:oMath>", raw_xml)
        self.assertIn("G = 1.2 * A * sqrt(h)", raw_xml)
        self.assertIn("(А.3)", raw_xml)

    def test_ooxml_omml_dropped_at_parser_ingestion_and_detected_by_eig(self):
        # 2. Ingest through parsers.office._parse_docx()
        docx_file = self.temp_path / "formula_omml.docx"
        _create_docx(docx_file, DOC_XML_WITH_OMML)

        extracted_text, meta = _parse_docx(docx_file)

        # OMML equation text is discarded because python-docx iterates only w:t tags
        self.assertNotIn("G = 1.2 * A * sqrt(h)", extracted_text)
        # But the label paragraph "(А.3)" survives
        self.assertIn("(А.3)", extracted_text)

        # 3. Check formula integrity via stitcher
        status, missing = check_formula_integrity(extracted_text)
        self.assertEqual(status, "FORMULA_MISSING")
        self.assertEqual(missing, ["(А.3)"])

    def test_text_represented_equation_verified_successfully(self):
        # When equation is in standard w:t tags, formula is verified
        docx_file = self.temp_path / "formula_text.docx"
        _create_docx(docx_file, DOC_XML_WITH_TEXT_EQUATION)

        extracted_text, meta = _parse_docx(docx_file)
        self.assertIn("G = 1.2 * A * sqrt(h)", extracted_text)
        self.assertIn("(А.3)", extracted_text)

        status, missing = check_formula_integrity(extracted_text)
        self.assertEqual(status, "FORMULA_TEXT_PRESENT_UNVERIFIED")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
