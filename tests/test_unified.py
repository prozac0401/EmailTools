from __future__ import annotations

import csv
import itertools
import json
import logging
import sys
import tempfile
import threading
import unittest
import zipfile
from email.message import EmailMessage
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from emailtools import pipeline, reader
from emailtools.exporters import files as exporter
from emailtools.extractors import text
from emailtools.models import ProcessingOptions
from emailtools.table_config import default_columns
from emailtools.ui.server import Workspace
from test_table_to_excel import docx_table_bytes, write_eml
from openpyxl import load_workbook


class UnifiedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="EmailTools_unified_")
        self.root = Path(self.temp.name)
        self.source = self.root / "메일 입력"
        self.source.mkdir()
        self.output = self.root / "결과"
        self.logger = logging.Logger("unified-test", logging.INFO)
        self.log = StringIO()
        self.handler = logging.StreamHandler(self.log)
        self.logger.addHandler(self.handler)
        self.payloads = [
            ("평가.docx", docx_table_bytes([["평가", "만족"]])),
            ("중복.txt", "첫 번째 텍스트".encode("utf-8")),
            ("중복.txt", "두 번째 텍스트".encode("utf-8")),
            ("../../command.bat", b"echo never execute"),
        ]
        msg = EmailMessage()
        msg["Subject"] = "=UNTRUSTED()"
        msg["From"] = "sender@example.com"
        msg.set_content("메일 본문")
        msg.add_alternative("<table><tr><td>교육명</td><td>통합 테스트</td></tr></table>", subtype="html")
        for name, payload in self.payloads:
            msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename=name)
        self.mail_path = self.source / "메일.EML"
        self.mail_path.write_bytes(msg.as_bytes())

    def tearDown(self):
        self.handler.close()
        self.temp.cleanup()

    def analyze(self, options=ProcessingOptions()):
        return pipeline.analyze(self.source, options, self.root / "spool", self.logger)

    def export(self, result, **kwargs):
        return exporter.export_results(result, self.output, self.logger, get_log=self.log.getvalue, **kwargs)

    def test_all_15_feature_combinations_preserve_input_and_only_save_requested_files(self):
        before = self.mail_path.read_bytes()
        for flags in itertools.product((False, True), repeat=4):
            if not any(flags):
                continue
            with self.subTest(flags=flags):
                options = ProcessingOptions(*flags)
                result = self.analyze(options)
                folder = self.export(result)
                self.assertEqual(len(list(folder.rglob("mail.txt"))), int(options.save_mail))
                originals = [p for p in folder.rglob("*") if p.is_file() and p.parent.name == "attachments"]
                self.assertEqual(len(originals), 4 if options.save_attachments else 0)
                if originals:
                    self.assertCountEqual([p.read_bytes() for p in originals], [v for _, v in self.payloads])
                    self.assertTrue(all(p.resolve().is_relative_to(folder) for p in originals))
                texts = [p for p in folder.rglob("*") if p.is_file() and p.parent.name == "text"]
                self.assertEqual(len(texts), 3 if options.extract_text else 0)
                self.assertEqual((folder / "tables/EML_Table_Result.xlsx").exists(), options.extract_tables)
                self.assertTrue((folder / "summary.csv").is_file())
                self.assertTrue((folder / "processing.log").is_file())
                self.assertEqual(self.mail_path.read_bytes(), before)
                self.assertEqual(list(self.source.iterdir()), [self.mail_path])

    def test_eml_and_payload_are_read_once_when_all_features_are_selected(self):
        with patch.object(reader, "read_message", wraps=reader.read_message) as parse, \
             patch.object(reader, "attachment_bytes", wraps=reader.attachment_bytes) as decode:
            result = self.analyze(ProcessingOptions(True, True, True, True))
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(decode.call_count, 4)
        self.assertEqual(result.records[0]["평가"], "만족")
        self.assertIn("만족", result.mails[0].attachments[0].text)

    def test_text_and_table_only_never_spool_original_attachments(self):
        self.analyze(ProcessingOptions(False, False, True, True))
        self.assertFalse((self.root / "spool").exists())
        self.assertFalse(self.output.exists())

    def test_table_sources_are_independent_and_unselected_sources_do_not_warn(self):
        for email, docx in [(True, False), (False, True), (True, True)]:
            result = self.analyze(ProcessingOptions(email_tables=email, docx_tables=docx))
            self.assertEqual("교육명" in result.columns, email)
            self.assertEqual("평가" in result.columns, docx)
            self.assertEqual(result.records[0]["_status"], "OK")

    def test_nested_mail_data_does_not_leak_into_parent_body_tables_or_attachments(self):
        nested = EmailMessage()
        nested["Subject"] = "Nested"
        nested.set_content("NESTED_BODY")
        nested.add_alternative("<table><tr><td>NESTED_FIELD</td><td>nested</td></tr></table>", subtype="html")
        nested.add_attachment(b"inner", maintype="application", subtype="octet-stream", filename="inner.txt")
        parent = EmailMessage()
        parent["Subject"] = "Parent"
        parent.set_content("PARENT_BODY")
        parent.add_attachment(nested, filename="nested.eml")
        self.mail_path.write_bytes(parent.as_bytes())
        result = self.analyze(ProcessingOptions(True, True, True, True))
        self.assertEqual(result.attachment_count, 1)
        self.assertNotIn("NESTED_FIELD", result.columns)
        self.assertNotIn("NESTED_BODY", result.mails[0].body)
        self.assertIn("NESTED_BODY", result.mails[0].attachments[0].text)

    def test_errors_in_one_mail_do_not_abort_other_mail_or_successful_extractors(self):
        bad = self.source / "bad.eml"
        write_eml(bad, subject="Bad DOCX", email_rows=[["유효", "유지"]], docx_rows=None, docx_payload=b"bad zip")
        missing = self.source / "denied.eml"
        missing.write_bytes(b"Subject: denied\n\nbody")
        actual_read = reader.read_message
        def read(path):
            if path == missing:
                raise PermissionError("synthetic access failure")
            return actual_read(path)
        with patch.object(reader, "read_message", side_effect=read):
            result = self.analyze(ProcessingOptions(True, True, True, True))
        self.assertEqual((result.success, result.warnings, result.failures), (1, 1, 1))
        self.assertEqual(next(r for r in result.records if r["source_eml"] == "bad.eml")["유효"], "유지")
        folder = self.export(result)
        self.assertIn("synthetic access failure", (folder / "processing.log").read_text(encoding="utf-8-sig"))
        self.assertTrue(any(p.read_bytes() == b"bad zip" for p in folder.rglob("*.docx")))

    def test_export_uses_analyzed_bytes_even_if_input_changes_and_each_run_is_unique(self):
        result = self.analyze(ProcessingOptions(True, True, True, True))
        self.mail_path.write_bytes(b"Subject: Changed\n\nDifferent mail")
        first, second = self.export(result), self.export(result)
        self.assertNotEqual(first, second)
        self.assertCountEqual([p.read_bytes() for p in first.rglob("*") if p.is_file() and p.parent.name == "attachments"],
                             [v for _, v in self.payloads])
        self.assertIn("메일 본문", next(first.rglob("mail.txt")).read_text(encoding="utf-8-sig"))

    def test_failed_export_does_not_publish_partial_job_or_modify_previous_result(self):
        result = self.analyze(ProcessingOptions(True, True, True, True))
        first = self.export(result)
        before = {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()}
        with patch.object(exporter, "write_excel", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.export(result)
        self.assertEqual(list(self.output.iterdir()), [first])
        self.assertEqual({p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()}, before)

    def test_output_folders_and_archives_are_not_rescanned(self):
        result = self.analyze(ProcessingOptions(True, True, False, False))
        folder = exporter.export_results(result, self.source / "results", self.logger, archive=True)
        (folder / "exported.eml").write_bytes(self.mail_path.read_bytes())
        legacy = self.source / "_EML_OUTPUT"
        legacy.mkdir()
        (legacy / "old.eml").write_bytes(b"old")
        with zipfile.ZipFile(folder / exporter.ARCHIVE_FILENAME) as archive:
            self.assertIn(reader.JOB_MARKER, archive.namelist())
            self.assertNotIn(exporter.ARCHIVE_FILENAME, archive.namelist())
            self.assertIsNone(archive.testzip())
        _, files = reader.find_eml_targets(self.source)
        self.assertEqual(files, [self.mail_path])

    def test_csv_metadata_cannot_be_interpreted_as_formula(self):
        folder = self.export(self.analyze())
        with (folder / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["subject"], "'=UNTRUSTED()")

    def test_invalid_options_are_rejected(self):
        for value in [{"extract_tables": False}, {"unknown": True}, {"save_mail": 1},
                      {"email_tables": False, "docx_tables": False}, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ProcessingOptions.from_dict(value)

    def test_oversized_office_xml_is_reported_without_aborting_other_features(self):
        with patch.object(text, "MAX_OFFICE_XML_BYTES", 10):
            result = self.analyze(ProcessingOptions(True, True, True, True))
        self.assertEqual(result.records[0]["평가"], "만족")
        self.assertIn("Office XML exceeds", result.records[0]["_error"])
        folder = self.export(result)
        self.assertTrue(any(p.name == "평가.docx" for p in folder.rglob("*.docx")))

    def test_legacy_table_defensive_error_boundary_still_produces_failure_record(self):
        from emailtools.compat import tables as legacy
        with patch.object(legacy, "process_eml_record", side_effect=RuntimeError("synthetic unexpected error")):
            result = legacy.scan_source(self.source, self.logger)
        self.assertEqual(result.failures, 1)
        self.assertEqual(result.records[0]["source_eml"], "메일.EML")

    def test_cancellation_during_discovery_produces_no_output(self):
        with self.assertRaises(InterruptedError):
            pipeline.analyze(self.source, ProcessingOptions(), self.root / "spool", self.logger,
                             is_cancelled=lambda: True)
        self.assertFalse(self.output.exists())


class UnifiedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace()

    def tearDown(self):
        self.workspace.close()

    def load(self, options):
        self.workspace.load({"demo": True, "options": options.as_dict()})
        self.workspace.worker.join(timeout=10)
        self.assertEqual(self.workspace.phase, "ready")
        return self.workspace.snapshot()

    def test_no_table_mode_supports_details_and_archive_without_columns(self):
        state = self.load(ProcessingOptions(True, True, True, False))
        self.assertEqual(state["columns"], [])
        self.assertEqual(state["attachments"], 2)
        req = {"dataset": state["dataset"]}
        self.assertEqual(self.workspace.details({**req, "kind": "mails"})["total"], 3)
        self.assertEqual(self.workspace.details({**req, "kind": "attachments"})["total"], 2)
        with self.assertRaises(ValueError):
            self.workspace.preview(req)
        result = self.workspace.export(req)
        self.assertTrue(result["download"].endswith("/zip"))
        self.assertIsNone(result["excel"])
        folder = Path(result["output_path"])
        self.assertFalse((folder / "tables").exists())
        self.assertEqual(len(list(folder.rglob("mail.txt"))), 3)

    def test_export_rejects_changed_options_and_preserves_loaded_dataset_on_invalid_request(self):
        state = self.load(ProcessingOptions())
        request = {"dataset": state["dataset"], "columns": default_columns(state["columns"]),
                   "options": ProcessingOptions(True, True, True, True).as_dict()}
        with self.assertRaises(ValueError):
            self.workspace.export(request)
        with self.assertRaises(ValueError):
            self.workspace.load({"demo": True, "options": {"extract_tables": False}})
        self.assertEqual(self.workspace.snapshot()["dataset"], state["dataset"])

    def test_new_dataset_releases_old_spooled_attachments_and_invalidates_requests(self):
        first = self.load(ProcessingOptions(False, True, False, False))
        old_spool = self.workspace.scan.mails[0].attachments[0].payload_path
        self.assertTrue(old_spool.is_file())
        self.load(ProcessingOptions())
        self.assertFalse(old_spool.exists())
        with self.assertRaises(ValueError):
            self.workspace.details({"dataset": first["dataset"]})

    def test_cancelled_analysis_cannot_be_exported_and_next_analysis_recovers(self):
        entered, proceed = threading.Event(), threading.Event()
        original = reader.read_message
        def delayed(path):
            entered.set()
            self.assertTrue(proceed.wait(timeout=5))
            return original(path)
        with patch.object(reader, "read_message", side_effect=delayed):
            self.workspace.load({"demo": True})
            self.assertTrue(entered.wait(timeout=5))
            self.workspace.cancel_event.set()
            proceed.set()
            self.workspace.worker.join(timeout=10)
        self.assertFalse(self.workspace.worker.is_alive())
        state = self.workspace.snapshot()
        self.assertEqual(state["phase"], "error")
        self.assertEqual(state["dataset"], "")
        self.assertIn("중지", state["error"])
        with self.assertRaises(ValueError):
            self.workspace.export({"dataset": ""})
        self.load(ProcessingOptions())

    def test_uploaded_input_can_be_reanalyzed_with_different_options(self):
        import base64
        message = EmailMessage()
        message.set_content("uploaded body")
        message.add_attachment(b"attachment body", maintype="text", subtype="plain", filename="note.txt")
        self.workspace.load({"files": [{"name": "nested/mail.eml", "data": base64.b64encode(message.as_bytes()).decode()}]})
        self.workspace.worker.join(timeout=10)
        self.assertEqual(self.workspace.phase, "ready")
        first_id = self.workspace.dataset
        self.workspace.load({"reuse": True, "options": ProcessingOptions(False, False, True, False).as_dict()})
        self.workspace.worker.join(timeout=10)
        self.assertEqual(self.workspace.phase, "ready")
        self.assertNotEqual(self.workspace.dataset, first_id)
        self.assertEqual(self.workspace.scan.mails[0].attachments[0].text, "attachment body")
        result = self.workspace.export({"dataset": self.workspace.dataset})
        folder = Path(result["output_path"])
        self.assertFalse(any(p.name == "attachments" for p in folder.rglob("*")))
        self.assertTrue(list(folder.glob("mails/*/text/*.txt")))


if __name__ == "__main__":
    unittest.main()
