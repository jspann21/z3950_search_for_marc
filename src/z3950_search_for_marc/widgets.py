"""Focused PySide6 widgets used by the main desktop window."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .domain.models import QueryType, ServerResult, ServerStatus
from .ui.results_model import ResultsTableModel


class SearchPanel(QWidget):
    search_requested = Signal()
    cancel_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(245)
        self.setAccessibleName("Search and filters")
        heading = QLabel("Search", self)
        heading.setStyleSheet("font-size: 20px; font-weight: 700;")
        help_text = QLabel("Find MARC records across selected Z39.50 servers.", self)
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #526176;")
        self.tabs = QTabWidget(self)
        self.tabs.setAccessibleName("Search type")

        self.isbn_input = QLineEdit(self)
        self.isbn_input.setPlaceholderText("9780306406157")
        self.isbn_input.setAccessibleName("ISBN")
        isbn_page = QWidget(self)
        isbn_layout = QFormLayout(isbn_page)
        isbn_layout.addRow("ISBN", self.isbn_input)

        self.title_input = QLineEdit(self)
        self.title_input.setAccessibleName("Title")
        self.author_input = QLineEdit(self)
        self.author_input.setAccessibleName("Author")
        title_page = QWidget(self)
        title_layout = QFormLayout(title_page)
        title_layout.addRow("Title", self.title_input)
        title_layout.addRow("Author", self.author_input)
        self.tabs.addTab(isbn_page, "ISBN")
        self.tabs.addTab(title_page, "Title + author")

        filters = QGroupBox("Locations", self)
        filter_layout = QVBoxLayout(filters)
        self.usa_checkbox = QCheckBox("United States", filters)
        self.worldwide_checkbox = QCheckBox("Worldwide", filters)
        self.usa_checkbox.setChecked(True)
        self.worldwide_checkbox.setChecked(True)
        filter_layout.addWidget(self.usa_checkbox)
        filter_layout.addWidget(self.worldwide_checkbox)

        self.search_button = QPushButton("Search servers", self)
        self.search_button.setProperty("primary", True)
        self.search_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel search", self)
        self.cancel_button.setProperty("danger", True)
        self.cancel_button.setEnabled(False)
        self.settings_button = QPushButton("Settings…", self)
        self.search_button.clicked.connect(self.search_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.settings_button.clicked.connect(self.settings_requested)
        self.isbn_input.returnPressed.connect(self.search_requested)
        self.author_input.returnPressed.connect(self.search_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(help_text)
        layout.addWidget(self.tabs)
        layout.addWidget(filters)
        layout.addStretch(1)
        layout.addWidget(self.search_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.settings_button)

    @property
    def query_type(self) -> QueryType:
        return QueryType.ISBN if self.tabs.currentIndex() == 0 else QueryType.TITLE_AUTHOR

    @property
    def selected_locations(self) -> frozenset[str]:
        selected: set[str] = set()
        if self.usa_checkbox.isChecked():
            selected.add("USA")
        if self.worldwide_checkbox.isChecked():
            selected.add("Worldwide")
        return frozenset(selected)

    def set_searching(self, searching: bool) -> None:
        self.search_button.setEnabled(not searching)
        self.cancel_button.setEnabled(searching)
        self.tabs.setEnabled(not searching)


class ResultsPanel(QWidget):
    result_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(390)
        heading = QLabel("Server results", self)
        heading.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.summary_label = QLabel("Start a search to query the catalog.", self)
        self.summary_label.setStyleSheet("color: #526176;")
        self.summary_label.setWordWrap(True)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.model = ResultsTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().selectionChanged.connect(self._emit_selection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(heading)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table, 1)

    def reset(self, total: int) -> None:
        self.model.clear()
        self.progress.setValue(0)
        self.summary_label.setText(f"Preparing {total} servers…")

    def update_result(self, result: ServerResult) -> None:
        self.model.update_result(result)

    def set_progress(self, completed: int, total: int, percentage: int) -> None:
        self.progress.setValue(percentage)
        self.summary_label.setText(
            f"{completed} of {total} servers complete · {self.model.available_count} with records"
        )

    def finish(self, canceled: bool = False) -> None:
        available = self.model.available_count
        if canceled:
            text = f"Search canceled · {available} servers returned records"
        elif available:
            text = f"Search complete · {available} servers returned records"
        else:
            text = "Search complete · no matching records found"
        self.summary_label.setText(text)

    def _emit_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        source = self.proxy.mapToSource(rows[0])
        result = self.model.result_at(source.row())
        if result and result.status == ServerStatus.SUCCESS:
            self.result_selected.emit(result)


class RecordPanel(QWidget):
    previous_requested = Signal()
    next_requested = Signal()
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(360)
        self.server_label = QLabel("Record detail", self)
        self.server_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.position_label = QLabel("Select a successful server to view its first record.", self)
        self.position_label.setStyleSheet("color: #526176;")
        self.position_label.setWordWrap(True)
        self.export_mode_label = QLabel("", self)
        self.export_mode_label.setStyleSheet("color: #9a3412;")
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setAccessibleName("MARC record details")
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.previous_button = QPushButton("← Previous", self)
        self.next_button = QPushButton("Next →", self)
        self.export_button = QPushButton("Export .mrc…", self)
        self.export_button.setProperty("primary", True)
        for button in (self.previous_button, self.next_button, self.export_button):
            button.setEnabled(False)
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button.clicked.connect(self.next_requested)
        self.export_button.clicked.connect(self.export_requested)
        actions = QHBoxLayout()
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        actions.addStretch(1)
        actions.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.server_label)
        layout.addWidget(self.position_label)
        layout.addWidget(self.export_mode_label)
        layout.addWidget(self.details, 1)
        layout.addLayout(actions)

    def show_record(
        self, server: str, position: int, total: int, text: str, *, trimmed_export: bool
    ) -> None:
        self.server_label.setText(server)
        self.position_label.setText(f"Record {position:,} of {total:,}")
        self.export_mode_label.setText(
            "Export mode: trimmed fields will be removed"
            if trimmed_export
            else "Export mode: exact original server bytes"
        )
        self.details.setPlainText(text)
        self.previous_button.setEnabled(position > 1)
        self.next_button.setEnabled(position < total)
        self.export_button.setEnabled(True)

    def show_loading(self, server: str, position: int, total: int) -> None:
        self.server_label.setText(server)
        self.position_label.setText(f"Loading record {position:,} of {total:,}…")
        for button in (self.previous_button, self.next_button, self.export_button):
            button.setEnabled(False)

    def clear(self) -> None:
        self.server_label.setText("Record detail")
        self.position_label.setText("Select a successful server to view its first record.")
        self.export_mode_label.clear()
        self.details.clear()
        for button in (self.previous_button, self.next_button, self.export_button):
            button.setEnabled(False)


class ActivityPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toggle = QPushButton("Activity ▾", self)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.log = QPlainTextEdit(self)
        self.log.setAccessibleName("Application activity")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(150)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.toggle.toggled.connect(self._set_expanded)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.log)

    def append(self, message: str) -> None:
        self.log.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def _set_expanded(self, expanded: bool) -> None:
        self.log.setVisible(expanded)
        self.toggle.setText("Activity ▾" if expanded else "Activity ▸")
