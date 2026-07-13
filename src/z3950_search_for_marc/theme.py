"""Central visual tokens for the desktop interface."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

APP_STYLESHEET = """
QMainWindow, QDialog { background: #f3f6fa; }
QWidget { color: #172033; font-size: 13px; }
QWidget#sidebar {
    background: #f8fafc;
    border-right: 1px solid #d9e1ec;
}
QLabel#pageTitle { font-size: 21px; font-weight: 700; color: #111827; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; color: #111827; }
QLabel#secondaryText { color: #5d6b80; }
QLabel#exportMode {
    color: #9a3412;
    background: #fff7ed;
    border: 1px solid #fed7aa;
    border-radius: 4px;
    padding: 5px 8px;
}
QLabel#failureDetail {
    color: #991b1b;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 5px;
    padding: 7px 9px;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #d7deea;
    border-radius: 7px;
    margin-top: 10px;
    padding: 12px 10px 9px 10px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QLineEdit, QSpinBox, QTableView, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
}
QLineEdit, QSpinBox { min-height: 31px; padding: 0 8px; }
QLineEdit:focus, QSpinBox:focus, QTableView:focus, QPlainTextEdit:focus {
    border-color: #2563eb;
}
QPushButton {
    min-height: 31px;
    padding: 0 13px;
    border: 1px solid #b8c2d1;
    border-radius: 5px;
    background: #ffffff;
}
QPushButton:hover { background: #eef3fa; border-color: #94a3b8; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; border-color: #dbe2ea; }
QPushButton[primary="true"] {
    min-height: 35px;
    color: #ffffff;
    background: #2563eb;
    border-color: #2563eb;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton[danger="true"] { color: #b42318; border-color: #f1aaa5; }
QPushButton#activityToggle {
    min-height: 32px;
    padding: 0 10px;
    text-align: left;
    font-weight: 600;
    background: #f8fafc;
    border-color: #d7deea;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    min-height: 30px;
    padding: 0 14px;
    color: #475569;
    background: #e8edf4;
    border: 1px solid #cbd5e1;
    border-bottom: 0;
}
QTabBar::tab:first { border-top-left-radius: 5px; }
QTabBar::tab:last { border-top-right-radius: 5px; }
QTabBar::tab:selected {
    color: #1d4ed8;
    background: #ffffff;
    font-weight: 600;
}
QTabBar::tab:hover:!selected { background: #dfe6ef; }
QHeaderView::section {
    background: #eef2f7;
    color: #334155;
    border: 0;
    border-bottom: 1px solid #cbd5e1;
    border-right: 1px solid #dde4ed;
    padding: 8px;
    font-weight: 600;
}
QTableView {
    gridline-color: #e6ebf2;
    selection-background-color: #dbeafe;
    selection-color: #172033;
    alternate-background-color: #f8fafc;
}
QTableView::item { padding: 4px 7px; }
QProgressBar {
    border: 0;
    border-radius: 3px;
    background: #dce3ed;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
}
QProgressBar::chunk { border-radius: 3px; background: #2563eb; }
QCheckBox { spacing: 7px; }
QSplitter::handle { background: #d7deea; width: 1px; height: 1px; }
QStatusBar { color: #526176; background: #f8fafc; border-top: 1px solid #d9e1ec; }
QMenuBar { background: #f8fafc; border-bottom: 1px solid #d9e1ec; }
QMenuBar::item { padding: 6px 10px; }
QMenuBar::item:selected { background: #e8edf4; }
"""


def apply_theme(app: QApplication) -> None:
    """Apply application-wide styling in one place."""
    app.setStyleSheet(APP_STYLESHEET)
