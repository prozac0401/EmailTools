"""EmailTools native Windows application, powered by embedded Python and Qt."""
from __future__ import annotations
import argparse
import copy
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import replace
from io import StringIO
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot, QThread, QTimer, QUrl, QSettings, QSize
from PySide6.QtGui import QDesktopServices, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QLineEdit, QFileDialog, QCheckBox,
    QTabWidget, QSplitter, QComboBox, QProgressBar, QScrollArea, QDialog, QPlainTextEdit,
    QDialogButtonBox, QFormLayout, QSizePolicy)

from emailtools import __version__, pipeline, reader
from emailtools.models import ProcessingOptions
from emailtools.plans import MODE_NAMES, options_for_mode, ExportPlan
from emailtools.table_config import validate_columns, project_records
from emailtools.exporters.files import export_results
from emailtools.extractors.tables import collect_columns
from emailtools.desktop.theme import icon, stylesheet
from emailtools.desktop.widgets import DropFrame, ChipList, RecordModel, data_table, ROLE

LABELS = {"source_eml": "원본 파일", "subject": "메일 제목", "from": "보낸 사람", "to": "받는 사람",
          "date": "보낸 날짜", "attachments": "첨부", "_status": "처리 상태", "_error": "확인 내용",
          "name": "첨부파일", "type": "파일 형식", "size": "크기", "table": "표 분석", "text": "텍스트 추출"}
BASE_COLUMNS = [dict(id="base:source", source="source_eml", name="source_eml", value="", enabled=True, base=True),
                dict(id="base:subject", source="subject", name="subject", value="", enabled=True, base=True)]
FLAGS = {"common": "공통 후보", "rare": "드문 항목", "repeated": "반복 많음", "review": "구조 확인"}


def parse_input_paths(text):
    """Keep Windows backslashes/spaces, including Explorer's Copy as path list."""
    text = text.strip()
    if '"' in text:
        if not re.fullmatch(r'\s*"[^"\r\n]+"(?:\s+"[^"\r\n]+")*\s*', text):
            raise ValueError("경로의 따옴표를 확인해 주세요. 여러 경로는 각각 큰따옴표로 감싸 주세요.")
        return re.findall(r'"([^"\r\n]+)"', text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def label(text, name="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback=None, primary=False, name="", symbol=None):
    widget = QPushButton(text)
    if callback:
        widget.clicked.connect(callback)
    widget.setObjectName("Primary" if primary else name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if symbol:
        widget.setIcon(icon(symbol, "#ffffff" if primary else "#63788e"))
        widget.setIconSize(QSize(19, 19))
    return widget


def layout(widget=None, horizontal=False, margin=0, spacing=12):
    result = QHBoxLayout(widget) if horizontal else QVBoxLayout(widget)
    result.setContentsMargins(margin, margin, margin, margin)
    result.setSpacing(spacing)
    return result


def panel(name="Panel"):
    result = QFrame()
    result.setObjectName(name)
    return result


def combo(entries):
    result = QComboBox()
    for text, value in entries:
        result.addItem(text, value)
    return result


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str, str)
    stopped = Signal()
    status = Signal(object)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = self.operation(self.status.emit, self.isInterruptionRequested)
        except InterruptedError:
            self.stopped.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())
        else:
            self.completed.emit(result)


class Window(QMainWindow):
    def __init__(self, sources=(), *, remember=True):
        super().__init__()
        self.setWindowTitle(f"EmailTools {__version__} · 메일 작업 공간")
        self.setWindowIcon(icon("mail", "#218596", 48))
        self.resize(1400, 930)
        self.setMinimumSize(1000, 720)
        self.temp = tempfile.TemporaryDirectory(prefix="EmailTools_desktop_")
        self.root = Path(self.temp.name)
        self.logger = logging.Logger("emailtools.desktop", logging.INFO)
        self.log = StringIO()
        self.log_handler = logging.StreamHandler(self.log)
        self.logger.addHandler(self.log_handler)
        log_root = (Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "EmailTools" / "logs"
                    if remember else self.root)
        self.log_path = log_root / "desktop.log"
        self.file_log_handler = None
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            self.file_log_handler = RotatingFileHandler(self.log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
            self.file_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(self.file_log_handler)
        except OSError:
            self.log_path = None
        self.settings = QSettings("EmailTools", "Desktop") if remember else None
        self.large = self.settings.value("large_text", False, type=bool) if self.settings else False
        self.sources = [str(Path(p)) for p in sources]
        self.analyzed_sources = ()
        self.result = None
        self.worker = None
        self.mode = "list"
        self.dataset = ""
        self.columns = copy.deepcopy(BASE_COLUMNS)
        self.undo_columns = None
        self.page_number = 0
        self.preview_page = 0
        self.last_folder = None
        self.active_spool = None
        self.close_pending = False
        self.busy = False
        self.task_kind = ""
        self.task_succeeded = False
        self.completion_callback = None
        self.last_error = ""
        self.setStyleSheet(stylesheet(self.large))
        self._build()
        self.set_mode("list")
        self.sync_input()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.elapsed_update)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.pick_files)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.primary_action)

    def _build(self):
        root = QWidget()
        root.setObjectName("Workspace")
        self.setCentralWidget(root)
        shell = layout(root, horizontal=True, spacing=0)
        rail = panel("Rail")
        rail.setFixedWidth(198)
        side = layout(rail, margin=20, spacing=16)
        brand = layout(horizontal=True, spacing=10)
        brand_icon = label("")
        brand_icon.setPixmap(icon("mail", "#6fd0cc", 32).pixmap(32, 32))
        brand.addWidget(brand_icon)
        brand.addWidget(label("EmailTools", "Brand"))
        side.addLayout(brand)
        side.addWidget(label("MAIL TO WORKSPACE", "RailCaption"))
        side.addSpacing(26)
        side.addWidget(label("작업 공간", "RailCaption"))
        self.nav = []
        for index, title in enumerate(("01   작업 선택", "02   결과 검토", "03   저장 확인")):
            item = button(title, lambda checked=False, i=index: self.navigate(i))
            item.setCheckable(True)
            side.addWidget(item)
            self.nav.append(item)
        side.addStretch()
        side.addWidget(label("내 컴퓨터에서 안전하게", "", True))
        side.addWidget(label("메일은 이 PC에서 처리됩니다.\n계정 연결 없이 시작하세요.", "RailCaption", True))
        side.addSpacing(8)
        side.addWidget(button("사용 안내", self.help_dialog))
        side.addWidget(label(f"WINDOWS DESKTOP  ·  {__version__}", "RailCaption"))
        shell.addWidget(rail)
        area = QWidget()
        main = layout(area, margin=28, spacing=18)
        self.main_layout = main
        top = layout(horizontal=True)
        self.breadcrumb = label("작업 공간   /   새 메일 작업", "Eyebrow")
        top.addWidget(self.breadcrumb)
        top.addStretch()
        top.addWidget(label("●  로컬 작업", "Tag"))
        self.size_button = button("글자 크게" if not self.large else "글자 기본", self.toggle_text)
        top.addWidget(self.size_button)
        main.addLayout(top)
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        self._build_start()
        self._build_review()
        self._build_export()
        self._build_progress()
        footer = layout(horizontal=True)
        self.footer_hint = label("EML 파일 또는 폴더를 선택해 주세요.", "Muted", True)
        footer.addWidget(self.footer_hint, 1)
        self.back_button = button("이전으로", self.go_back)
        footer.addWidget(self.back_button)
        self.primary = button("목록 만들기", self.primary_action, True, symbol="arrow")
        footer.addWidget(self.primary)
        main.addLayout(footer)
        shell.addWidget(area, 1)
        self.statusBar().showMessage("준비됨  ·  Ctrl+O 파일 선택  ·  Ctrl+Enter 다음 단계")
        self.show_page(0)

    def _build_start(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("Workspace")
        body = layout(content, spacing=17)
        body.addWidget(label("어떤 결과가 필요한가요?", "Title"))
        body.addWidget(label("원하는 작업을 선택하고, 메일을 불러오세요.", "Muted"))
        cards = layout(horizontal=True, spacing=14)
        self.cards = {}
        descriptions = {
            "list": ("mail", "메일 목록만", "제목·발신자·날짜를\n하나의 목록으로 정리합니다.", "메일 목록 Excel"),
            "archive": ("folder", "목록과 첨부 정리", "메일 목록과 첨부 원본을\n메일별 폴더에 보관합니다.", "목록 Excel + 첨부 원본"),
            "analyze": ("table", "목록·첨부·표 분석", "메일 본문과 Word 첨부의\n표 항목을 비교하고 선택합니다.", "목록 + 첨부 + 선택한 표 Excel"),
        }
        for mode, (symbol, title, description, output) in descriptions.items():
            card = panel("Card")
            box = layout(card, margin=18, spacing=9)
            row = layout(horizontal=True)
            glyph = label("")
            glyph.setPixmap(icon(symbol, "#278593", 28).pixmap(28, 28))
            row.addWidget(glyph)
            row.addStretch()
            check = label("○", "Muted")
            row.addWidget(check)
            box.addLayout(row)
            select = button(title, lambda checked=False, m=mode: self.set_mode(m), name="Link")
            select.setStyleSheet("text-align:left; padding:0; font-size:15px; font-weight:650;")
            select.setAccessibleName(title)
            box.addWidget(select)
            box.addWidget(label(description, "Muted", True))
            box.addWidget(label(output, "Eyebrow", True))
            card.mousePressEvent = lambda event, m=mode: self.set_mode(m)
            cards.addWidget(card, 1)
            self.cards[mode] = (card, check)
        body.addLayout(cards)
        input_panel = panel()
        input_layout = layout(input_panel, margin=20, spacing=12)
        row = layout(horizontal=True)
        row.addWidget(label("메일 불러오기", "SectionTitle"))
        row.addStretch()
        self.sample_button = button("샘플로 체험하기", self.load_demo, name="Link")
        row.addWidget(self.sample_button)
        input_layout.addLayout(row)
        self.drop = DropFrame()
        self.drop.pathsDropped.connect(self.accept_paths)
        drop_layout = layout(self.drop, margin=20, spacing=8)
        drop_layout.addStretch()
        glyph = label("")
        glyph.setPixmap(icon("folder", "#738fa8", 38).pixmap(38, 38))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(glyph)
        self.input_label = label("EML 파일이나 폴더를 여기에 놓으세요", "SectionTitle", True)
        self.input_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.input_label)
        caption = label("하위 폴더의 메일도 함께 찾습니다.", "Muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(caption)
        row = layout(horizontal=True)
        row.addStretch()
        row.addWidget(button("폴더 선택", self.pick_folder, symbol="folder"))
        row.addWidget(button("EML 파일 선택", self.pick_files, symbol="file"))
        row.addStretch()
        drop_layout.addLayout(row)
        drop_layout.addStretch()
        input_layout.addWidget(self.drop)
        row = layout(horizontal=True, spacing=8)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("또는 EML 파일·폴더 경로를 입력하세요")
        self.path_edit.setAccessibleName("EML 입력 경로")
        self.path_edit.editingFinished.connect(self.path_changed)
        self.path_edit.textEdited.connect(self.path_typed)
        row.addWidget(self.path_edit, 1)
        row.addWidget(button("입력 비우기", lambda: self.accept_paths([]), name="Link"))
        input_layout.addLayout(row)
        body.addWidget(input_panel, 1)
        settings_row = layout(horizontal=True)
        self.details_button = button("▸  세부 설정", self.toggle_details, name="Link")
        settings_row.addWidget(self.details_button)
        self.modified_label = label("", "Muted")
        settings_row.addWidget(self.modified_label)
        settings_row.addStretch()
        settings_row.addWidget(button("표만 취합", self.tables_only, name="Link"))
        body.addLayout(settings_row)
        self.details = panel()
        grid = QGridLayout(self.details)
        grid.setContentsMargins(18, 12, 18, 12)
        self.options_checks = {}
        for i, (key, title) in enumerate((
            ("save_mail", "본문을 TXT로 저장"), ("extract_text", "첨부 내용을 TXT로 추출"),
            ("save_attachments", "첨부 원본 저장"), ("attachment_index", "첨부 상세 목록 포함"),
            ("extract_tables", "표 분석 사용"), ("email_tables", "메일 본문 표"), ("docx_tables", "Word 첨부 표"))):
            check = QCheckBox(title)
            check.toggled.connect(self.options_changed)
            self.options_checks[key] = check
            grid.addWidget(check, i // 3, i % 3)
        self.details.hide()
        body.addWidget(self.details)
        self.planned_hint = label("", "Muted", True)
        body.addWidget(self.planned_hint)
        scroll.setWidget(content)
        self.stack.addWidget(scroll)

    def _build_review(self):
        page = QWidget()
        body = layout(page, spacing=14)
        row = layout(horizontal=True)
        row.addWidget(label("추출 결과를 검토하세요", "Title"))
        row.addStretch()
        row.addWidget(button("작업 설정 변경", lambda: self.show_page(0)))
        body.addLayout(row)
        self.result_summary = label("", "Muted", True)
        body.addWidget(self.result_summary)
        self.metrics_widget = QWidget()
        metrics = layout(self.metrics_widget, horizontal=True, spacing=12)
        self.metrics = []
        for title in ("불러온 메일", "첨부파일", "발견한 표 항목"):
            card = panel("Metric")
            box = layout(card, horizontal=True, margin=16)
            box.addWidget(label(title, "Muted"))
            box.addStretch()
            value = label("0", "MetricValue")
            box.addWidget(value)
            self.metrics.append(value)
            metrics.addWidget(card, 1)
        body.addWidget(self.metrics_widget)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.tab_changed)
        body.addWidget(self.tabs, 1)
        self.mail_page = self._list_page(False)
        self.attachment_page = self._list_page(True)
        self.field_page = self._field_page()
        self.table_page = self._table_page()
        self.stack.addWidget(page)

    def _list_page(self, attachments):
        page = QWidget()
        body = layout(page, margin=16)
        row = layout(horizontal=True)
        search = QLineEdit()
        search.setPlaceholderText("첨부명 · 원본 메일 검색" if attachments else "제목 · 발신자 · 수신자 · 파일명 검색")
        search.setAccessibleName("첨부 검색" if attachments else "메일 검색")
        row.addWidget(search, 1)
        status = combo([("모든 상태", "all"), ("확인 필요", "warning")])
        row.addWidget(status)
        body.addLayout(row)
        table = data_table()
        body.addWidget(table, 1)
        hint = label("검색과 관계없이 전체 메일을 저장합니다. 행을 더블클릭하면 상세를 확인합니다.", "Muted", True)
        body.addWidget(hint)
        if attachments:
            self.attachment_table, self.attachment_search, self.attachment_status = table, search, status
        else:
            self.mail_table, self.mail_search, self.mail_status = table, search, status
        search.textChanged.connect(self.refresh_lists)
        status.currentIndexChanged.connect(self.refresh_lists)
        table.doubleClicked.connect(lambda index: self.mail_detail(table.model().rows[index.row()]["_mail_index"]))
        return page

    def _field_page(self):
        page = QWidget()
        body = layout(page, margin=16, spacing=9)
        self.field_split = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top_layout = layout(top, spacing=7)
        row = layout(horizontal=True, spacing=7)
        self.selected_title = label("선택한 열 순서", "SectionTitle")
        row.addWidget(self.selected_title)
        row.addStretch()
        self.move_left = button("←", lambda: self.move_current(-1))
        self.move_right = button("→", lambda: self.move_current(1))
        self.move_left.setAccessibleName("선택한 열 앞으로")
        self.move_right.setAccessibleName("선택한 열 뒤로")
        row.addWidget(self.move_left)
        row.addWidget(self.move_right)
        row.addWidget(button("열 편집", self.edit_current))
        self.undo_button = button("되돌리기", self.undo)
        row.addWidget(self.undo_button)
        row.addWidget(button("+ 사용자 열", self.add_custom))
        top_layout.addLayout(row)
        self.field_move_hint = label("끌어서 순서를 바꾸세요.  Alt+←/→ 이동 · Delete 제외 · F1 출처 확인", "Muted", True)
        top_layout.addWidget(self.field_move_hint)
        self.selected = ChipList(True)
        self.selected.setAccessibleName("선택한 열 순서")
        self.selected.currentItemChanged.connect(self.update_move_buttons)
        self.selected.infoField.connect(self.field_detail)
        self.selected.removedField.connect(self.remove_field)
        self.selected.movedField.connect(self.move_field)
        self.selected.droppedField.connect(self.drop_selected)
        top_layout.addWidget(self.selected, 1)
        self.field_split.addWidget(top)
        bottom = QWidget()
        lower = layout(bottom, spacing=7)
        row = layout(horizontal=True)
        self.candidate_title = label("남은 후보", "SectionTitle")
        row.addWidget(self.candidate_title)
        row.addStretch()
        self.common_button = button("공통 후보 추가", self.add_common, name="Link")
        row.addWidget(self.common_button)
        row.addWidget(button("원본 표", lambda: self.field_detail("tables"), name="Link"))
        lower.addLayout(row)
        row = layout(horizontal=True, spacing=8)
        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText("항목명 검색")
        self.field_search.setAccessibleName("표 항목 검색")
        self.search_values = QCheckBox("값도 검색")
        row.addWidget(self.field_search, 1)
        row.addWidget(self.search_values)
        lower.addLayout(row)
        row = layout(horizontal=True, spacing=8)
        self.source_scope = combo([("전체 출처", "all"), ("메일 본문", "email"), ("Word 첨부", "docx")])
        self.category = combo([("전체 항목", "all"), *[(v, k) for k, v in FLAGS.items()]])
        self.field_sort = combo([("공통 후보 우선", "common"), ("발견 메일 많은 순", "coverage"), ("반복 적은 순", "repeat"), ("처음 발견한 순", "first")])
        row.addWidget(self.source_scope)
        row.addWidget(self.category)
        row.addWidget(self.field_sort)
        row.addStretch()
        row.addWidget(label("필터는 조회만 변경", "Eyebrow"))
        lower.addLayout(row)
        self.candidates = ChipList()
        self.candidates.setAccessibleName("남은 표 항목 후보")
        self.candidates.activatedField.connect(self.add_field)
        self.candidates.infoField.connect(self.field_detail)
        self.candidates.droppedField.connect(lambda fid, pos, selected: self.remove_field(fid) if selected else None)
        lower.addWidget(self.candidates, 1)
        self.empty_candidates = label("", "Muted", True)
        lower.addWidget(self.empty_candidates)
        row = layout(horizontal=True)
        self.field_count = label("", "Muted")
        row.addWidget(self.field_count)
        row.addStretch()
        row.addWidget(button("조건 초기화", self.clear_filters, name="Link"))
        self.candidate_prev = button("이전", lambda: self.change_candidates(-1))
        self.candidate_next = button("다음", lambda: self.change_candidates(1))
        row.addWidget(self.candidate_prev)
        row.addWidget(self.candidate_next)
        lower.addLayout(row)
        self.field_split.addWidget(bottom)
        self.field_split.setChildrenCollapsible(False)
        self.field_split.setStretchFactor(0, 2)
        self.field_split.setStretchFactor(1, 3)
        self.field_split.setSizes([180, 270])
        body.addWidget(self.field_split, 1)
        for control in (self.source_scope, self.category, self.field_sort):
            control.currentIndexChanged.connect(self.filters_changed)
        self.field_search.textChanged.connect(self.filters_changed)
        self.search_values.toggled.connect(self.filters_changed)
        return page

    def _table_page(self):
        page = QWidget()
        body = layout(page, margin=16)
        row = layout(horizontal=True)
        row.addWidget(label("저장할 순서와 값을 확인하세요", "SectionTitle"))
        row.addStretch()
        row.addWidget(button("열 선택·순서 편집", lambda: self.tabs.setCurrentWidget(self.field_page)))
        self.original_view = QCheckBox("원본 전체 보기")
        self.original_view.toggled.connect(self.refresh_preview)
        row.addWidget(self.original_view)
        body.addLayout(row)
        body.addWidget(label("머리글을 끌어 열 순서를 바꿀 수 있습니다. 셀을 더블클릭하면 전체 값을 확인합니다.", "Muted", True))
        self.preview = data_table()
        self.preview.horizontalHeader().setSectionsMovable(True)
        self.preview.horizontalHeader().sectionMoved.connect(self.header_moved)
        self.preview.doubleClicked.connect(self.cell_detail)
        body.addWidget(self.preview, 1)
        row = layout(horizontal=True)
        self.preview_hint = label("", "Muted")
        row.addWidget(self.preview_hint, 1)
        self.preview_prev = button("이전 25행", lambda: self.change_preview(-1))
        self.preview_next = button("다음 25행", lambda: self.change_preview(1))
        row.addWidget(self.preview_prev)
        row.addWidget(self.preview_next)
        body.addLayout(row)
        return page

    def _build_export(self):
        page = QWidget()
        body = layout(page, spacing=18)
        body.addWidget(label("저장할 결과를 확인하세요", "Title"))
        body.addWidget(label("전체 메일을 저장합니다. 화면에서 사용한 검색과 필터는 저장 범위를 바꾸지 않습니다.", "Muted", True))
        card = panel()
        form = layout(card, margin=24, spacing=13)
        form.addWidget(label("결과 구성", "SectionTitle"))
        self.export_summary = label("", "Muted", True)
        form.addWidget(self.export_summary)
        self.export_checks = {}
        for key, title in (("attachment_index", "첨부 목록 Excel"), ("attachments", "첨부파일 원본"),
                           ("tables", "선택한 표 Excel"), ("body", "메일 본문 TXT"),
                           ("text", "첨부 내용 TXT"), ("archive", "전체 결과 ZIP도 만들기")):
            check = QCheckBox(title)
            check.toggled.connect(self.update_export)
            self.export_checks[key] = check
            form.addWidget(check)
        self.column_summary = label("", "Muted", True)
        form.addWidget(self.column_summary)
        self.exclude_tables = button("표 Excel 없이 목록·첨부만 저장", lambda: self.export_checks["tables"].setChecked(False), name="Link")
        form.addWidget(self.exclude_tables)
        body.addWidget(card)
        card = panel()
        box = layout(card, margin=24)
        box.addWidget(label("저장 위치", "SectionTitle"))
        row = layout(horizontal=True)
        self.output_path = QLineEdit()
        self.output_path.setAccessibleName("결과 저장 폴더")
        self.output_path.textChanged.connect(self.update_export)
        row.addWidget(self.output_path, 1)
        row.addWidget(button("폴더 선택", self.pick_output, symbol="folder"))
        box.addLayout(row)
        box.addWidget(label("실행마다 새 결과 폴더를 만들어 이전 결과를 보존합니다.", "Muted", True))
        body.addWidget(card)
        self.outputs = QWidget()
        self.output_links = layout(self.outputs, horizontal=True)
        body.addWidget(self.outputs)
        body.addStretch()
        self.stack.addWidget(page)

    def _build_progress(self):
        page = QWidget()
        outer = layout(page)
        outer.addStretch(1)
        card = panel()
        body = layout(card, margin=36, spacing=20)
        self.progress_title = label("작업 준비 중", "Title")
        body.addWidget(self.progress_title)
        self.progress_steps = label("파일 찾기  →  메일 처리  →  결과 준비", "Muted", True)
        body.addWidget(self.progress_steps)
        self.phase_label = label("준비 중", "SectionTitle")
        body.addWidget(self.phase_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName("현재 단계 진행률")
        body.addWidget(self.progress_bar)
        self.progress_detail = label("", "Muted", True)
        body.addWidget(self.progress_detail)
        self.current_file = label("", "Muted", True)
        body.addWidget(self.current_file)
        row = layout(horizontal=True)
        self.elapsed_label = label("경과 00:00", "Muted")
        row.addWidget(self.elapsed_label)
        row.addStretch()
        self.cancel_button = button("처리 중지", self.cancel_work)
        row.addWidget(self.cancel_button)
        self.error_button = button("오류 상세 보기", self.show_task_error)
        self.error_button.setVisible(False)
        row.addWidget(self.error_button)
        body.addLayout(row)
        outer.addWidget(card)
        outer.addStretch(2)
        self.stack.addWidget(page)

    def show_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, item in enumerate(self.nav):
            item.setChecked(i == index)
            item.setEnabled(not self.busy and (i == 0 or self.result is not None))
        self.back_button.setVisible(index in (1, 2) or (index == 0 and self.result is not None))
        self.primary.setVisible(index != 3 or not self.busy)
        if index == 0:
            self.primary.setText("표까지 분석하기" if self.current_options().extract_tables else "목록 만들기")
            self.primary.setEnabled(bool(self.sources))
            self.footer_hint.setText("EML 파일 또는 폴더를 선택해 주세요." if not self.sources else "준비되었습니다. 선택한 작업으로 분석을 시작하세요.")
            if self.result:
                self.back_button.setText("설정 취소 · 결과로")
        elif index == 1:
            self.back_button.setText("작업 설정")
            self.primary.setText("저장 구성 확인")
            self.primary.setEnabled(True)
            self.footer_hint.setText(f"검색과 관계없이 전체 {len(self.result.mails):,}개 메일을 저장합니다.")
        elif index == 2:
            self.back_button.setText("결과 검토")
            self.primary.setText("결과 저장")
            self.update_export()
        else:
            self.footer_hint.setText("진행률은 현재 단계에서 실제로 처리한 수량을 표시합니다.")

    def navigate(self, index):
        if self.busy:
            return
        if index == 2 and self.result:
            self.prepare_export()
        elif index == 0 or self.result:
            self.show_page(index)

    def go_back(self):
        if self.stack.currentIndex() == 0 and self.result:
            self.set_options(self.result.options)
            self.sources = list(self.analyzed_sources)
            self.sync_input()
            self.show_page(1)
        else:
            self.show_page(max(0, self.stack.currentIndex() - 1))

    def primary_action(self):
        if self.busy:
            return
        index = self.stack.currentIndex()
        if index == 0:
            self.start_analysis()
        elif index == 1:
            self.prepare_export()
        elif index == 2:
            self.start_export()
        elif self.result:
            self.show_page(2 if self.task_kind == "save" else 1)
        else:
            self.show_page(0)

    def set_mode(self, mode):
        if self.busy:
            return
        self.mode = mode
        self.set_options(options_for_mode(mode))

    def set_options(self, options):
        for key, check in self.options_checks.items():
            check.blockSignals(True)
            check.setChecked(getattr(options, key))
            check.blockSignals(False)
        self.options_changed()

    def current_options(self):
        return ProcessingOptions(mail_index=True, **{key: check.isChecked() for key, check in self.options_checks.items()})

    def options_changed(self):
        options = self.current_options()
        for mode, (card, marker) in self.cards.items():
            card.setProperty("selected", mode == self.mode)
            marker.setText("●" if mode == self.mode else "○")
            card.style().unpolish(card)
            card.style().polish(card)
        changed = options != options_for_mode(self.mode)
        self.modified_label.setText("세부 설정 변경됨" if changed else "")
        for key in ("email_tables", "docx_tables"):
            self.options_checks[key].setEnabled(options.extract_tables)
        pieces = ["메일 목록 Excel"]
        for enabled, text in ((options.attachment_index, "첨부 목록"), (options.save_attachments, "첨부 원본"),
                (options.extract_tables, "선택한 표 Excel"), (options.save_mail, "본문 TXT"), (options.extract_text, "첨부 TXT")):
            if enabled:
                pieces.append(text)
        self.planned_hint.setText("저장 예정  ·  " + "  +  ".join(pieces))
        if hasattr(self, "primary") and self.stack.currentIndex() == 0:
            self.primary.setText("표까지 분석하기" if options.extract_tables else "목록 만들기")

    def tables_only(self):
        self.mode = "analyze"
        self.set_options(ProcessingOptions(mail_index=True, extract_tables=True))

    def toggle_details(self):
        self.details.setVisible(not self.details.isVisible())
        self.details_button.setText("▾  세부 설정" if self.details.isVisible() else "▸  세부 설정")

    def toggle_text(self):
        self.large = not self.large
        self.setStyleSheet(stylesheet(self.large))
        self.size_button.setText("글자 기본" if self.large else "글자 크게")
        if self.settings:
            self.settings.setValue("large_text", self.large)
        self.selected.doItemsLayout()
        self.candidates.doItemsLayout()
        self.apply_compact_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "metrics_widget"):
            self.apply_compact_layout()

    def apply_compact_layout(self):
        compact = self.height() < 850
        self.metrics_widget.setVisible(not compact)
        self.result_summary.setVisible(not compact)
        self.field_move_hint.setVisible(not compact)
        margin = 20 if compact else 28
        self.main_layout.setContentsMargins(margin, margin, margin, margin)
        self.main_layout.setSpacing(12 if compact else 18)

    def accept_paths(self, paths):
        if self.busy:
            return False
        normalized = []
        try:
            for value in paths:
                path = Path(value).expanduser().resolve(strict=True)
                if not path.is_dir() and not (path.is_file() and path.suffix.lower() == ".eml"):
                    raise ValueError(f"EML 파일 또는 폴더를 선택해 주세요: {path.name}")
                normalized.append(str(path))
        except FileNotFoundError:
            self.notice(f"파일 또는 폴더를 찾을 수 없습니다: {value}")
            return False
        except (OSError, ValueError) as exc:
            self.notice(f"입력 경로를 확인해 주세요: {exc}")
            return False
        self.sources = list(dict.fromkeys(normalized))
        self.sync_input()
        return True

    def sync_input(self):
        self.path_edit.setText(self.sources[0] if len(self.sources) == 1 else "")
        self.path_edit.setPlaceholderText(f"EML 파일 {len(self.sources)}개 선택됨" if len(self.sources) > 1 else "또는 EML 파일·폴더 경로를 입력하세요")
        self.path_edit.setToolTip("\n".join(self.sources))
        if len(self.sources) == 1:
            self.input_label.setText(Path(self.sources[0]).name or self.sources[0])
        elif self.sources:
            self.input_label.setText(f"EML 파일 {len(self.sources):,}개 선택됨")
        else:
            self.input_label.setText("EML 파일이나 폴더를 여기에 놓으세요")
        if self.stack.currentIndex() == 0:
            self.primary.setEnabled(bool(self.sources))
            self.footer_hint.setText("선택한 작업으로 분석을 시작할 수 있습니다." if self.sources else "EML 파일 또는 폴더를 선택해 주세요.")

    def path_typed(self, text):
        try:
            self.sources = parse_input_paths(text)
        except ValueError:
            self.sources = []
        self.primary.setEnabled(bool(self.sources))

    def path_changed(self):
        # Programmatic sync (including a multiple-file picker) is not a new edit.
        if not self.path_edit.isModified():
            return
        try:
            paths = parse_input_paths(self.path_edit.text())
        except ValueError as exc:
            self.notice(str(exc))
        else:
            if self.accept_paths(paths):
                return
        self.sources = []
        self.primary.setEnabled(False)

    def pick_files(self):
        if not self.busy:
            paths, _ = QFileDialog.getOpenFileNames(self, "EML 파일 선택", "", "EML 메일 (*.eml *.EML)")
            if paths:
                self.accept_paths(paths)

    def pick_folder(self):
        if not self.busy:
            path = QFileDialog.getExistingDirectory(self, "메일 폴더 선택")
            if path:
                self.accept_paths([path])

    def load_demo(self):
        from emailtools.demo import create_demo
        folder = self.root / "sample"
        folder.mkdir(exist_ok=True)
        create_demo(folder)
        self.accept_paths([str(folder)])
        self.statusBar().showMessage("합성 샘플 메일 3개가 준비되었습니다. 분석 버튼을 눌러 시작하세요.")

    def notice(self, message):
        self.statusBar().showMessage(message)
        self.footer_hint.setText(message)

    def start_analysis(self):
        if not self.sources or not self.accept_paths(self.sources):
            return
        options = self.current_options()
        try:
            options.validate()
        except ValueError as exc:
            self.notice(str(exc))
            return
        inputs = tuple(self.sources)
        spool = self.root / ("analysis-" + uuid.uuid4().hex)
        restore = inputs == self.analyzed_sources
        def operation(status, cancelled):
            try:
                return pipeline.analyze(Path(inputs[0]), options, spool, self.logger,
                    sources=[Path(p) for p in inputs], status=status, is_cancelled=cancelled)
            except BaseException:
                if spool.exists() and spool.resolve().parent == self.root.resolve():
                    shutil.rmtree(spool)
                raise
        def complete(result):
            names = ("result", "analyzed_sources", "dataset", "last_folder", "undo_columns",
                     "columns", "page_number", "preview_page")
            previous = {name: getattr(self, name) for name in names}
            self.result = result
            self.analyzed_sources = inputs
            self.dataset = uuid.uuid4().hex
            self.last_folder = None
            self.undo_columns = None
            old_count = len(self.columns)
            if restore:
                self.columns = [copy.deepcopy(c) for c in self.columns if c.get("base") or c.get("custom") or
                                (result.catalog and c["id"] in result.catalog.fields)]
                for column in self.columns:
                    if result.catalog and column["id"] in result.catalog.fields:
                        column["source"] = result.catalog.fields[column["id"]]["record_key"]
            else:
                self.columns = copy.deepcopy(BASE_COLUMNS)
            self.page_number = self.preview_page = 0
            try:
                if not restore:
                    self.reset_result_filters()
                self.refresh_result()
                self.refresh_output_links()
            except Exception:
                for name, value in previous.items():
                    setattr(self, name, value)
                if self.result:
                    try:
                        self.refresh_result()
                        self.refresh_output_links()
                    except Exception:
                        self.logger.exception("이전 결과 화면 복원 실패")
                else:
                    self.tabs.clear()
                self.clean_spool(spool)
                raise
            previous_spool = self.active_spool
            self.active_spool = spool
            self.clean_spool(previous_spool)
            self.finish_progress("분석 완료 · 일부 확인 필요" if result.warnings or result.failures else "분석 완료",
                f"정상 {result.success}개 · 확인 {result.warnings}개 · 실패 {result.failures}개" +
                (f" · 사라진 항목 {old_count - len(self.columns)}개 제외" if restore and old_count > len(self.columns) else ""))
        self.task_kind = "analysis"
        self.progress_steps.setText("파일 찾기  →  메일·표 읽기  →  항목 정리  →  결과 준비" if options.extract_tables else "파일 찾기  →  메일·첨부 준비  →  결과 준비")
        self.begin_work(operation, complete, "표 항목을 분석하고 있습니다" if options.extract_tables else "메일 목록을 만들고 있습니다")

    def clean_spool(self, path):
        if path and path.exists() and path.resolve().parent == self.root.resolve():
            try:
                shutil.rmtree(path)
            except OSError:
                self.logger.exception("임시 분석 파일 정리 실패")

    def begin_work(self, operation, complete, title):
        if self.worker is not None:
            return
        self.busy = True
        self.task_succeeded = False
        self.completion_callback = complete
        self.last_error = ""
        self.error_button.setVisible(False)
        self.started = time.monotonic()
        self.progress_title.setText(title)
        self.phase_label.setText("준비 중")
        self.progress_detail.setText("작업을 준비하고 있습니다.")
        self.current_file.setText("")
        self.progress_bar.setRange(0, 0)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("저장 중지" if self.task_kind == "save" else "처리 중지")
        self.worker = Worker(operation, self)
        self.worker.status.connect(self.on_progress)
        self.worker.completed.connect(self.work_completed)
        self.worker.failed.connect(self.work_failed)
        self.worker.stopped.connect(self.work_stopped)
        self.worker.finished.connect(self.worker_finished)
        self.show_page(3)
        self.timer.start()
        self.worker.start()

    @Slot(object)
    def work_completed(self, result):
        # A QObject slot runs on the GUI thread and provides an explicit error
        # boundary; exceptions in a raw Qt callback vanish under pythonw.exe.
        try:
            self.completion_callback(result)
        except Exception as exc:
            self.work_failed(f"결과를 표시하지 못했습니다: {type(exc).__name__}: {exc}", traceback.format_exc())
        else:
            self.task_succeeded = True

    def on_progress(self, status):
        self.phase_label.setText(status["phase"])
        total, done = status.get("total"), status.get("completed", 0)
        if total is None or total <= 0:
            self.progress_bar.setRange(0, 0)
            self.progress_detail.setText(f"발견한 EML {done:,}개 · 파일 찾는 중" if status["phase"] == "파일 찾기" else "전체량 확인 중")
        else:
            percent = min(100, done * 100 // total)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
            unit = "바이트" if status["phase"] == "ZIP 생성" else "행" if "Excel" in status["phase"] else "개"
            self.progress_detail.setText(f"현재 단계 {percent}%  ·  {done:,} / {total:,}{unit}")
            self.progress_bar.setAccessibleDescription(f"{status['phase']}, {done} / {total}{unit}, {percent}%")
        self.current_file.setText(status.get("current", ""))
        if not status.get("cancellable", True):
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("저장 마무리 중")

    def elapsed_update(self):
        seconds = int(time.monotonic() - self.started)
        self.elapsed_label.setText(f"경과 {seconds // 60:02d}:{seconds % 60:02d}")

    def cancel_work(self):
        if self.worker:
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("중지 요청됨 · 정리 중")

    def finish_progress(self, title, description):
        self.progress_title.setText(title)
        self.phase_label.setText("작업 완료 100%")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_detail.setText(description)
        self.current_file.setText("")

    @Slot(str, str)
    def work_failed(self, error, details=""):
        self.task_succeeded = False
        self.last_error = details or error
        self.logger.error("%s\n%s", error, details)
        self.error_button.setVisible(True)
        self.progress_title.setText("작업을 완료하지 못했습니다")
        self.phase_label.setText("실패 · 다시 시도할 수 있습니다")
        self.progress_detail.setText(error)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.current_file.setText("이전 분석 결과와 선택한 열은 유지됩니다." if self.result else "입력 경로와 파일을 확인해 주세요.")

    def show_task_error(self):
        location = f"오류 기록: {self.log_path}\n\n" if self.log_path else ""
        self.text_dialog("작업 오류 상세", location + self.last_error)

    def work_stopped(self):
        self.progress_title.setText("작업이 중지되었습니다")
        self.phase_label.setText("중지됨")
        self.progress_detail.setText("이번 작업의 미완성 결과는 저장하지 않았습니다.")
        self.current_file.setText("이전 분석 결과와 선택한 열은 유지됩니다." if self.result else "작업 설정으로 돌아가 다시 시작할 수 있습니다.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.busy = False
        self.completion_callback = None
        self.timer.stop()
        self.cancel_button.setEnabled(False)
        self.primary.setVisible(True)
        self.primary.setEnabled(True)
        self.primary.setText("저장 결과 확인" if self.last_folder and self.task_kind == "save" else "결과 검토" if self.result else "작업 설정으로")
        for i, item in enumerate(self.nav):
            item.setEnabled(i == 0 or self.result is not None)
        if self.close_pending:
            self.close()
        elif self.task_succeeded and self.task_kind == "analysis":
            self.show_page(1)
            self.statusBar().showMessage("분석 완료 · " + self.progress_detail.text())

    def reset_result_filters(self):
        for control in (self.mail_search, self.attachment_search, self.field_search):
            control.blockSignals(True)
            control.clear()
            control.blockSignals(False)
        for control in (self.mail_status, self.attachment_status, self.source_scope, self.category, self.field_sort):
            control.blockSignals(True)
            control.setCurrentIndex(0)
            control.blockSignals(False)
        self.search_values.blockSignals(True)
        self.search_values.setChecked(False)
        self.search_values.blockSignals(False)

    def refresh_result(self):
        result = self.result
        self.result_summary.setText(f"전체 {len(result.mails):,}개 메일  ·  정상 {result.success:,}개  ·  확인 필요 {result.warnings:,}개  ·  읽기 실패 {result.failures:,}개")
        for value, count in zip(self.metrics, (len(result.mails), result.attachment_count, len(result.catalog.fields) if result.catalog else 0)):
            value.setText(f"{count:,}")
        self.tabs.clear()
        self.tabs.addTab(self.mail_page, "메일 목록")
        options = result.options
        if options.attachment_index or options.save_attachments or options.extract_text or options.extract_tables:
            self.tabs.addTab(self.attachment_page, "첨부파일")
        if options.extract_tables:
            self.tabs.addTab(self.field_page, "표 항목 찾기")
            self.tabs.addTab(self.table_page, "저장할 표")
        self.refresh_lists()
        self.refresh_fields()
        self.refresh_preview()
        self.tabs.setCurrentWidget(self.field_page if options.extract_tables else self.attachment_page if options.save_attachments else self.mail_page)

    def refresh_lists(self):
        if not self.result:
            return
        mails, attachments = [], []
        for i, mail in enumerate(self.result.mails):
            row = {**mail.record, "attachments": len(mail.attachments), "_mail_index": i}
            needle = self.mail_search.text().casefold().strip()
            if (not needle or any(needle in str(row.get(k, "")).casefold() for k in ("subject", "from", "to", "source_eml"))) and (self.mail_status.currentData() == "all" or row["_status"] != "OK"):
                mails.append(row)
            for item in mail.attachments:
                row = dict(source_eml=mail.record["source_eml"], name=item.name, type=Path(item.name).suffix.upper().lstrip(".") or item.content_type,
                    size="확인 안 함" if item.size is None else f"{item.size:,} B", table=item.table_status,
                    text=item.text_status, _error=item.error, _mail_index=i)
                needle = self.attachment_search.text().casefold().strip()
                if (not needle or needle in (item.name + mail.record["source_eml"]).casefold()) and (self.attachment_status.currentData() == "all" or item.error):
                    attachments.append(row)
        self.mail_table.setModel(RecordModel(mails, ["subject", "from", "to", "date", "attachments", "_status", "source_eml"], LABELS, self.mail_table))
        self.mail_table.setColumnWidth(0, 310)
        self.mail_table.setColumnWidth(4, 100)
        self.attachment_table.setModel(RecordModel(attachments, ["name", "source_eml", "type", "size", "table", "text", "_error"], LABELS, self.attachment_table))
        self.attachment_table.setColumnWidth(0, 250)

    def field_tooltip(self, fid):
        if not self.result or not self.result.catalog:
            return ""
        detail = self.result.catalog.detail(fid, self.source_scope.currentData()) or self.result.catalog.detail(fid)
        if not detail:
            return ""
        flags = " · ".join(FLAGS[k] for k in detail["flags"]) or "전체 후보"
        duplicate = detail["mail_count"] - detail["effective_mail_count"]
        return (f"{detail['name']}\n{flags}\n발견 메일 {detail['mail_count']} / {detail['total_mail_count']}개"
                f" · 문서 {detail['document_count']}개 · 등장 {detail['occurrence_count']}회"
                f"\n문서 내 1회 비율 {detail['single_document_ratio']:.0%} · 값 채움 {detail['filled_ratio']:.0%}"
                f"\n동일 원본 중복 {duplicate}개\n값 예시: {' · '.join(detail['examples'])[:500] or '빈 값'}\nⓘ 또는 F1: 전체 값·원본 출처")

    def refresh_fields(self):
        selected = []
        for col in self.columns:
            selected.append({**col, "display": LABELS.get(col["name"], col["name"]),
                "tooltip": "기본 메일 정보 · 순서 이동 가능" if col.get("base") else "사용자 열 · 모든 행에 같은 값" if col.get("custom") else self.field_tooltip(col["id"])})
        self.selected.populate(selected, self.dataset)
        self.selected_title.setText(f"선택한 열 순서  {len(self.columns)}")
        self.undo_button.setEnabled(self.undo_columns is not None)
        self.update_move_buttons()
        catalog = self.result.catalog if self.result else None
        if not catalog:
            self.candidates.populate([], self.dataset)
            return
        data = catalog.query(scope=self.source_scope.currentData(), query=self.field_search.text(),
            search_values=self.search_values.isChecked(), category=self.category.currentData(),
            sort=self.field_sort.currentData(), selected=[c["id"] for c in self.columns], page=self.page_number)
        if self.page_number and not data["fields"]:
            self.page_number -= 1
            return self.refresh_fields()
        fields = [{**f, "tooltip": self.field_tooltip(f["id"])} for f in data["fields"]]
        self.candidates.populate(fields, self.dataset)
        self.candidate_title.setText(f"남은 후보  {data['total']:,}")
        self.common_button.setVisible(bool(data["common"]))
        self.common_button.setText(f"공통 후보 {len(data['common'])}개 추가")
        self.common_ids = data["common"]
        self.candidate_prev.setEnabled(self.page_number > 0)
        self.candidate_next.setEnabled((self.page_number + 1) * 50 < data["total"])
        counts = data["counts"]
        self.field_count.setText(f"{self.page_number + 1} 페이지 · 공통 {counts['common']} · 드문 항목 {counts['rare']} · 구조 확인 {counts['review']}")
        self.empty_candidates.setVisible(not fields)
        if not catalog.tables:
            message = "분석 대상에서 표를 찾지 못했습니다. ‘메일 목록’에서 읽기 상태를 확인하세요. 표 분석 대상은 메일 HTML 본문과 Word 첨부입니다."
        elif not catalog.fields:
            message = "표는 있지만 추출할 항목/값 쌍을 찾지 못했습니다. ‘원본 표’에서 구조를 확인하세요."
        else:
            message = "조건에 맞는 남은 후보가 없습니다. 조건을 초기화하거나 선택한 열을 확인하세요."
        self.empty_candidates.setText(message)

    def filters_changed(self):
        self.page_number = 0
        self.refresh_fields()
        self.candidates.verticalScrollBar().setValue(0)

    def clear_filters(self):
        self.field_search.clear()
        self.source_scope.setCurrentIndex(0)
        self.category.setCurrentIndex(0)
        self.field_sort.setCurrentIndex(0)
        self.search_values.setChecked(False)

    def change_candidates(self, delta):
        self.page_number = max(0, self.page_number + delta)
        self.refresh_fields()

    def add_field(self, fid, position=None):
        if any(c["id"] == fid for c in self.columns) or not self.result or not self.result.catalog or fid not in self.result.catalog.fields:
            return
        field = self.result.catalog.fields[fid]
        self.undo_columns = None
        self.columns.insert(len(self.columns) if position is None else position,
            dict(id=fid, source=field["record_key"], name=self.available_name(field["name"]), value="", enabled=True))
        self.columns_changed(fid)

    def add_common(self):
        previous = copy.deepcopy(self.columns)
        for fid in self.common_ids:
            field = self.result.catalog.fields[fid]
            self.columns.append(dict(id=fid, source=field["record_key"], name=self.available_name(field["name"]), value="", enabled=True))
        self.undo_columns = previous
        self.columns_changed()
        self.notice("현재 출처 범위의 공통 후보를 추가했습니다. 검색·분류 조건과 관계없이 추가됩니다.")

    def available_name(self, name):
        names = {c["name"].casefold() for c in self.columns}
        candidate = name[:120]
        index = 2
        while candidate.casefold() in names:
            candidate = name[:110] + f" ({index})"
            index += 1
        return candidate

    def remove_field(self, fid):
        column = next((c for c in self.columns if c["id"] == fid), None)
        if not column or column.get("base"):
            return
        self.undo_columns = None
        self.columns.remove(column)
        self.columns_changed()

    def move_field(self, fid, position):
        origin = next((i for i, c in enumerate(self.columns) if c["id"] == fid), None)
        if origin is None or position < 0 or position >= len(self.columns) or origin == position:
            return
        self.undo_columns = copy.deepcopy(self.columns)
        column = self.columns.pop(origin)
        self.columns.insert(position, column)
        self.columns_changed(fid)
        self.notice(f"{column['name']} · {position + 1}번째 열로 이동했습니다.")

    def drop_selected(self, fid, position, was_selected):
        if was_selected:
            origin = next((i for i, c in enumerate(self.columns) if c["id"] == fid), None)
            if origin is not None:
                self.move_field(fid, position - int(position > origin))
        else:
            self.add_field(fid, position)

    def move_current(self, delta):
        item = self.selected.currentItem()
        if item:
            self.move_field(item.data(ROLE)["id"], self.selected.currentRow() + delta)

    def update_move_buttons(self, *args):
        row = self.selected.currentRow()
        self.move_left.setEnabled(row > 0)
        self.move_right.setEnabled(0 <= row < len(self.columns) - 1)

    def columns_changed(self, focus=None):
        self.refresh_fields()
        self.refresh_preview()
        if focus:
            for i in range(self.selected.count()):
                if self.selected.item(i).data(ROLE)["id"] == focus:
                    self.selected.setCurrentRow(i)
                    self.selected.scrollToItem(self.selected.item(i))
                    self.selected.setFocus()
                    break

    def undo(self):
        if self.undo_columns is not None:
            self.columns, self.undo_columns = self.undo_columns, None
            self.columns_changed()

    def edit_current(self):
        if self.selected.currentItem():
            self.column_dialog(self.selected.currentItem().data(ROLE)["id"])

    def add_custom(self):
        self.column_dialog()

    def column_dialog(self, fid=None):
        column = next((c for c in self.columns if c["id"] == fid), None)
        dialog = QDialog(self)
        dialog.setWindowTitle("열 편집" if column else "사용자 열 추가")
        dialog.resize(480, 240)
        body = layout(dialog, margin=24)
        form = QFormLayout()
        name = QLineEdit(column["name"] if column else "")
        value = QLineEdit(column["value"] if column else "")
        form.addRow("열 이름", name)
        if column is None or column.get("custom"):
            form.addRow("모든 행에 넣을 값", value)
        body.addLayout(form)
        error = label("", "Muted", True)
        body.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        def save():
            proposed = copy.deepcopy(self.columns)
            target = next((c for c in proposed if c["id"] == fid), None)
            if target is None:
                target = dict(id="custom:" + uuid.uuid4().hex, source=None, enabled=True, custom=True)
                proposed.append(target)
            target.update(name=name.text(), value=value.text())
            try:
                validate_columns(proposed, self.result.columns)
            except ValueError as exc:
                error.setText(str(exc))
                return
            self.undo_columns = None
            self.columns = proposed
            self.columns_changed(target["id"])
            dialog.accept()
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        body.addWidget(buttons)
        dialog.exec()

    def refresh_preview(self):
        if not self.result or not self.result.options.extract_tables:
            return
        try:
            if self.original_view.isChecked():
                specs = [dict(source=k, name=k, value="") for k in self.result.columns]
            else:
                specs = validate_columns(self.columns, self.result.columns)
            start = self.preview_page * 25
            rows = project_records(self.result.records[start:start + 25], specs, self.logger)
        except ValueError as exc:
            self.notice(str(exc))
            return
        header = self.preview.horizontalHeader()
        header.blockSignals(True)
        self.preview.setModel(RecordModel(rows, [s["name"] for s in specs], parent=self.preview))
        for i in range(header.count()):
            header.moveSection(header.visualIndex(i), i)
        header.setSectionsMovable(not self.original_view.isChecked())
        header.blockSignals(False)
        self.preview_hint.setText(f"전체 {len(self.result.records):,}행 저장 · {self.preview_page + 1}페이지 · {len(specs)}열")
        self.preview_prev.setEnabled(self.preview_page > 0)
        self.preview_next.setEnabled((self.preview_page + 1) * 25 < len(self.result.records))

    def header_moved(self, logical, old, new):
        if old != new and not self.original_view.isChecked():
            self.move_field(self.columns[old]["id"], new)

    def change_preview(self, delta):
        self.preview_page = max(0, self.preview_page + delta)
        self.refresh_preview()

    def tab_changed(self, index):
        if hasattr(self, "table_page") and self.tabs.currentWidget() is self.table_page:
            self.refresh_preview()

    def cell_detail(self, index):
        self.text_dialog("셀 전체 내용", str(self.preview.model().rows[index.row()].get(self.preview.model().columns[index.column()], "")))

    def text_dialog(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 520)
        body = layout(dialog, margin=20)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        body.addWidget(view, 1)
        body.addWidget(button("닫기", dialog.accept))
        dialog.exec()

    def mail_detail(self, index):
        mail = self.result.mails[index]
        dialog = QDialog(self)
        dialog.setWindowTitle("메일 상세")
        dialog.resize(800, 580)
        body = layout(dialog, margin=24)
        body.addWidget(label(mail.record.get("subject", "제목 없음"), "SectionTitle", True))
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText("\n".join(f"{LABELS.get(k, k)}: {mail.record.get(k, '')}" for k in ("source_eml", "from", "to", "date", "_status", "_error")) +
                          "\n\n첨부파일\n" + "\n".join(a.name for a in mail.attachments))
        body.addWidget(view, 1)
        def read_body():
            try:
                if mail.body:
                    text = mail.body
                else:
                    message = reader.read_message(mail.source_path)
                    if getattr(message, "_emailtools_hash", "") != mail.content_hash:
                        raise ValueError("분석 후 원본이 변경되었습니다. 다시 분석해 주세요.")
                    text = reader.render_mail_text(message)
                view.setPlainText(text)
            except Exception as exc:
                view.appendPlainText(f"\n본문을 읽지 못했습니다: {exc}")
        body.addWidget(button("본문 읽기", read_body))
        body.addWidget(button("닫기", dialog.accept))
        dialog.exec()

    def field_detail(self, fid):
        if fid.startswith("custom:"):
            self.column_dialog(fid)
            return
        if not self.result or not self.result.catalog or (fid != "tables" and fid not in self.result.catalog.fields):
            self.text_dialog("기본 메일 정보", "원본 파일과 메일 제목은 기본 정보입니다. 순서를 바꾸거나 이름을 편집할 수 있습니다.")
            return
        catalog = self.result.catalog
        scope = self.source_scope.currentData()
        occurrences = [o for o in catalog.occurrences.get(fid, []) if scope == "all" or o.source_kind == scope]
        dialog = QDialog(self)
        dialog.setWindowTitle("항목 근거와 원본 표")
        dialog.resize(1000, 720)
        body = layout(dialog, margin=24)
        body.addWidget(label(catalog.fields[fid]["name"] if fid != "tables" else "원본 표 검토", "Title"))
        body.addWidget(label(self.field_tooltip(fid) if fid != "tables" else "항목으로 읽히지 않은 표도 원본 구조와 함께 확인할 수 있습니다.", "Muted", True))
        source = QComboBox()
        unique = list(dict.fromkeys(o.table_id for o in occurrences)) if fid != "tables" else [t.table_id for t in catalog.tables]
        tables = {t.table_id: t for t in catalog.tables}
        source_page = [0]
        def fill_sources(delta=0):
            source_page[0] = max(0, min(max(0, (len(unique)-1)//50), source_page[0] + delta))
            source.clear()
            for tid in unique[source_page[0]*50:(source_page[0]+1)*50]:
                t = tables[tid]
                source.addItem(f"{t.mail_id} / {t.source_name} / 표 {t.table_index}", tid)
            source_count.setText(f"출처 {len(unique):,}개 · {source_page[0]+1}페이지")
        sources_row = layout(horizontal=True)
        source_count = label("", "Muted")
        sources_row.addWidget(source_count, 1)
        sources_row.addWidget(button("이전 출처", lambda: fill_sources(-1)))
        sources_row.addWidget(button("다음 출처", lambda: fill_sources(1)))
        body.addLayout(sources_row)
        fill_sources()
        source.setMaxVisibleItems(12)
        body.addWidget(source)
        reason = label("", "Muted", True)
        body.addWidget(reason)
        grid = data_table()
        body.addWidget(grid, 1)
        interpretation = combo([("자동 판정", ""), ("항목/값 표로 해석", "key_value"), ("명단·내역 표", "records"), ("배치·서명 표", "layout"), ("구조 확인 필요", "uncertain")])
        row = layout(horizontal=True)
        row.addWidget(interpretation, 1)
        def show_table():
            if source.currentData() is None:
                return
            table = tables[source.currentData()]
            rows = table.rows()
            width = max((c.column + c.colspan for c in table.cells), default=0)
            headers = [str(i + 1) for i in range(width)]
            values = [{str(c.column + 1): c.text for c in row} for row in rows]
            grid.setModel(RecordModel(values, headers, parent=grid))
            positions = [f"행 {o.key_position[0] + 1}, 열 {o.key_position[1] + 1}" for o in occurrences if o.table_id == table.table_id]
            reason.setText(f"판정: {table.shape} · {table.reasons}\n항목 위치: {', '.join(positions[:25])}")
            interpretation.setCurrentIndex(max(0, interpretation.findData(table.override)))
        def apply():
            if source.currentData() is None:
                return
            catalog.override_table(source.currentData(), interpretation.currentData())
            self.result.columns = collect_columns(self.result.records)
            self.dataset = uuid.uuid4().hex
            self.undo_columns = None
            self.refresh_fields()
            self.refresh_preview()
            show_table()
        row.addWidget(button("이 표에 적용", apply))
        body.addLayout(row)
        if fid != "tables":
            body.addWidget(button("모든 등장 값 보기", lambda: self.occurrence_dialog(occurrences)))
        body.addWidget(button("닫기", dialog.accept))
        source.currentIndexChanged.connect(show_table)
        show_table()
        dialog.exec()

    def occurrence_dialog(self, occurrences):
        dialog = QDialog(self)
        dialog.setWindowTitle("전체 등장 기록")
        dialog.resize(820, 620)
        body = layout(dialog, margin=20)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        body.addWidget(view, 1)
        row = layout(horizontal=True)
        count = label("", "Muted")
        row.addWidget(count, 1)
        page = [0]
        def render(delta=0):
            page[0] = max(0, min(max(0, (len(occurrences)-1)//50), page[0]+delta))
            view.setPlainText("\n\n".join(f"{o.mail_id} / {o.source_name} / 행 {o.key_position[0]+1}, 열 {o.key_position[1]+1}\n{o.value or '(빈 값)'}"
                for o in occurrences[page[0]*50:(page[0]+1)*50]))
            count.setText(f"전체 {len(occurrences):,}개 등장 · {page[0]+1}페이지")
        row.addWidget(button("이전 50개", lambda: render(-1)))
        row.addWidget(button("다음 50개", lambda: render(1)))
        body.addLayout(row)
        body.addWidget(button("닫기", dialog.accept))
        render()
        dialog.exec()

    def prepare_export(self):
        if not self.result:
            return
        options = self.result.options
        plan = ExportPlan.from_options(options)
        for name, check in self.export_checks.items():
            check.blockSignals(True)
            check.setChecked(getattr(plan, name))
            available = dict(attachments=options.save_attachments, body=options.save_mail, text=options.extract_text,
                             tables=options.extract_tables, attachment_index=True, archive=True)[name]
            check.setEnabled(available)
            check.setVisible(available)
            check.blockSignals(False)
        if not self.output_path.text():
            base = self.result.source_root
            if base.is_relative_to(self.root):
                base = Path.home() / "Documents" / "EmailTools"
            self.output_path.setText(str(base / "_EML_OUTPUT"))
        self.export_summary.setText(f"MailList.xlsx  ·  전체 {len(self.result.mails):,}개 메일\n첨부파일 {self.result.attachment_count:,}개  ·  처리 기록과 CSV 목록 포함")
        self.show_page(2)

    def export_plan(self):
        return ExportPlan(**{key: check.isChecked() for key, check in self.export_checks.items()})

    def update_export(self):
        if not self.result or not hasattr(self, "primary"):
            return
        plan = self.export_plan()
        count = sum(not c.get("base") for c in self.columns)
        self.column_summary.setText("표 열 순서  ·  " + " → ".join(c["name"] for c in self.columns) if plan.tables else "표 Excel은 이번 저장에서 제외됩니다.")
        blocked = plan.tables and not count
        self.exclude_tables.setVisible(blocked)
        if self.stack.currentIndex() == 2:
            self.primary.setEnabled(not blocked and bool(self.output_path.text().strip()) and not self.busy)
            self.footer_hint.setText("표 항목을 선택하거나 표 Excel을 명시적으로 제외해 주세요." if blocked else "선택한 구성으로 새 결과 폴더를 만듭니다.")

    def pick_output(self):
        path = QFileDialog.getExistingDirectory(self, "결과 저장 폴더", self.output_path.text())
        if path:
            self.output_path.setText(path)

    def start_export(self):
        plan = self.export_plan()
        try:
            result = plan.apply(self.result)
            if plan.tables and not any(not c.get("base") for c in self.columns):
                raise ValueError("추출 항목이나 사용자 열을 선택해 주세요.")
            specs = copy.deepcopy(self.columns)
            if plan.tables:
                validate_columns(specs, result.columns)
            if not self.output_path.text().strip():
                raise ValueError("저장 위치를 선택해 주세요.")
            destination = Path(self.output_path.text().strip())
        except ValueError as exc:
            self.notice(str(exc))
            return
        def operation(status, cancelled):
            return export_results(result, destination, self.logger, columns=specs,
                get_log=self.log.getvalue, archive=plan.archive, progress=status, is_cancelled=cancelled)
        def complete(folder):
            self.last_folder = folder
            self.finish_progress("결과가 저장되었습니다", str(folder))
            self.refresh_output_links()
        self.task_kind = "save"
        self.progress_steps.setText("결과 파일 작성  →  " + ("ZIP 생성  →  " if plan.archive else "") + "저장 마무리")
        self.begin_work(operation, complete, "결과를 저장하고 있습니다")

    def refresh_output_links(self):
        while self.output_links.count():
            item = self.output_links.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.last_folder:
            return
        for title, path in (("결과 폴더 열기", self.last_folder), ("메일 목록 열기", self.last_folder / "MailList.xlsx"),
                ("표 Excel 열기", self.last_folder / "tables/EML_Table_Result.xlsx"),
                ("전체 ZIP 열기", self.last_folder / "EmailTools_Result.zip")):
            if path.exists():
                self.output_links.addWidget(button(title, lambda checked=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))))

    def help_dialog(self):
        self.text_dialog("EmailTools 사용 안내", "1. 원하는 작업을 선택합니다. 처음에는 ‘메일 목록만’이 선택됩니다.\n"
            "2. 폴더 또는 EML 파일을 선택하고 분석 버튼을 누릅니다. 샘플로 먼저 연습할 수 있습니다.\n"
            "3. 메일·첨부 목록과 표 항목의 근거를 검토합니다.\n"
            "4. 필요한 표 항목을 추가하고 끌어서 순서를 바꿉니다. ⓘ 또는 F1으로 원본 표를 확인합니다.\n"
            "5. 저장 구성 확인에서 위치와 산출물을 선택하고 결과 저장을 누릅니다.\n\n"
            "표 분석 대상은 메일 HTML 본문과 첨부 DOCX입니다. PDF·XLSX·PPTX는 텍스트 추출만 지원합니다.\n"
            "검색·출처 필터는 조회에만 적용됩니다. 저장은 전체 메일과 선택한 열을 사용합니다.\n"
            "목록만 작업은 본문과 첨부 내용을 디코딩하지 않습니다. 첨부 크기는 ‘확인 안 함’으로 표시됩니다.\n"
            "중지는 안전한 처리 경계에서 완료됩니다. 이전 결과는 유지됩니다.\n\n"
            "Ctrl+O: 파일 선택 / Ctrl+Enter: 다음 단계 / Alt+방향키: 선택 열 이동 / Delete: 열 제외 / F1: 출처\n\n"
            "Qt for Python (PySide6 Essentials) 6.10.2\nhttps://doc.qt.io/qtforpython-6/\n"
            "런타임·Qt 및 타사 라이선스는 THIRD_PARTY_LICENSES와 runtime/desktop의 dist-info/licenses에 포함됩니다.")

    def closeEvent(self, event):
        if self.worker:
            self.close_pending = True
            self.cancel_work()
            event.ignore()
            return
        self.log_handler.close()
        if self.file_log_handler:
            self.file_log_handler.close()
        self.temp.cleanup()
        event.accept()


def main() -> int:
    parser = argparse.ArgumentParser(description="EmailTools Windows 데스크톱")
    parser.add_argument("sources", nargs="*", help="EML 파일 또는 폴더 (여러 개 가능)")
    parser.add_argument("--desktop-smoke", type=Path, metavar="OUTPUT", help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setStyle("Fusion")
    app.setApplicationName("EmailTools")
    app.setApplicationVersion(__version__)
    font = QFont("Segoe UI")
    font.setPixelSize(13)
    app.setFont(font)
    window = Window(args.sources, remember=args.desktop_smoke is None)
    window.show()
    if args.desktop_smoke:
        from emailtools.desktop.smoke import run_smoke
        QTimer.singleShot(100, lambda: run_smoke(app, window, args.desktop_smoke))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
