from __future__ import annotations

from typing import cast

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLineEdit

from z3950_search_for_marc.theme import apply_theme


def test_standard_context_menus_use_readable_application_colors(qtbot) -> None:
    app = cast(QApplication | None, QApplication.instance())
    assert app is not None
    original_stylesheet = app.styleSheet()
    editor = QLineEdit("Context menu")
    qtbot.addWidget(editor)

    try:
        apply_theme(app)
        editor.selectAll()
        menu = editor.createStandardContextMenu()
        qtbot.addWidget(menu)
        menu.ensurePolished()
        menu.adjustSize()

        palette = menu.palette()
        assert palette.color(QPalette.ColorRole.Window).name() == "#ffffff"
        assert palette.color(QPalette.ColorRole.WindowText).name() == "#172033"
        assert menu.actionGeometry(menu.actions()[0]).x() >= 8
    finally:
        app.setStyleSheet(original_stylesheet)
