"""Main window and application composition for the Z39.50 desktop client."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import cast
from uuid import UUID

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .backend import SearchBackend, YAZBackend, resolve_yaz_executable
from .config import load_servers, resolve_server_catalog_path
from .dialogs import SettingsDialog
from .marc import extract_marc_record, format_record_for_display, get_record_info, sanitize_filename
from .models import (
    BackendFailure,
    BackendResponse,
    FailureKind,
    QueryType,
    RecordReference,
    SearchProgress,
    SearchRequest,
    SearchSession,
    SearchState,
    ServerConfig,
    ServerSearchResult,
    ServerStatus,
)
from .resources import resource_path
from .search import SearchCoordinator
from .settings import SettingsStore
from .theme import apply_theme
from .widgets import ActivityPanel, RecordPanel, ResultsPanel, SearchPanel

__all__ = ["SettingsDialog", "Z3950SearchApp", "build_application", "run"]


class Z3950SearchApp(QMainWindow):
    """Three-pane search workspace and application-level event orchestration."""

    def __init__(
        self,
        qsettings: QSettings | None = None,
        backend: SearchBackend | None = None,
    ) -> None:
        super().__init__()
        self.qsettings = qsettings or QSettings()
        self.settings_store = SettingsStore(self.qsettings)
        self.app_settings = self.settings_store.load()
        self.servers: list[ServerConfig] = []
        self.search_state = SearchState()
        self._backend_injected = backend is not None
        self.backend: SearchBackend = backend or YAZBackend(self.app_settings.yaz_executable)
        self.coordinator = SearchCoordinator(self.backend, self)
        self._search_running = False
        self._successful_servers = 0
        self._failed_servers = 0

        self._init_ui()
        self._connect_coordinator()
        self._load_servers(show_dialog=False)
        self._report_yaz_status()

    def _init_ui(self) -> None:
        self.setWindowTitle("Z39.50 MARC Search")
        self.setMinimumSize(980, 650)
        self.resize(1360, 820)
        icon_path = resource_path("app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.search_panel = SearchPanel(self)
        self.results_panel = ResultsPanel(self)
        self.record_panel = RecordPanel(self)
        self.activity_panel = ActivityPanel(self)

        workspace = QSplitter(self)
        workspace.setChildrenCollapsible(False)
        workspace.addWidget(self.search_panel)
        workspace.addWidget(self.results_panel)
        workspace.addWidget(self.record_panel)
        workspace.setSizes([270, 480, 610])
        workspace.setStretchFactor(0, 0)
        workspace.setStretchFactor(1, 1)
        workspace.setStretchFactor(2, 2)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(workspace, 1)
        layout.addWidget(self.activity_panel)
        self.setCentralWidget(central)
        self._status_bar = cast(QStatusBar, self.statusBar())
        self._status_bar.showMessage("Ready")

        self.search_panel.search_requested.connect(self._start_search_from_panel)
        self.search_panel.cancel_requested.connect(self._cancel_search)
        self.search_panel.settings_requested.connect(self._open_settings_dialog)
        self.results_panel.result_selected.connect(self._select_result)
        self.record_panel.previous_requested.connect(self._show_previous_record)
        self.record_panel.next_requested.connect(self._show_next_record)
        self.record_panel.export_requested.connect(self._download_marc_record)

        settings_action = QAction("Settings", self)
        settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        settings_action.triggered.connect(self._open_settings_dialog)
        self.addAction(settings_action)

        # Compatibility aliases for code using the previous public widget attributes.
        self.isbn_input = self.search_panel.isbn_input
        self.title_input = self.search_panel.title_input
        self.author_input = self.search_panel.author_input
        self.usa_checkbox = self.search_panel.usa_checkbox
        self.worldwide_checkbox = self.search_panel.worldwide_checkbox
        self.progress_bar = self.results_panel.progress
        self.results_window = self.results_panel.table
        self.record_details_window = self.record_panel.details
        self.log_window = self.activity_panel.log
        self.download_button = self.record_panel.export_button
        self.prev_record_button = self.record_panel.previous_button
        self.next_record_button = self.record_panel.next_button
        self.cancel_button = self.search_panel.cancel_button
        self.settings_button = self.search_panel.settings_button
        self.search_isbn_button = self.search_panel.search_button
        self.search_title_author_button = self.search_panel.search_button

    def _connect_coordinator(self) -> None:
        self.coordinator.server_changed.connect(self._handle_server_change)
        self.coordinator.progress_changed.connect(self._handle_progress)
        self.coordinator.search_finished.connect(self._handle_search_finished)
        self.coordinator.record_fetched.connect(self._handle_record_fetched)

    def log_message(self, message: str) -> None:
        self.activity_panel.append(message)

    def _report_yaz_status(self) -> None:
        if self._backend_injected:
            return
        resolved = resolve_yaz_executable(self.app_settings.yaz_executable)
        if resolved:
            self.log_message(f"YAZ client ready: {resolved}")
        else:
            self.log_message(
                "YAZ client was not found. Open Settings to select yaz-client before searching."
            )
            self._status_bar.showMessage("YAZ client setup required")

    def _load_servers(self, *, show_dialog: bool = True) -> bool:
        catalog_path = resolve_server_catalog_path(self.app_settings.server_catalog_path)
        try:
            self.servers = load_servers(catalog_path)
        except (OSError, ValueError) as exc:
            self.servers = []
            self.log_message(f"Could not load server catalog: {exc}")
            if show_dialog:
                QMessageBox.critical(self, "Server catalog error", str(exc))
            self._status_bar.showMessage("Server catalog could not be loaded")
            return False
        self.log_message(f"Loaded {len(self.servers)} servers from {catalog_path}.")
        return True

    @staticmethod
    def validate_isbn(isbn: str) -> bool:
        normalized = isbn.replace("-", "").replace(" ", "").upper()
        if not re.fullmatch(r"(97[89])?\d{9}[\dX]", normalized):
            return False
        if len(normalized) == 10:
            total = sum(
                (10 - index) * (10 if char == "X" else int(char))
                for index, char in enumerate(normalized)
            )
            return total % 11 == 0
        if len(normalized) == 13 and "X" not in normalized:
            return (
                sum(
                    (1 if index % 2 == 0 else 3) * int(char)
                    for index, char in enumerate(normalized)
                )
                % 10
                == 0
            )
        return False

    def _request_from_panel(self) -> SearchRequest | None:
        locations = self.search_panel.selected_locations
        if not locations:
            QMessageBox.warning(self, "Choose a location", "Select at least one location filter.")
            return None

        if self.search_panel.query_type == QueryType.ISBN:
            isbn = self.search_panel.isbn_input.text().strip()
            if not isbn:
                QMessageBox.warning(self, "ISBN required", "Enter an ISBN to search for.")
                return None
            if not self.validate_isbn(isbn):
                QMessageBox.warning(self, "Invalid ISBN", "Enter a valid ISBN-10 or ISBN-13.")
                return None
            query: str | tuple[str, str] = isbn
        else:
            title = self.search_panel.title_input.text().strip()
            author = self.search_panel.author_input.text().strip()
            if not title or not author:
                QMessageBox.warning(
                    self,
                    "Title and author required",
                    "Enter both a title and an author to search.",
                )
                return None
            query = (title, author)

        return SearchRequest(
            self.search_panel.query_type,
            query,
            locations,
            self.app_settings.server_timeout_seconds,
        )

    def _start_search_from_panel(self) -> None:
        request = self._request_from_panel()
        if request is None:
            return
        if (
            not self._backend_injected
            and resolve_yaz_executable(self.app_settings.yaz_executable) is None
        ):
            QMessageBox.critical(
                self,
                "YAZ client required",
                "yaz-client was not found. Install YAZ or select the executable in Settings.",
            )
            return
        if not self.servers and not self._load_servers():
            return

        filtered = [server for server in self.servers if server.location in request.locations]
        if not filtered:
            QMessageBox.warning(
                self, "No matching servers", "No catalog servers match the selected locations."
            )
            return

        session = SearchSession(request)
        self.search_state.reset(session)
        self._successful_servers = 0
        self._failed_servers = 0
        self._search_running = True
        self.results_panel.reset(len(filtered))
        self.record_panel.clear()
        self.search_panel.set_searching(True)
        self._status_bar.showMessage(f"Searching {len(filtered)} servers…")
        self.log_message(
            f"Starting {request.query_type.value} search across {len(filtered)} servers."
        )
        self.coordinator.start(session, filtered, self.app_settings.max_concurrent_queries)

    # Compatibility handlers retained for callers of the old window.
    def _start_isbn_search(self) -> None:
        self.search_panel.tabs.setCurrentIndex(0)
        self._start_search_from_panel()

    def _start_title_author_search(self) -> None:
        self.search_panel.tabs.setCurrentIndex(1)
        self._start_search_from_panel()

    def _start_search(self) -> None:
        self._start_search_from_panel()

    def _handle_server_change(self, result: ServerSearchResult) -> None:
        session = self.search_state.session
        if session is None or result.session_id != session.id:
            return
        self.results_panel.update_result(result)
        if result.status == ServerStatus.SUCCESS:
            self._successful_servers += 1
            self.log_message(
                f"{result.server.name} returned {result.number_of_hits:,} matching records."
            )
        elif result.status in {ServerStatus.FAILED, ServerStatus.TIMED_OUT}:
            self._failed_servers += 1
            self.log_message(result.message or f"{result.server.name}: {result.status.value}")

    def _handle_progress(self, progress: SearchProgress) -> None:
        session = self.search_state.session
        if session is None or progress.session_id != session.id:
            return
        self.results_panel.set_progress(progress.completed, progress.total, progress.percentage)

    def _handle_search_finished(self, session_id: UUID) -> None:
        session = self.search_state.session
        if session is None or session_id != session.id or not self._search_running:
            return
        self._search_running = False
        self.search_panel.set_searching(False)
        self.results_panel.finish()
        self._status_bar.showMessage(
            f"Search complete: {self._successful_servers} servers with records"
        )
        self.log_message(
            f"Search complete. {self._successful_servers} servers returned records; "
            f"{self._failed_servers} failed or timed out."
        )

    def _cancel_search(self) -> None:
        if self.search_state.session is None:
            return
        self.coordinator.cancel()
        self._search_running = False
        self.search_state.fetch_in_progress = False
        self.search_panel.set_searching(False)
        self.results_panel.finish(canceled=True)
        self._status_bar.showMessage("Search canceled")
        self.log_message("Search canceled. Active YAZ processes were stopped.")

    def _select_result(self, result: ServerSearchResult) -> None:
        session = self.search_state.session
        if session is None or result.session_id != session.id:
            return
        record = extract_marc_record(
            result.raw_data,
            trim_records=self.app_settings.trim_records,
            log_callback=self.log_message,
        )
        self.search_state.select(result, record)
        if record is None:
            self.record_panel.clear()
            QMessageBox.warning(
                self,
                "Record could not be read",
                "The server returned a result, but its MARC record could not be parsed.",
            )
            return
        self._display_current_record()

    def _display_current_record(self) -> None:
        result = self.search_state.selected_result
        record = self.search_state.current_record
        if result is None or record is None:
            self.record_panel.clear()
            return
        self.record_panel.show_record(
            result.server.name,
            self.search_state.current_position,
            result.number_of_hits,
            format_record_for_display(record),
        )
        self._status_bar.showMessage(
            f"{result.server.name}: record {self.search_state.current_position} "
            f"of {result.number_of_hits}"
        )

    def _show_previous_record(self) -> None:
        if self.search_state.fetch_in_progress or self.search_state.current_position <= 1:
            return
        self.search_state.current_position -= 1
        self._display_current_record()

    def _show_prev_record(self) -> None:
        self._show_previous_record()

    def _show_next_record(self) -> None:
        result = self.search_state.selected_result
        session = self.search_state.session
        if (
            result is None
            or session is None
            or self.search_state.fetch_in_progress
            or self.search_state.current_position >= result.number_of_hits
        ):
            return
        position = self.search_state.current_position + 1
        key = (result.server.key, position)
        cached = self.search_state.records.get(key)
        if cached is not None:
            self.search_state.current_position = position
            self._display_current_record()
            return

        self.search_state.fetch_in_progress = True
        self.record_panel.show_loading(result.server.name, position, result.number_of_hits)
        self.search_panel.cancel_button.setEnabled(True)
        self.log_message(f"Fetching record {position} from {result.server.name}.")
        self.coordinator.fetch_record(RecordReference(session.id, result.server, position))

    def _handle_record_fetched(
        self,
        reference: RecordReference,
        backend_result: BackendResponse | BackendFailure,
    ) -> None:
        session = self.search_state.session
        result = self.search_state.selected_result
        if session is None or result is None or reference.session_id != session.id:
            return
        self.search_state.fetch_in_progress = False
        self.search_panel.cancel_button.setEnabled(self._search_running)
        if isinstance(backend_result, BackendFailure):
            if backend_result.kind != FailureKind.CANCELED:
                self.log_message(f"Record fetch failed: {backend_result.message}")
                QMessageBox.warning(self, "Record fetch failed", backend_result.message)
            self._display_current_record()
            return
        record = extract_marc_record(
            backend_result.cleaned_data,
            trim_records=self.app_settings.trim_records,
            log_callback=self.log_message,
        )
        if record is None:
            self.log_message(f"Record {reference.position} could not be parsed.")
            QMessageBox.warning(
                self, "Record could not be read", "The returned MARC record could not be parsed."
            )
            self._display_current_record()
            return
        self.search_state.records[reference.cache_key] = record
        self.search_state.current_position = reference.position
        self._display_current_record()

    def _download_marc_record(self) -> None:
        record = self.search_state.current_record
        if record is None:
            QMessageBox.warning(self, "No record", "Select a MARC record before exporting.")
            return
        author, title = get_record_info(record)
        suggested_name = sanitize_filename(f"{author}_{title}") + ".mrc"
        directory = Path(self.app_settings.default_save_directory).expanduser()
        if not directory.is_dir():
            directory = Path.home()
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Export MARC record",
            str(directory / suggested_name),
            "MARC records (*.mrc)",
        )
        if not file_name:
            return
        try:
            Path(file_name).write_bytes(record.as_marc())
        except (OSError, ValueError) as exc:
            self.log_message(f"Could not export MARC record: {exc}")
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.log_message(f"Exported MARC record to {file_name}.")
        self._status_bar.showMessage(f"Record exported to {file_name}", 8000)

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.app_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_settings is None:
            return
        self.coordinator.shutdown()
        self.app_settings = self.settings_store.save(dialog.saved_settings)
        if not self._backend_injected:
            self.backend = YAZBackend(self.app_settings.yaz_executable)
        self.coordinator = SearchCoordinator(self.backend, self)
        self._connect_coordinator()
        self._load_servers()
        self._report_yaz_status()
        self.log_message("Settings saved and applied.")

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802
        self.coordinator.shutdown()
        self.search_state.reset()
        if event is not None:
            event.accept()


def build_application() -> QApplication:
    """Create the Qt application object with stable settings metadata."""
    app = cast(QApplication | None, QApplication.instance())
    if app is None:
        app = QApplication(sys.argv)
    app.setOrganizationName("z3950_search_for_marc")
    app.setApplicationName("z3950_search_for_marc")
    app.setApplicationDisplayName("Z39.50 MARC Search")
    apply_theme(app)
    return app


def run(*, smoke_test: bool = False) -> int:
    """Launch the main window, optionally exiting automatically for package smoke tests."""
    app = build_application()
    window = Z3950SearchApp()
    window.show()
    if smoke_test:
        QTimer.singleShot(350, app.quit)
    return app.exec()
