"""Focused widgets used by the main desktop window."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .models import QueryType, ServerSearchResult, ServerStatus


class SearchPanel(QWidget):
    """Search inputs, filters, and primary actions."""

    search_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(245)
        self.setAccessibleName("Search and filters")

        heading = QLabel("Search", self)
        heading.setStyleSheet("font-size: 20px; font-weight: 700;")
        help_text = QLabel("Find MARC records across the selected Z39.50 servers.", self)
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
        self.title_input.setPlaceholderText("Title")
        self.title_input.setAccessibleName("Title")
        self.author_input = QLineEdit(self)
        self.author_input.setPlaceholderText("Author")
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
        self.usa_checkbox.setChecked(True)
        self.worldwide_checkbox = QCheckBox("Worldwide", filters)
        self.worldwide_checkbox.setChecked(True)
        filter_layout.addWidget(self.usa_checkbox)
        filter_layout.addWidget(self.worldwide_checkbox)

        self.search_button = QPushButton("Search servers", self)
        self.search_button.setProperty("primary", True)
        self.search_button.setDefault(True)
        self.search_button.setAccessibleName("Start search")
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
        locations: set[str] = set()
        if self.usa_checkbox.isChecked():
            locations.add("USA")
        if self.worldwide_checkbox.isChecked():
            locations.add("Worldwide")
        return frozenset(locations)

    def set_searching(self, searching: bool) -> None:
        self.search_button.setEnabled(not searching)
        self.cancel_button.setEnabled(searching)
        self.tabs.setEnabled(not searching)


class ResultsPanel(QWidget):
    """Sortable, incrementally updated server result table."""

    result_selected = pyqtSignal(object)
    _COLUMNS = ("Server", "Endpoint", "Hits", "Status")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(340)
        heading = QLabel("Server results", self)
        heading.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.summary_label = QLabel("Start a search to query the catalog.", self)
        self.summary_label.setStyleSheet("color: #526176;")
        self.summary_label.setWordWrap(True)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)

        self.table = QTableWidget(0, len(self._COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        vertical_header = self.table.verticalHeader()
        assert vertical_header is not None
        vertical_header.setVisible(False)
        header = self.table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._emit_selection)
        self._rows: dict[str, int] = {}
        self._results: dict[str, ServerSearchResult] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(heading)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table, 1)

    def reset(self, total: int) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._rows.clear()
        self._results.clear()
        self.progress.setValue(0)
        self.summary_label.setText(f"Preparing {total} servers…")

    def update_result(self, result: ServerSearchResult) -> None:
        self.table.setSortingEnabled(False)
        row = self._rows.get(result.server.key)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._rows[result.server.key] = row
        self._results[result.server.key] = result
        values = (
            result.server.name,
            result.server.endpoint,
            str(result.number_of_hits) if result.status == ServerStatus.SUCCESS else "—",
            result.status.value,
        )
        for column, value in enumerate(values):
            item = self.table.item(row, column) or QTableWidgetItem()
            item.setText(value)
            item.setData(Qt.ItemDataRole.UserRole, result.server.key)
            if column == 2 and result.status == ServerStatus.SUCCESS:
                item.setData(Qt.ItemDataRole.DisplayRole, result.number_of_hits)
            self.table.setItem(row, column, item)

    def set_progress(self, completed: int, total: int, percentage: int) -> None:
        self.progress.setValue(percentage)
        available = sum(result.status == ServerStatus.SUCCESS for result in self._results.values())
        self.summary_label.setText(
            f"{completed} of {total} servers complete · {available} with records"
        )

    def finish(self, canceled: bool = False) -> None:
        available = sum(result.status == ServerStatus.SUCCESS for result in self._results.values())
        if canceled:
            self.summary_label.setText(f"Search canceled · {available} servers returned records")
        elif available:
            self.summary_label.setText(f"Search complete · {available} servers returned records")
        else:
            self.summary_label.setText("Search complete · no matching records found")
        self.table.setSortingEnabled(True)

    def _emit_selection(self) -> None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        rows = selection_model.selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return
        key = cast(str, item.data(Qt.ItemDataRole.UserRole))
        result = self._results.get(key)
        if result and result.status == ServerStatus.SUCCESS:
            self.result_selected.emit(result)


class RecordPanel(QWidget):
    """Selected MARC record display and navigation."""

    previous_requested = pyqtSignal()
    next_requested = pyqtSignal()
    export_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(360)
        self.server_label = QLabel("Record detail", self)
        self.server_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.position_label = QLabel("Select a server result to view its first record.", self)
        self.position_label.setStyleSheet("color: #526176;")
        self.position_label.setWordWrap(True)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("No record selected")
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.details.setFont(fixed_font)

        self.previous_button = QPushButton("← Previous", self)
        self.next_button = QPushButton("Next →", self)
        self.export_button = QPushButton("Export .mrc…", self)
        self.export_button.setProperty("primary", True)
        for button in (self.previous_button, self.next_button, self.export_button):
            button.setEnabled(False)
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button.clicked.connect(self.next_requested)
        self.export_button.clicked.connect(self.export_requested)

        buttons = QHBoxLayout()
        buttons.addWidget(self.previous_button)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.server_label)
        layout.addWidget(self.position_label)
        layout.addWidget(self.details, 1)
        layout.addLayout(buttons)

    def show_record(self, server: str, position: int, total: int, text: str) -> None:
        self.server_label.setText(server)
        self.position_label.setText(f"Record {position:,} of {total:,}")
        self.details.setPlainText(text)
        self.previous_button.setEnabled(position > 1)
        self.next_button.setEnabled(position < total)
        self.export_button.setEnabled(True)

    def show_loading(self, server: str, position: int, total: int) -> None:
        self.server_label.setText(server)
        self.position_label.setText(f"Loading record {position:,} of {total:,}…")
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def clear(self) -> None:
        self.server_label.setText("Record detail")
        self.position_label.setText("Select a server result to view its first record.")
        self.details.clear()
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.export_button.setEnabled(False)


class ActivityPanel(QWidget):
    """Collapsible timestamped diagnostic activity view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toggle = QPushButton("Activity ▾", self)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setAccessibleName("Show or hide activity log")
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(150)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.toggle.toggled.connect(self._set_expanded)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(3)
        layout.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.log)

    def append(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{timestamp}] {message}")

    def _set_expanded(self, expanded: bool) -> None:
        self.log.setVisible(expanded)
        self.toggle.setText("Activity ▾" if expanded else "Activity ▸")
