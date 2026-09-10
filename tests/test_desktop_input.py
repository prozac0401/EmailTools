"""Input event regressions, using synthetic files and Qt's event dispatcher."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import emailtools  # Configure the embedded Qt module path.
from emailtools.demo import create_demo
from emailtools.desktop.app import Window
from PySide6.QtCore import Qt, QUrl, QMimeData, QPoint, QPointF
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtTest import QTest


class DesktopInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="EmailTools_input_test_")
        self.source = Path(self.temp.name) / "한글 메일 & 공백 ! (검증)"
        self.source.mkdir()
        create_demo(self.source)
        self.files = sorted(self.source.glob("*.eml"))
        self.files[0] = self.files[0].rename(self.files[0].with_suffix(".EML"))
        nested = self.source / "하위 폴더"
        nested.mkdir()
        self.files[1] = self.files[1].rename(nested / self.files[1].name)
        self.window = Window(remember=False)
        self.window.show()
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

    def click(self, text):
        self.app.processEvents()
        target = next(b for b in self.window.findChildren(QPushButton)
                      if b.text() == text and b.isVisible())
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def analyze(self):
        self.window.primary.click()
        deadline = time.monotonic() + 20
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.phase_label.text(), "작업 완료 100%")
        self.assertEqual(len(self.window.result.mails), 3)
        self.assertEqual(self.window.result.failures, 0)
        self.assertEqual({m.source_path for m in self.window.result.mails}, set(self.files))

    def test_picker_results_read_korean_paths_and_nested_uppercase_files(self):
        # The native dialog is a boundary: test the button and returned paths,
        # without pretending this drives the Windows shell dialog itself.
        with patch("emailtools.desktop.app.QFileDialog.getOpenFileNames",
                   return_value=([str(p) for p in self.files], "")) as picker:
            self.click("EML 파일 선택")
            picker.assert_called_once()
        self.assertEqual([Path(p) for p in self.window.sources], self.files)
        self.analyze()
        self.window.show_page(0)
        with patch("emailtools.desktop.app.QFileDialog.getExistingDirectory",
                   return_value=str(self.source)) as picker:
            self.click("폴더 선택")
            picker.assert_called_once()
        self.assertEqual([Path(p) for p in self.window.sources], [self.source])
        self.analyze()

    def test_drag_movement_remains_accepted_before_drop_and_analysis(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in self.files])
        for event in (
            QDragEnterEvent(QPoint(30, 30), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
            QDragMoveEvent(QPoint(45, 45), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
            QDropEvent(QPointF(45, 45), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
        ):
            QApplication.sendEvent(self.window.drop, event)
            self.assertTrue(event.isAccepted(), type(event).__name__)
        self.assertEqual([Path(p) for p in self.window.sources], self.files)
        self.analyze()

    def test_multiple_explorer_copy_as_path_values_are_separate_files(self):
        for separator in ("\r\n", " "):
            with self.subTest(separator=repr(separator)):
                edit = self.window.path_edit
                edit.setFocus()
                edit.selectAll()
                edit.insert(separator.join(f'"{p}"' for p in self.files))
                QTest.keyClick(edit, Qt.Key.Key_Tab)
                self.assertEqual([Path(p) for p in self.window.sources], self.files)
                self.analyze()
                self.window.show_page(0)
                self.app.processEvents()

    def test_missing_file_is_rejected_before_starting_worker(self):
        missing = self.source / "없는 메일.eml"
        edit = self.window.path_edit
        edit.setFocus()
        edit.insert(str(missing))
        QTest.keyClick(edit, Qt.Key.Key_Tab)
        self.assertFalse(self.window.primary.isEnabled())
        self.assertIsNone(self.window.worker)
        self.assertIn("찾을 수 없", self.window.footer_hint.text())

    def test_cancelled_picker_preserves_selection(self):
        self.window.accept_paths([str(self.source)])
        with patch("emailtools.desktop.app.QFileDialog.getOpenFileNames", return_value=([], "")):
            self.click("EML 파일 선택")
        self.assertEqual([Path(p) for p in self.window.sources], [self.source])

    def test_remote_url_is_rejected(self):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/mail.eml")])
        event = QDragEnterEvent(QPoint(30, 30), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.window.drop, event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.sources, [])


if __name__ == "__main__":
    unittest.main()
