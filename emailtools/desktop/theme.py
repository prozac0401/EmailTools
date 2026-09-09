"""Shared desktop typography, spacing and color tokens."""
from PySide6.QtGui import QIcon
from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt

PATHS = {
    "mail": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m3 7 9 6 9-6"/>',
    "folder": '<path d="M3 8V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "table": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 9v12M3 15h18"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Zm0 0v6h6M8 13h8M8 17h5"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Zm-4 9 3 3 5-6"/>',
}


def icon(name, color="#65758b", size=24):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def stylesheet(large=False):
    size = 15 if large else 13
    return """
    * { font-family: 'Segoe UI', 'Malgun Gothic'; font-size: SIZEpx; color: #26354b; }
    QMainWindow, QDialog { background: #f5f7fb; }
    QWidget#Workspace { background: #f5f7fb; }
    QFrame#Rail { background: #142339; border: none; }
    #Rail QLabel { color: #aebed0; background: transparent; }
    #Rail QLabel#Brand { color: #ffffff; font-size: 21px; font-weight: 700; }
    #Rail QLabel#RailCaption { color: #7e93ad; font-size: 12px; }
    #Rail QPushButton { background: transparent; border: none; color: #aebed0; text-align: left; padding: 14px 16px; border-radius: 9px; }
    #Rail QPushButton:checked { background: #263d57; color: #ffffff; }
    #Rail QPushButton:hover { background: #20344e; color: white; }
    QLabel { background: transparent; }
    QLabel#Title { font-size: 22px; font-weight: 700; color: #192c43; }
    QLabel#SectionTitle { font-size: 16px; font-weight: 650; color: #21334b; }
    QLabel#Muted { color: #66778e; }
    QLabel#Eyebrow { color: #526783; font-size: 12px; font-weight: 600; }
    QLabel#MetricValue { color: #172e48; font-size: 23px; font-weight: 650; }
    QLabel#Tag { color: #147f75; background: #e3f4ef; padding: 6px 10px; border-radius: 6px; font-size: 12px; }
    QFrame#Panel, QFrame#Metric { background: white; border: 1px solid #e0e6ef; border-radius: 12px; }
    QFrame#DropZone { background: #fafcfe; border: 1px dashed #b8c9dc; border-radius: 12px; }
    QFrame#Card { background: white; border: 1px solid #dce4ee; border-radius: 12px; }
    QFrame#Card[selected="true"] { background: #f1f9fc; border: 2px solid #278795; }
    QPushButton, QToolButton { background: white; border: 1px solid #d9e2ed; border-radius: 7px; padding: 8px 13px; min-height: 20px; font-weight: 550; }
    QPushButton:hover, QToolButton:hover { background: #edf3f9; border-color: #b2c6da; }
    QPushButton:pressed { background: #dfe9f4; }
    QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus { border: 2px solid #368caa; }
    QPushButton:disabled, QToolButton:disabled { background: #e9edf3; color: #929fb0; border-color: #e1e7ef; }
    QPushButton#Primary { background: #176f83; border: 1px solid #176f83; color: white; padding: 11px 24px; }
    QPushButton#Primary:hover { background: #125d70; }
    QPushButton#Primary:disabled { background: #cbd9e0; border-color: #cbd9e0; color: #718491; }
    QPushButton#Link { background: transparent; border: none; color: #25798e; padding: 6px 8px; }
    QLineEdit, QPlainTextEdit, QComboBox { background: white; border: 1px solid #d9e2ed; border-radius: 7px; padding: 9px 12px; selection-background-color: #d4e8ef; }
    QLineEdit { font-size: INPUTpx; min-height: 20px; }
    QComboBox { min-height: 22px; }
    QComboBox QAbstractItemView { background: white; padding: 6px; selection-background-color: #e3eff6; selection-color: #26354b; }
    QCheckBox { spacing: 8px; padding: 5px 0; }
    QCheckBox::indicator { width: 17px; height: 17px; }
    QTabWidget::pane { background: white; border: 1px solid #e0e6ef; border-radius: 10px; }
    QTabBar::tab { background: transparent; border-bottom: 3px solid transparent; color: #62738a; padding: 13px 20px; margin-right: 4px; }
    QTabBar::tab:selected { color: #176f83; border-bottom: 3px solid #176f83; font-weight: 650; }
    QTableView { background: white; alternate-background-color: #f8fafc; border: none; gridline-color: #edf1f6; selection-background-color: #e1f0f4; selection-color: #192f48; }
    QHeaderView::section { background: #f4f7fb; color: #586b83; padding: 12px 10px; border: none; border-bottom: 1px solid #e0e6ef; font-weight: 600; }
    QTableCornerButton::section { background: #f4f7fb; border: none; }
    QListWidget { background: transparent; border: none; outline: none; }
    QScrollArea { border: none; background: transparent; }
    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #c2cddb; border-radius: 4px; min-height: 28px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: #f4f7fb; height: 10px; }
    QScrollBar::handle:horizontal { background: #c2cddb; border-radius: 4px; min-width: 28px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QProgressBar { background: #e6edf4; border: none; border-radius: 5px; min-height: 10px; max-height: 10px; }
    QProgressBar::chunk { background: #218796; border-radius: 5px; }
    QSplitter::handle { background: #e6ecf3; height: 5px; }
    QToolTip { background: #1d3048; color: white; border: 1px solid #40556e; padding: 10px; font-size: SIZEpx; }
    QStatusBar { background: #f5f7fb; color: #66778e; font-size: 12px; }
    """.replace("SIZE", str(size)).replace("INPUT", str(size + 1))
