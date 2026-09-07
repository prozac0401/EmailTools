from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "eml_attachment_tool" / "app.py"
RUN_BAT = REPO_ROOT / "eml_attachment_tool" / "run.bat"
EMBEDDED_PYTHON = REPO_ROOT / "runtime" / "python" / "python.exe"
SPEC = importlib.util.spec_from_file_location("eml_attachment_tool_app", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


def zip_bytes(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            data = value.encode("utf-8") if isinstance(value, str) else value
            archive.writestr(name, data)
    return buffer.getvalue()


def docx_bytes() -> bytes:
    return zip_bytes(
        {
            "word/document.xml": (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>DOCX 본문</w:t></w:r></w:p></w:body></w:document>"
            )
        }
    )


def xlsx_bytes() -> bytes:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    return zip_bytes(
        {
            "xl/workbook.xml": (
                f'<workbook xmlns="{namespace}" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="결과" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                f'<Relationships xmlns="{rel_namespace}">'
                '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": (
                f'<worksheet xmlns="{namespace}"><sheetData><row r="1">'
                '<c r="A1" t="inlineStr"><is><t>XLSX 값</t></is></c>'
                "</row></sheetData></worksheet>"
            ),
        }
    )


def pptx_bytes() -> bytes:
    return zip_bytes(
        {
            "ppt/slides/slide1.xml": (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                "<p:cSld><a:t>PPTX 슬라이드</a:t></p:cSld></p:sld>"
            )
        }
    )


def pdf_bytes() -> bytes:
    content = b"BT /F1 12 Tf 72 720 Td (PDF attachment text) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


class EmlAttachmentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="EmailTools_test_")
        self.root = Path(self.temp_dir.name)
        self.output = self.root / app.OUTPUT_DIR_NAME

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def process(self, message: EmailMessage, filename: str = "sample.eml"):
        eml_path = self.root / filename
        eml_path.write_bytes(message.as_bytes(policy=SMTP))
        count, records, error = app.process_eml(eml_path, self.root, self.output)
        mail_dir = self.output / app.safe_name(eml_path.stem, "mail")
        return count, records, error, mail_dir

    def basic_message(self, subject: str = "Synthetic test") -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = "sender@example.com"
        message["To"] = "receiver@example.com"
        return message

    def test_plain_text_eml_without_attachments(self) -> None:
        message = self.basic_message()
        message.set_content("plain body")
        count, records, error, mail_dir = self.process(message, "plain.eml")
        self.assertEqual((count, records, error), (0, [], None))
        self.assertIn("plain body", (mail_dir / "_mail.txt").read_text(encoding="utf-8-sig"))

    def test_html_eml_and_inline_attachment(self) -> None:
        message = self.basic_message()
        message.set_content("plain alternative")
        message.add_alternative("<html><body><h1>HTML 제목</h1><script>ignore()</script></body></html>", subtype="html")
        html_part = message.get_payload()[-1]
        html_part.add_related(
            b"inline bytes",
            maintype="application",
            subtype="octet-stream",
            filename="inline.js",
            disposition="inline",
            cid="inline-test",
        )
        count, records, error, mail_dir = self.process(message, "html.eml")
        self.assertIsNone(error)
        self.assertEqual(count, 1)
        self.assertEqual(records[0].attachment_name, "inline.js")
        mail_text = (mail_dir / "_mail.txt").read_text(encoding="utf-8-sig")
        self.assertIn("plain alternative", mail_text)
        self.assertNotIn("ignore()", mail_text)

    def test_korean_rfc2047_headers_and_cp949_body(self) -> None:
        raw = (
            b"Subject: =?UTF-8?B?7ZWc6riAIOygnOuqqQ==?=\r\n"
            b"From: =?UTF-8?B?67Cc7Iah7J6Q?= <sender@example.com>\r\n"
            b"To: receiver@example.com\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain; charset=cp949\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n\r\n"
            + "CP949 본문".encode("cp949")
        )
        eml_path = self.root / "korean.eml"
        eml_path.write_bytes(raw)
        count, records, error = app.process_eml(eml_path, self.root, self.output)
        self.assertEqual((count, records, error), (0, [], None))
        text = (self.output / "korean" / "_mail.txt").read_text(encoding="utf-8-sig")
        self.assertIn("한글 제목", text)
        self.assertIn("CP949 본문", text)

    def test_korean_text_attachment(self) -> None:
        message = self.basic_message("한글 첨부 테스트")
        message.set_content("body")
        message.add_attachment(
            "첨부 내용".encode("cp949"),
            maintype="text",
            subtype="plain",
            filename="결과 보고서.txt",
        )
        count, records, error, mail_dir = self.process(message)
        self.assertEqual(count, 1)
        self.assertIsNone(error)
        self.assertEqual(records[0].attachment_name, "결과 보고서.txt")
        extracted = mail_dir / app.TEXT_DIR_NAME / "결과 보고서.txt.txt"
        self.assertIn("첨부 내용", extracted.read_text(encoding="utf-8-sig"))

    def test_office_and_pdf_attachments(self) -> None:
        message = self.basic_message()
        message.set_content("body")
        attachments = [
            (docx_bytes(), "application", "vnd.openxmlformats-officedocument.wordprocessingml.document", "sample.docx", "DOCX 본문"),
            (xlsx_bytes(), "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet", "sample.xlsx", "XLSX 값"),
            (pptx_bytes(), "application", "vnd.openxmlformats-officedocument.presentationml.presentation", "sample.pptx", "PPTX 슬라이드"),
            (pdf_bytes(), "application", "pdf", "sample.pdf", "PDF attachment text"),
        ]
        for data, maintype, subtype, filename, _ in attachments:
            message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
        count, records, error, mail_dir = self.process(message, "documents.eml")
        self.assertEqual(count, 4)
        self.assertIsNone(error)
        self.assertEqual({record.text_status for record in records}, {"docx", "xlsx", "pptx", "pdf"})
        for _, _, _, filename, expected in attachments:
            text = (mail_dir / app.TEXT_DIR_NAME / f"{filename}.txt").read_text(encoding="utf-8-sig")
            self.assertIn(expected, text)

    def test_nested_eml_attachment(self) -> None:
        nested = self.basic_message("Nested subject")
        nested.set_content("nested body")
        outer = self.basic_message("Outer subject")
        outer.set_content("outer body")
        outer.add_attachment(nested, filename="nested.eml")
        count, records, error, mail_dir = self.process(outer, "nested_outer.eml")
        self.assertEqual(count, 1)
        self.assertIsNone(error)
        self.assertEqual(records[0].text_status, "eml")
        nested_text = (mail_dir / app.TEXT_DIR_NAME / "nested.eml.txt").read_text(encoding="utf-8-sig")
        self.assertIn("Nested subject", nested_text)
        self.assertIn("nested body", nested_text)

    def test_duplicate_attachment_names(self) -> None:
        message = self.basic_message()
        message.set_content("body")
        for value in (b"first", b"second", b"third"):
            message.add_attachment(value, maintype="text", subtype="plain", filename="same.txt")
        count, records, error, _ = self.process(message, "duplicates.eml")
        self.assertEqual(count, 3)
        self.assertIsNone(error)
        self.assertEqual(
            [record.attachment_name for record in records],
            ["same.txt", "same (1).txt", "same (2).txt"],
        )

    def test_attachment_path_traversal_is_confined_and_never_executed(self) -> None:
        message = self.basic_message()
        message.set_content("body")
        candidates = [
            (r"..\..\evil.exe", b"not an executable"),
            (r"C:\Temp\evil.bat", b"echo should-not-run"),
            ("/absolute/payload.js", b"throw new Error('should-not-run')"),
        ]
        for filename, data in candidates:
            message.add_attachment(data, maintype="application", subtype="octet-stream", filename=filename)
        count, records, error, mail_dir = self.process(message, "traversal.eml")
        self.assertEqual(count, 3)
        self.assertIsNone(error)
        attachments_dir = (mail_dir / "attachments").resolve()
        self.assertEqual(
            [record.attachment_name for record in records],
            ["evil.exe", "evil.bat", "payload.js"],
        )
        for record, (_, expected_data) in zip(records, candidates):
            saved = Path(record.saved_path).resolve()
            self.assertEqual(saved.parent, attachments_dir)
            self.assertEqual(saved.read_bytes(), expected_data)
        self.assertFalse((self.root / "evil.exe").exists())

    def test_malformed_mime_is_reported_without_aborting(self) -> None:
        eml_path = self.root / "malformed.eml"
        eml_path.write_bytes(
            b"Subject: malformed\r\nMIME-Version: 1.0\r\n"
            b"Content-Type: multipart/mixed; boundary=missing\r\n\r\n"
            b"This body has no matching MIME boundary."
        )
        count, records, error = app.process_eml(eml_path, self.root, self.output)
        self.assertEqual((count, records, error), (0, [], None))
        self.assertTrue((self.output / "malformed" / "_mail.txt").is_file())

    @unittest.skipUnless(EMBEDDED_PYTHON.is_file(), "embedded Python is not configured")
    def test_run_bat_drag_drop_argument_from_unrelated_unicode_directory(self) -> None:
        working_dir = self.root / "다른 작업 폴더"
        working_dir.mkdir()
        message = self.basic_message("run.bat argument")
        message.set_content("batch argument body")
        input_root = self.root / "메일 입력 폴더"
        nested_input = input_root / "하위 폴더"
        nested_input.mkdir(parents=True)
        eml_path = nested_input / "드래그 테스트.eml"
        eml_path.write_bytes(message.as_bytes(policy=SMTP))
        command = f'cmd.exe /d /c call "{RUN_BAT}" "{input_root}"'
        result = subprocess.run(
            command,
            cwd=working_dir,
            input="\n",
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(EMBEDDED_PYTHON), result.stdout)
        self.assertTrue(
            (
                input_root
                / app.OUTPUT_DIR_NAME
                / "하위 폴더"
                / "드래그 테스트"
                / "_mail.txt"
            ).is_file()
        )

    @unittest.skipUnless(EMBEDDED_PYTHON.is_file(), "embedded Python is not configured")
    def test_run_bat_console_path_input(self) -> None:
        working_dir = self.root / "console cwd"
        working_dir.mkdir()
        message = self.basic_message("run.bat console")
        message.set_content("batch console body")
        eml_path = self.root / "console input.eml"
        eml_path.write_bytes(message.as_bytes(policy=SMTP))
        command = f'cmd.exe /d /c call "{RUN_BAT}"'
        result = subprocess.run(
            command,
            cwd=working_dir,
            input=f'"{eml_path}"\n\n',
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("batch console body", (self.output / "console input" / "_mail.txt").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
