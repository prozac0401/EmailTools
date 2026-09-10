"""Analysis-to-results transitions, including failures without a console."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import emailtools
from emailtools.demo import create_demo
from emailtools.desktop.app import Window
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication


class DesktopResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="EmailTools_results_test_")
        self.source = Path(self.temp.name) / "메일"
        self.source.mkdir()
        create_demo(self.source)
        self.window = Window(remember=False)
        self.window.show()
        self.window.accept_paths([str(self.source)])
        self.app.processEvents()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.requestInterruption()
            self.window.worker.wait(10000)
            self.app.processEvents()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def analyze(self):
        self.window.show_page(0)
        self.window.primary.click()
        deadline = time.monotonic() + 20
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window.busy)
        self.app.processEvents()

    def test_success_immediately_shows_mail_list_and_table_candidates(self):
        for mode in ("list", "analyze"):
            with self.subTest(mode=mode):
                self.window.set_mode(mode)
                original = self.window.refresh_result
                threads = []
                def refresh():
                    threads.append(QThread.currentThread())
                    original()
                with patch.object(self.window, "refresh_result", side_effect=refresh):
                    self.analyze()
                self.assertEqual(self.window.phase_label.text(), "작업 완료 100%")
                self.assertEqual(self.window.stack.currentIndex(), 1)
                self.assertEqual(threads, [self.app.thread()])
                self.assertEqual(self.window.mail_table.model().rowCount(), 3)
                if mode == "list":
                    self.assertTrue(self.window.mail_table.isVisible())
                else:
                    self.assertTrue(self.window.candidates.isVisible())
                    self.assertGreater(self.window.candidates.count(), 0)

    def test_new_input_does_not_inherit_filters_that_hide_all_results(self):
        self.window.set_mode("analyze")
        self.analyze()
        self.window.mail_search.setText("일치하지 않는 이전 검색")
        self.window.attachment_search.setText("일치하지 않는 이전 검색")
        self.window.field_search.setText("일치하지 않는 이전 검색")
        self.window.mail_status.setCurrentIndex(1)
        self.assertEqual(self.window.mail_table.model().rowCount(), 0)
        other = Path(self.temp.name) / "새 메일"
        other.mkdir()
        create_demo(other)
        self.window.show_page(0)
        self.window.accept_paths([str(other)])
        self.analyze()
        self.assertEqual(self.window.mail_table.model().rowCount(), 3)
        self.assertGreater(self.window.candidates.count(), 0)
        self.assertEqual(self.window.mail_search.text(), "")

    def test_result_render_failure_is_visible_and_never_publishes_partial_result(self):
        with patch.object(self.window, "refresh_result", side_effect=RuntimeError("render regression")):
            self.analyze()
        self.assertEqual(self.window.stack.currentIndex(), 3)
        self.assertIn("실패", self.window.phase_label.text())
        self.assertIn("render regression", self.window.last_error)
        self.assertIsNone(self.window.result)
        self.assertTrue(self.window.error_button.isVisible())
        self.assertIn("render regression", self.window.log_path.read_text(encoding="utf-8"))

    def test_failed_reanalysis_keeps_previous_result_and_stays_on_error(self):
        self.analyze()
        previous = self.window.result
        with patch("emailtools.desktop.app.pipeline.analyze", side_effect=PermissionError("메일 접근 거부")):
            self.analyze()
        self.assertIs(self.window.result, previous)
        self.assertEqual(self.window.stack.currentIndex(), 3)
        self.assertIn("실패", self.window.phase_label.text())
        self.assertIn("메일 접근 거부", self.window.progress_detail.text())

    def test_render_failure_preserves_previous_attachment_spool_and_columns(self):
        self.window.set_mode("analyze")
        self.analyze()
        self.window.add_common()
        previous = self.window.result
        previous_spool = self.window.active_spool
        previous_columns = self.window.columns[:]
        payloads = [a.payload_path for m in previous.mails for a in m.attachments]
        original = self.window.refresh_result
        calls = []
        def fail_once():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("화면 반영 실패")
            original()
        with patch.object(self.window, "refresh_result", side_effect=fail_once):
            self.analyze()
        self.assertIs(self.window.result, previous)
        self.assertEqual(self.window.active_spool, previous_spool)
        self.assertEqual(self.window.columns, previous_columns)
        self.assertTrue(all(p.is_file() for p in payloads))
        self.assertEqual(list(self.window.root.glob("analysis-*")), [previous_spool])
        self.assertIn("실패", self.window.phase_label.text())

    def test_no_tables_explains_empty_candidates_but_mail_list_exists(self):
        message = EmailMessage()
        message["Subject"] = "표 없는 메일"
        message.set_content("일반 텍스트 본문입니다.")
        path = Path(self.temp.name) / "plain.eml"
        path.write_bytes(message.as_bytes())
        self.window.accept_paths([str(path)])
        self.window.set_mode("analyze")
        self.analyze()
        self.assertEqual(self.window.mail_table.model().rowCount(), 1)
        self.assertIn("표를 찾지 못", self.window.empty_candidates.text())
        self.assertTrue(self.window.empty_candidates.isVisible())


if __name__ == "__main__":
    unittest.main()
