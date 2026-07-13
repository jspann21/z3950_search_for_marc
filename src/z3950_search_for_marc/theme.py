"""Central palettes, styles, and semantic colors for the desktop interface."""

# ruff: noqa: E501 -- keeping complete Qt stylesheet rules together is easier to audit.

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QStyle

from .domain.models import ServerStatus, Theme
from .resources import resource_path


@dataclass(frozen=True, slots=True)
class ThemeColors:
    window: str
    surface: str
    sidebar: str
    text: str
    title: str
    muted: str
    border: str
    field_border: str
    hover: str
    pressed: str
    disabled_text: str
    disabled_surface: str
    accent: str
    accent_hover: str
    primary_text: str
    selection: str
    selection_text: str
    header: str
    alternate: str
    error_text: str
    error_surface: str
    error_border: str
    warning_text: str
    warning_surface: str
    warning_border: str
    success: str
    timeout: str
    canceled: str
    scrollbar: str


LIGHT = ThemeColors(
    window="#f3f6fa",
    surface="#ffffff",
    sidebar="#f8fafc",
    text="#172033",
    title="#111827",
    muted="#5d6b80",
    border="#d7deea",
    field_border="#cbd5e1",
    hover="#eef3fa",
    pressed="#e2e8f0",
    disabled_text="#94a3b8",
    disabled_surface="#f1f5f9",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    primary_text="#ffffff",
    selection="#dbeafe",
    selection_text="#172033",
    header="#eef2f7",
    alternate="#f8fafc",
    error_text="#991b1b",
    error_surface="#fef2f2",
    error_border="#fecaca",
    warning_text="#9a3412",
    warning_surface="#fff7ed",
    warning_border="#fed7aa",
    success="#166534",
    timeout="#b45309",
    canceled="#64748b",
    scrollbar="#cbd5e1",
)

DARK = ThemeColors(
    window="#101827",
    surface="#182235",
    sidebar="#131d2e",
    text="#e5edf8",
    title="#f8fafc",
    muted="#a8b7cc",
    border="#2c3b52",
    field_border="#40516b",
    hover="#263650",
    pressed="#33445f",
    disabled_text="#71829b",
    disabled_surface="#202d42",
    accent="#2563eb",
    accent_hover="#3b82f6",
    primary_text="#ffffff",
    selection="#234b7a",
    selection_text="#f8fafc",
    header="#202d42",
    alternate="#1d293d",
    error_text="#fecaca",
    error_surface="#481f2a",
    error_border="#8f3543",
    warning_text="#fed7aa",
    warning_surface="#4a301c",
    warning_border="#8c5a2c",
    success="#86efac",
    timeout="#fcd34d",
    canceled="#b8c5d8",
    scrollbar="#4b5f7d",
)

_COLORS = {Theme.LIGHT: LIGHT, Theme.DARK: DARK}


def _stylesheet(
    c: ThemeColors,
    *,
    checkbox_check_path: str,
    spinbox_up_path: str,
    spinbox_down_path: str,
) -> str:
    """Render a complete Qt stylesheet from one semantic token set."""
    return f"""
QMainWindow, QDialog {{ background: {c.window}; }}
QWidget {{ color: {c.text}; font-size: 13px; }}
QToolTip {{ color: {c.text}; background: {c.surface}; border: 1px solid {c.border}; padding: 4px; }}
QWidget#sidebar {{ background: {c.sidebar}; border-right: 1px solid {c.border}; }}
QLabel#pageTitle {{ font-size: 21px; font-weight: 700; color: {c.title}; }}
QLabel#sectionTitle {{ font-size: 17px; font-weight: 700; color: {c.title}; }}
QLabel#secondaryText {{ color: {c.muted}; }}
QLabel#fieldHint {{ color: {c.muted}; font-size: 12px; }}
QLabel#exportMode {{ color: {c.warning_text}; background: {c.warning_surface}; border: 1px solid {c.warning_border}; border-radius: 4px; padding: 5px 8px; }}
QLabel#failureDetail {{ color: {c.error_text}; background: {c.error_surface}; border: 1px solid {c.error_border}; border-radius: 5px; padding: 7px 9px; }}
QGroupBox {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 7px; margin-top: 10px; padding: 12px 10px 9px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
QLineEdit, QSpinBox, QComboBox, QTableView, QPlainTextEdit {{ background: {c.surface}; border: 1px solid {c.field_border}; }}
QLineEdit, QSpinBox, QComboBox {{ border-radius: 5px; min-height: 31px; padding: 0 8px; }}
QSpinBox {{ padding-right: 28px; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 24px; background: {c.header}; border-left: 1px solid {c.field_border}; border-bottom: 1px solid {c.field_border}; border-top-right-radius: 4px; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; background: {c.header}; border-left: 1px solid {c.field_border}; border-bottom-right-radius: 4px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c.hover}; }}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: {c.pressed}; }}
QSpinBox::up-arrow {{ image: url("{spinbox_up_path}"); width: 10px; height: 6px; }}
QSpinBox::down-arrow {{ image: url("{spinbox_down_path}"); width: 10px; height: 6px; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTableView:focus, QPlainTextEdit:focus {{ border-color: {c.accent}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{ color: {c.disabled_text}; background: {c.disabled_surface}; }}
QComboBox::drop-down {{ border: 0; width: 25px; }}
QComboBox QAbstractItemView {{ color: {c.text}; background: {c.surface}; border: 1px solid {c.field_border}; selection-background-color: {c.selection}; selection-color: {c.selection_text}; }}
QPushButton {{ min-height: 31px; padding: 0 13px; border: 1px solid {c.field_border}; border-radius: 5px; background: {c.surface}; }}
QPushButton:hover {{ background: {c.hover}; border-color: {c.scrollbar}; }}
QPushButton:pressed {{ background: {c.pressed}; }}
QPushButton:disabled {{ color: {c.disabled_text}; background: {c.disabled_surface}; border-color: {c.border}; }}
QPushButton[primary="true"] {{ min-height: 35px; color: {c.primary_text}; background: {c.accent}; border-color: {c.accent}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
QPushButton[danger="true"] {{ color: {c.error_text}; border-color: {c.error_border}; }}
QPushButton#activityToggle {{ min-height: 32px; padding: 0 10px; text-align: left; font-weight: 600; background: {c.sidebar}; border-color: {c.border}; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {c.field_border}; background: {c.surface}; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; }}
QCheckBox::indicator:checked {{ image: url("{checkbox_check_path}"); }}
QTabWidget::pane {{ background: {c.surface}; border: 1px solid {c.field_border}; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; top: -1px; }}
QTabBar::tab {{ min-height: 30px; padding: 0 14px; color: {c.muted}; background: {c.header}; border: 1px solid {c.field_border}; border-bottom: 0; }}
QTabBar::tab:first {{ border-top-left-radius: 5px; }} QTabBar::tab:last {{ border-top-right-radius: 5px; }}
QTabBar::tab:selected {{ color: {c.accent}; background: {c.surface}; font-weight: 600; }}
QTabBar::tab:hover:!selected {{ background: {c.hover}; }}
QHeaderView::section {{ background: {c.header}; color: {c.text}; border: 0; border-bottom: 1px solid {c.field_border}; border-right: 1px solid {c.border}; padding: 8px; font-weight: 600; }}
QTableView {{ gridline-color: {c.border}; selection-background-color: {c.selection}; selection-color: {c.selection_text}; alternate-background-color: {c.alternate}; }}
QTableView::item {{ padding: 4px 7px; }}
QProgressBar {{ border: 0; border-radius: 3px; background: {c.border}; min-height: 6px; max-height: 6px; text-align: center; }}
QProgressBar::chunk {{ border-radius: 3px; background: {c.accent}; }}
QScrollBar:vertical {{ background: {c.sidebar}; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: {c.sidebar}; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: {c.scrollbar}; border-radius: 5px; min-height: 24px; min-width: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {c.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: {c.border}; width: 1px; height: 1px; }}
QStatusBar {{ color: {c.muted}; background: {c.sidebar}; border-top: 1px solid {c.border}; }}
QMenuBar {{ background: {c.sidebar}; border-bottom: 1px solid {c.border}; }}
QMenuBar::item {{ padding: 6px 10px; }} QMenuBar::item:selected {{ background: {c.header}; }}
QMenu {{ color: {c.text}; background: {c.surface}; border: 1px solid {c.field_border}; padding: 5px 8px; }}
QMenu::item {{ padding: 6px 24px 6px 20px; background: transparent; }}
QMenu::item:selected {{ color: {c.selection_text}; background: {c.selection}; }}
QMenu::item:disabled {{ color: {c.disabled_text}; }}
QMenu::separator {{ height: 1px; background: {c.border}; margin: 4px 8px; }}
"""


def current_theme(app: QApplication | None = None) -> Theme:
    """Return the active theme, defaulting safely to light."""
    application = app or QApplication.instance()
    if application is None:
        return Theme.LIGHT
    try:
        return Theme(str(application.property("applicationTheme")))
    except ValueError:
        return Theme.LIGHT


def colors_for(theme: Theme | None = None) -> ThemeColors:
    return _COLORS[theme or current_theme()]


def status_color(status: ServerStatus) -> QColor:
    """Return a readable semantic status color for the active theme."""
    colors = colors_for()
    values = {
        ServerStatus.SUCCESS: colors.success,
        ServerStatus.FAILED: colors.error_text,
        ServerStatus.TIMED_OUT: colors.timeout,
        ServerStatus.CANCELED: colors.canceled,
    }
    return QColor(values.get(status, colors.muted))


def _palette(c: ThemeColors) -> QPalette:
    palette = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, QColor(c.window))
        palette.setColor(group, QPalette.ColorRole.WindowText, QColor(c.text))
        palette.setColor(group, QPalette.ColorRole.Base, QColor(c.surface))
        palette.setColor(group, QPalette.ColorRole.AlternateBase, QColor(c.alternate))
        palette.setColor(group, QPalette.ColorRole.Text, QColor(c.text))
        palette.setColor(group, QPalette.ColorRole.Button, QColor(c.surface))
        palette.setColor(group, QPalette.ColorRole.ButtonText, QColor(c.text))
        palette.setColor(group, QPalette.ColorRole.Highlight, QColor(c.selection))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(c.selection_text))
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, QColor(c.surface))
        palette.setColor(group, QPalette.ColorRole.ToolTipText, QColor(c.text))
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, QColor(c.muted))
        palette.setColor(group, QPalette.ColorRole.Link, QColor(c.accent))
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Window, QColor(c.window))
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(c.disabled_text))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(c.disabled_surface))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(c.disabled_text))
    palette.setColor(disabled, QPalette.ColorRole.Button, QColor(c.disabled_surface))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(c.disabled_text))
    palette.setColor(disabled, QPalette.ColorRole.PlaceholderText, QColor(c.disabled_text))
    return palette


def _tinted_pixmap(source: QPixmap, color: QColor) -> QPixmap:
    tinted = source.copy()
    painter = QPainter(tinted)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return tinted


def _themed_menu_icon(source: QIcon, size: QSize) -> QIcon:
    source_pixmap = source.pixmap(size, QIcon.Mode.Normal, QIcon.State.Off)
    if source_pixmap.isNull():
        return source
    colors = colors_for()
    enabled = _tinted_pixmap(source_pixmap, QColor(colors.text))
    disabled = _tinted_pixmap(source_pixmap, QColor(colors.disabled_text))
    themed = QIcon()
    for state in (QIcon.State.Off, QIcon.State.On):
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
            themed.addPixmap(enabled, mode, state)
        themed.addPixmap(disabled, QIcon.Mode.Disabled, state)
    return themed


class _MenuIconTheme(QObject):
    """Give native Qt action icons a readable color whenever a menu opens."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(watched, QMenu):
            icon_extent = watched.style().pixelMetric(
                QStyle.PixelMetric.PM_SmallIconSize, None, watched
            )
            icon_size = QSize(icon_extent, icon_extent)
            for action in watched.actions():
                icon = action.icon()
                if not icon.isNull():
                    action.setIcon(_themed_menu_icon(icon, icon_size))
        return super().eventFilter(watched, event)


_menu_icon_theme: _MenuIconTheme | None = None


def apply_theme(app: QApplication, theme: Theme = Theme.LIGHT) -> None:
    """Apply one complete light or dark appearance to the running application."""
    global _menu_icon_theme
    theme = Theme(theme)
    app.setStyle("Fusion")
    app.setProperty("applicationTheme", theme.value)
    app.setPalette(_palette(colors_for(theme)))
    checkbox_check_path = resource_path("checkbox-check.svg").as_posix()
    spinbox_up_path = resource_path(f"spinbox-up-{theme.value}.svg").as_posix()
    spinbox_down_path = resource_path(f"spinbox-down-{theme.value}.svg").as_posix()
    app.setStyleSheet(
        _stylesheet(
            colors_for(theme),
            checkbox_check_path=checkbox_check_path,
            spinbox_up_path=spinbox_up_path,
            spinbox_down_path=spinbox_down_path,
        )
    )
    if _menu_icon_theme is None:
        _menu_icon_theme = _MenuIconTheme(app)
        app.installEventFilter(_menu_icon_theme)
