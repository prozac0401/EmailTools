"""Real Qt event-loop and file-output smoke test using only synthetic mail."""
from __future__ import annotations
import json
import time
import traceback
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from openpyxl import load_workbook


def run_smoke(app, window, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "error": None}
    def settle():
        app.processEvents()
        QTest.qWait(80)
    def wait():
        deadline = time.monotonic() + 60
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert not window.busy, "Worker did not finish"
        assert window.phase_label.text() == "작업 완료 100%", window.progress_detail.text()
        settle()
    def capture(name):
        settle()
        assert window.grab().save(str(output / name))
    try:
        capture("01-start.png")
        window.load_demo()
        window.start_analysis()
        wait()
        assert len(window.result.mails) == 3
        assert all(not m.body for m in window.result.mails)
        assert all(a.size is None for m in window.result.mails for a in m.attachments)
        assert window.tabs.count() == 1
        report["checks"].append("List mode: no body/payload extraction, conditional tabs")
        window.show_page(1)
        capture("02-mail-list.png")
        window.prepare_export()
        window.output_path.setText(str(output / "list-results"))
        window.start_export()
        wait()
        assert (window.last_folder / "MailList.xlsx").exists()
        assert not (window.last_folder / "tables").exists()
        report["checks"].append("List-only XLSX and ZIP saved")
        window.show_page(0)
        window.set_mode("analyze")
        window.start_analysis()
        wait()
        assert window.tabs.count() == 4
        assert len(window.columns) == 2
        assert window.result.catalog.query()["counts"]["common"] >= 4
        window.show_page(1)
        # Drive the Qt drag event contract, including its MIME and pixmap, without
        # depending on an external desktop automation service or OS pointer.
        source_list = window.candidates
        dragged = source_list.item(0).data(Qt.ItemDataRole.UserRole)["id"]
        pos = source_list.visualItemRect(source_list.item(0)).topLeft() + QPoint(45, 20)
        def drop_at_target(drag, action):
            assert not drag.pixmap().isNull()
            target = window.selected
            point = target.visualItemRect(target.item(0)).topLeft()
            event = SimpleNamespace(mimeData=lambda: drag.mimeData(), source=lambda: source_list,
                                    position=lambda: QPointF(point), acceptProposedAction=lambda: None)
            assert target._payload(event)["id"] == dragged
            target.dragMoveEvent(event)
            target.dropEvent(event)
            return Qt.DropAction.MoveAction
        source_list.press_position = pos
        event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(pos + QPoint(30, 0)),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        with patch("emailtools.desktop.widgets.QDrag.exec", drop_at_target):
            source_list.mouseMoveEvent(event)
        assert window.columns[0]["id"] == dragged
        window.remove_field(dragged)
        assert all(c["id"] != dragged for c in window.columns)
        report["checks"].append("Qt drag event routing, MIME isolation, drag pixmap and candidate-to-selected insertion")
        window.add_common()
        first = window.columns[-1]["id"]
        window.selected.setCurrentRow(len(window.columns) - 1)
        window.selected.setFocus()
        QTest.keyClick(window.selected, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        assert window.columns[-2]["id"] == first
        selected_before_filter = [c["id"] for c in window.columns]
        window.field_search.setText("없는 항목")
        window.source_scope.setCurrentIndex(1)
        assert [c["id"] for c in window.columns] == selected_before_filter
        window.clear_filters()
        capture("03-field-review.png")
        window.columns.append(dict(id="custom:test", name="검토 상태", source=None, value="=안전한 문자열", enabled=True, custom=True))
        window.columns_changed()
        window.tabs.setCurrentWidget(window.table_page)
        header = window.preview.horizontalHeader()
        header.moveSection(header.count() - 1, 0)
        assert window.columns[0]["id"] == "custom:test"
        expected_headers = [c["name"] for c in window.columns]
        expected_rows = [[row.get(name, "") or "" for name in expected_headers] for row in window.preview.model().rows]
        capture("04-table-preview.png")
        window.prepare_export()
        window.output_path.setText(str(output / "analysis-results"))
        capture("05-save-review.png")
        window.start_export()
        wait()
        capture("06-completed.png")
        workbook = load_workbook(window.last_folder / "tables/EML_Table_Result.xlsx")
        rows = list(workbook.active.values)
        assert list(rows[0]) == expected_headers, (rows[0], expected_headers)
        assert [[v or "" for v in row] for row in rows[1:]] == expected_rows
        assert workbook.active.cell(2, 1).data_type == "s"
        workbook.close()
        report["checks"].append("Catalog, scope-independent selection, keyboard and header reorder, exact XLSX values")
        assert len(list(window.last_folder.glob("mails/*/attachments/*.docx"))) == 2
        assert not list(window.last_folder.glob("mails/*/text/*"))
        report["checks"].append("Attachments prepared, text extraction remains opt-in")
        window.show_page(1)
        window.tabs.setCurrentWidget(window.field_page)
        window.resize(1000, 720)
        window.toggle_text()
        capture("07-compact-large-text.png")
        assert window.primary.isVisible()
        assert window.primary.geometry().bottom() < window.height()
        report["checks"].append("Compact window, large text, fixed action area")
        assert "emailtools.ui.server" not in __import__("sys").modules
        report["checks"].append("Native startup without browser/server import")
    except Exception:
        report["error"] = traceback.format_exc()
        capture("failure.png")
    finally:
        (output / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if window.worker:
            window.worker.requestInterruption()
            window.worker.wait(60000)
            app.processEvents()
        window.close()
        app.exit(1 if report["error"] else 0)
