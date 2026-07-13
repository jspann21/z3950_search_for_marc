"""Central visual tokens for the desktop interface."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

APP_STYLESHEET = """
QMainWindow, QDialog { background: #f5f7fa; }
QWidget { color: #172033; font-size: 13px; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #d7deea;
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QSpinBox, QTabWidget::pane, QTableView, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
}
QLineEdit, QSpinBox { min-height: 30px; padding: 0 7px; }
QLineEdit:focus, QSpinBox:focus, QTableView:focus, QPlainTextEdit:focus {
    border: 1px solid #2563eb;
}
QPushButton {
    min-height: 30px;
    padding: 0 12px;
    border: 1px solid #b8c2d1;
    border-radius: 5px;
    background: #ffffff;
}
QPushButton:hover { background: #eef3fa; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; }
QPushButton[primary="true"] {
    color: #ffffff;
    background: #2563eb;
    border-color: #2563eb;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: #1d4ed8; }
QPushButton[danger="true"] { color: #b42318; border-color: #f1aaa5; }
QHeaderView::section {
    background: #eef2f7;
    border: 0;
    border-bottom: 1px solid #cbd5e1;
    padding: 7px;
    font-weight: 600;
}
QTableView {
    gridline-color: #e6ebf2;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}
QProgressBar {
    border: 0;
    border-radius: 3px;
    background: #dce3ed;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk { border-radius: 3px; background: #2563eb; }
QTabBar::tab { padding: 7px 12px; }
QTabBar::tab:selected { color: #1d4ed8; font-weight: 600; }
QSplitter::handle { background: #d7deea; width: 1px; height: 1px; }
"""


def apply_theme(app: QApplication) -> None:
    """Apply application-wide styling in one place."""
    app.setStyleSheet(APP_STYLESHEET)
