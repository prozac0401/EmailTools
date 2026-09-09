"""Native table models and accessible wrapping field chips."""
from __future__ import annotations
import json
import math
from PySide6.QtCore import Qt, Signal, QSize, QRect, QMimeData, QAbstractTableModel
from PySide6.QtGui import QColor, QPainter, QPen, QDrag
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QStyledItemDelegate, QAbstractItemView,
    QApplication, QTableView, QHeaderView, QFrame)

ROLE = Qt.ItemDataRole.UserRole
MIME = "application/x-emailtools-column"


class RecordModel(QAbstractTableModel):
    def __init__(self, rows=(), columns=(), labels=None, parent=None):
        super().__init__(parent)
        self.rows, self.columns = list(rows), list(columns)
        self.labels = labels or {}

    def rowCount(self, parent=None):
        return len(self.rows)

    def columnCount(self, parent=None):
        return len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.rows[index.row()].get(self.columns[index.column()], "")
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return str(value) if value not in (None, "") else "—"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.labels.get(self.columns[section], self.columns[section]) if orientation == Qt.Orientation.Horizontal else str(section + 1)


def data_table():
    table = QTableView()
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setDefaultSectionSize(40)
    table.verticalHeader().setMinimumWidth(38)
    table.horizontalHeader().setMinimumSectionSize(100)
    table.horizontalHeader().setDefaultSectionSize(190)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(False)
    return table


class DropFrame(QFrame):
    pathsDropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.pathsDropped.emit([u.toLocalFile() for u in event.mimeData().urls()])
        event.acceptProposedAction()


class ChipDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        data = index.data(ROLE)
        name = data.get("display", data["name"])
        width = min(285, max(150, option.fontMetrics.horizontalAdvance(name) + 100))
        lines = max(1, math.ceil(option.fontMetrics.horizontalAdvance(name) / (width - 90)))
        return QSize(width, max(40, 16 + lines * option.fontMetrics.height()))

    def paint(self, painter, option, index):
        data = index.data(ROLE)
        rect = option.rect.adjusted(1, 1, -1, -1)
        selected = self.parent().selected_list
        active = self.parent().currentIndex() == index
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = "#eef6fa" if selected else "#ffffff"
        if data.get("custom"):
            color = "#f4effb"
        painter.setBrush(QColor(color))
        painter.setPen(QPen(QColor("#228093" if active else "#d6e1ec"), 2 if active else 1))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor("#668094"))
        prefix = str(index.row() + 1) if selected else "+"
        painter.drawText(rect.adjusted(10, 0, -rect.width() + 33, 0), Qt.AlignmentFlag.AlignVCenter, prefix)
        painter.setPen(QColor("#253c51"))
        painter.drawText(rect.adjusted(37, 5, -48, -5), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                         data.get("display", data["name"]))
        painter.setPen(QColor("#648294"))
        painter.drawText(QRect(rect.right() - 43, rect.top(), 21, rect.height()), Qt.AlignmentFlag.AlignCenter, "ⓘ")
        if selected and not data.get("base"):
            painter.drawText(QRect(rect.right() - 22, rect.top(), 21, rect.height()), Qt.AlignmentFlag.AlignCenter, "×")
        painter.restore()


class ChipList(QListWidget):
    activatedField = Signal(str)
    infoField = Signal(str)
    removedField = Signal(str)
    droppedField = Signal(str, int, bool)
    movedField = Signal(str, int)

    def __init__(self, selected=False):
        super().__init__()
        self.selected_list = selected
        self.dataset = ""
        self.dragging = False
        self.press_position = None
        self.insertion = None
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(6)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setItemDelegate(ChipDelegate(self))
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(40)
        self.setMinimumHeight(94)

    def populate(self, fields, dataset):
        current = self.currentItem().data(ROLE)["id"] if self.currentItem() else None
        scroll = self.verticalScrollBar().value()
        self.clear()
        self.dataset = dataset
        for field in fields:
            item = QListWidgetItem()
            item.setText(field.get("display", field["name"]))
            item.setData(ROLE, field)
            item.setToolTip(field.get("tooltip", field["name"]))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, item.text())
            self.addItem(item)
            if field["id"] == current:
                self.setCurrentItem(item)
        self.verticalScrollBar().setValue(scroll)

    def mousePressEvent(self, event):
        self.press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_position is not None and event.buttons() & Qt.MouseButton.LeftButton:
            item = self.itemAt(self.press_position)
            if item and self.press_position.x() < self.visualItemRect(item).right() - 46 and (
                    event.position().toPoint() - self.press_position).manhattanLength() >= QApplication.startDragDistance():
                data = item.data(ROLE)
                mime = QMimeData()
                mime.setData(MIME, json.dumps(dict(dataset=self.dataset, id=data["id"], selected=self.selected_list)).encode())
                drag = QDrag(self)
                drag.setMimeData(mime)
                rect = self.visualItemRect(item)
                drag.setPixmap(self.viewport().grab(rect))
                drag.setHotSpot(self.press_position - rect.topLeft())
                self.dragging = True
                self.press_position = None
                drag.exec(Qt.DropAction.MoveAction)
                self.dragging = False
                self.insertion = None
                self.viewport().update()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        clicked = self.press_position is not None and not self.dragging
        self.press_position = None
        super().mouseReleaseEvent(event)
        if item and clicked:
            data = item.data(ROLE)
            right = self.visualItemRect(item).right() - event.position().x()
            if right < 23 and self.selected_list and not data.get("base"):
                self.removedField.emit(data["id"])
            elif right < 46:
                self.infoField.emit(data["id"])
            elif not self.selected_list:
                self.activatedField.emit(data["id"])

    def _payload(self, event):
        if event.mimeData().hasFormat(MIME) and isinstance(event.source(), ChipList):
            try:
                data = json.loads(bytes(event.mimeData().data(MIME)))
                if data["dataset"] == self.dataset:
                    return data
            except (ValueError, KeyError):
                pass
        return None

    def dragEnterEvent(self, event):
        if self._payload(event):
            event.acceptProposedAction()

    def insertion_index(self, point):
        for i in range(self.count()):
            rect = self.visualItemRect(self.item(i))
            if point.y() < rect.top() or (point.y() <= rect.bottom() and point.x() < rect.center().x()):
                return i
        return self.count()

    def dragMoveEvent(self, event):
        if self._payload(event):
            point = event.position().toPoint()
            self.insertion = self.insertion_index(point)
            bar = self.verticalScrollBar()
            if point.y() < 36:
                bar.setValue(bar.value() - 12)
            elif point.y() > self.viewport().height() - 36:
                bar.setValue(bar.value() + 12)
            self.viewport().update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.insertion = None
        self.viewport().update()
        event.accept()

    def dropEvent(self, event):
        data = self._payload(event)
        if data:
            position = self.insertion if self.insertion is not None else self.insertion_index(event.position().toPoint())
            self.insertion = None
            self.droppedField.emit(data["id"], position, data["selected"])
            event.acceptProposedAction()
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.insertion is not None and self.selected_list:
            rect = self.visualItemRect(self.item(min(self.insertion, self.count() - 1))) if self.count() else QRect(8, 8, 8, 44)
            x = rect.left() - 3 if self.insertion < self.count() else rect.right() + 3
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor("#16889a"), 3))
            painter.drawLine(x, rect.top(), x, rect.bottom())
            painter.end()

    def keyPressEvent(self, event):
        item = self.currentItem()
        if item:
            fid = item.data(ROLE)["id"]
            if event.key() == Qt.Key.Key_F1:
                self.infoField.emit(fid)
                return
            if event.modifiers() & Qt.KeyboardModifier.AltModifier and self.selected_list:
                key = event.key()
                delta = -1 if key in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
                position = self.currentRow() + delta
                if key == Qt.Key.Key_Home:
                    position = 0
                elif key == Qt.Key.Key_End:
                    position = self.count() - 1
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
                    self.movedField.emit(fid, position)
                    return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Space) and not self.selected_list:
                self.activatedField.emit(fid)
                return
            if event.key() == Qt.Key.Key_Delete and self.selected_list and not item.data(ROLE).get("base"):
                self.removedField.emit(fid)
                return
        super().keyPressEvent(event)
