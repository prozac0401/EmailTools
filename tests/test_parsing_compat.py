"""Compare native extraction with the retained v2.0 parser on the same EML."""
from __future__ import annotations

import logging
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from emailtools import pipeline
from emailtools.models import ProcessingOptions
from emailtools.extractors import tables


class ParsingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="EmailTools_parser_compare_")
        self.root = Path(self.temp.name)
        self.logger = logging.Logger("parser-compat")
        self.logger.addHandler(logging.NullHandler())

    def tearDown(self):
        self.temp.cleanup()

    def mail(self, *, html=None, docx=None):
        message = EmailMessage()
        message["Subject"] = "동일 원본 비교"
        message["From"] = "sender@example.com"
        message.set_content("본문")
        if html is not None:
            message.add_alternative(html, subtype="html")
        if docx is not None:
            message.add_attachment(docx, maintype="application",
                subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename="신청서.docx")
        path = self.root / "compare.eml"
        path.write_bytes(message.as_bytes())
        return path

    def compare(self, path, **options):
        legacy_options = ProcessingOptions(**options)
        legacy = pipeline.analyze(path, legacy_options, self.root / "legacy", self.logger)
        native = pipeline.analyze(path, replace(legacy_options, mail_index=True), self.root / "native", self.logger)
        return legacy, native

    def docx(self, cells):
        xml = ('<w:document xmlns:w="' + tables.WORD_NS + '"><w:body><w:tbl><w:tr>'
               + cells + '</w:tr></w:tbl></w:body></w:document>')
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("word/document.xml", xml.encode("utf-8"))
        return stream.getvalue()

    def test_word_cell_content_controls_keep_fields_and_values(self):
        cells = ''.join('<w:tc><w:sdt><w:sdtPr/><w:sdtContent><w:p><w:r><w:t>' + text +
                        '</w:t></w:r></w:p></w:sdtContent></w:sdt></w:tc>' for text in ("교육명", "과정 A"))
        legacy, native = self.compare(self.mail(docx=self.docx(cells)))
        self.assertEqual(legacy.records[0]["교육명"], "과정 A")
        self.assertEqual(native.records[0].get("교육명"), legacy.records[0]["교육명"])
        self.assertEqual(len(native.catalog.fields), 1)

    def test_word_line_breaks_tabs_and_field_instructions_match_existing_values(self):
        cells = ('<w:tc><w:p><w:r><w:t>주요 의견</w:t></w:r></w:p></w:tc>'
                 '<w:tc><w:p><w:r><w:instrText> MERGEFIELD Review </w:instrText></w:r>'
                 '<w:r><w:t>첫째</w:t><w:br/><w:t>둘째</w:t><w:tab/><w:t>셋째</w:t></w:r></w:p></w:tc>')
        legacy, native = self.compare(self.mail(docx=self.docx(cells)))
        self.assertEqual(legacy.records[0]["주요 의견"], "첫째\n둘째 셋째")
        self.assertEqual(native.records[0].get("주요 의견"), legacy.records[0]["주요 의견"])

    def test_html_list_and_paragraph_boundaries_match_existing_values(self):
        for value in ('<ul><li>첫째</li><li>둘째</li></ul>', '<p>첫째</p>둘째'):
            with self.subTest(value=value):
                legacy, native = self.compare(self.mail(html='<table><tr><td>주요 의견</td><td>' + value + '</td></tr></table>'))
                self.assertEqual(legacy.records[0]["주요 의견"], "첫째\n둘째")
                self.assertEqual(native.records[0].get("주요 의견"), legacy.records[0]["주요 의견"])

    def test_bad_docx_table_does_not_prevent_original_attachment_save(self):
        legacy, native = self.compare(self.mail(docx=b"damaged document"), save_attachments=True, extract_text=True)
        self.assertEqual(legacy.mails[0].attachments[0].payload_path.read_bytes(), b"damaged document")
        attachment = native.mails[0].attachments[0]
        self.assertIsNotNone(attachment.payload_path)
        self.assertEqual(attachment.payload_path.read_bytes(), b"damaged document")
        self.assertNotEqual(attachment.text_status, "not requested")
        self.assertIn("BadZipFile", attachment.error)

    def test_word_content_controls_do_not_duplicate_nested_table_values(self):
        paragraph = lambda text: '<w:p><w:r><w:t>' + text + '</w:t></w:r></w:p>'
        inner = ('<w:tbl><w:tr><w:tc>' + paragraph("내부 항목") + '</w:tc><w:tc>'
                 + paragraph("내부 값") + '</w:tc></w:tr></w:tbl>')
        cells = ('<w:tc><w:sdt><w:sdtContent>' + paragraph("외부 항목") + inner
                 + '</w:sdtContent></w:sdt></w:tc><w:tc>' + paragraph("외부 값") + '</w:tc>')
        _, native = self.compare(self.mail(docx=self.docx(cells)))
        self.assertEqual(native.records[0]["외부 항목"], "외부 값")
        self.assertEqual(native.records[0]["내부 항목"], "내부 값")
        self.assertEqual(len(native.catalog.tables), 2)
        self.assertEqual(sum(len(entries) for entries in native.catalog.occurrences.values()), 2)

    def test_existing_common_html_shapes_keep_extracted_fields(self):
        for html in (
            '<table><tr><td>교육명</td><td>과정 A</td></tr></table>',
            '<TABLE><TR><TD>교육명<TD>과정 A<TR><TD>강사<TD>홍길동</TABLE>',
            '<table><tr><td>교육명</td><td>과정 A</td>',
            '<table><tr><td>교육명</td><td>과정 A</td><td>강사</td><td>홍길동</td></tr></table>',
            '<table><tr><td>주요 의견</td><td>첫째<br/>둘째</td></tr></table>',
        ):
            with self.subTest(html=html):
                legacy, native = self.compare(self.mail(html=html))
                expected = {key: value for key, value in legacy.records[0].items() if key not in tables.SYSTEM_COLUMNS}
                actual = {key: value for key, value in native.records[0].items() if key not in tables.SYSTEM_COLUMNS}
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
