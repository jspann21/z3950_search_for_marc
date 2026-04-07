"""PyQt6 desktop application for Z39.50 MARC searching."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pymarc import Record
from PyQt6.QtCore import QSettings, Qt, QThread, pyqtBoundSignal
from PyQt6.QtGui import QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import load_servers, resolve_server_catalog_path
from .marc import (
    extract_marc_record,
    format_record_for_display,
    get_record_info,
    is_yaz_client_installed,
    sanitize_filename,
)
from .models import AppSettings, QueryType, SearchResult, SearchState, ServerConfig
from .resources import resource_path
from .settings import SettingsStore
from .workers import NextRecordWorker, NextRecordWorkerConfig, Worker, WorkerConfig
from .yaz import YAZClient


@dataclass(slots=True)
class WorkerInfo:
    worker: Any | None = None
    thread: QThread | None = None


class WorkerManager:
    """Create and clean up worker threads."""

    def __init__(self) -> None:
        self.worker_info = WorkerInfo()

    @staticmethod
    def create_worker_thread(
        worker_factory: Callable[[], Any],
        worker_signals: dict[str, Callable[..., Any]],
    ) -> tuple[Any, QThread]:
        worker = worker_factory()
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        for signal_name, handler in worker_signals.items():
            signal = cast(pyqtBoundSignal, getattr(worker, signal_name))
            signal.connect(handler)
        thread.started.connect(worker.run)
        thread.start()
        return worker, thread

    def cleanup_worker_thread(self) -> None:
        worker = self.worker_info.worker
        thread = self.worker_info.thread
        if worker is None or thread is None:
            return

        try:
            if thread.isRunning():
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
                thread.quit()
                thread.wait(5000)
        finally:
            self.worker_info = WorkerInfo()


class SettingsDialog(QDialog):
    """Settings UI backed by AppSettings."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._saved_settings: AppSettings | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.yaz_path_input = QLineEdit(settings.yaz_executable, self)
        self.server_catalog_input = QLineEdit(settings.server_catalog_path, self)
        self.max_threads_input = QSpinBox(self)
        self.max_threads_input.setRange(1, 32)
        self.max_threads_input.setValue(settings.max_concurrent_queries)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 60)
        self.timeout_input.setValue(settings.server_timeout_seconds)
        self.default_save_directory_input = QLineEdit(settings.default_save_directory, self)
        self.trim_records_checkbox = QCheckBox("Trim tags 000-009 and 900+", self)
        self.trim_records_checkbox.setChecked(settings.trim_records)

        yaz_layout = QHBoxLayout()
        yaz_layout.addWidget(self.yaz_path_input)
        browse_yaz = QPushButton("Browse", self)
        browse_yaz.clicked.connect(self._browse_yaz_path)
        yaz_layout.addWidget(browse_yaz)

        catalog_layout = QHBoxLayout()
        catalog_layout.addWidget(self.server_catalog_input)
        browse_catalog = QPushButton("Browse", self)
        browse_catalog.clicked.connect(self._browse_catalog_path)
        catalog_layout.addWidget(browse_catalog)

        save_dir_layout = QHBoxLayout()
        save_dir_layout.addWidget(self.default_save_directory_input)
        browse_save_dir = QPushButton("Browse", self)
        browse_save_dir.clicked.connect(self._browse_save_directory)
        save_dir_layout.addWidget(browse_save_dir)

        form.addRow("YAZ executable", yaz_layout)
        form.addRow("Server catalog", catalog_layout)
        form.addRow("Max concurrent queries", self.max_threads_input)
        form.addRow("Timeout (seconds)", self.timeout_input)
        form.addRow("Default save directory", save_dir_layout)
        form.addRow("", self.trim_records_checkbox)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_button = QPushButton("Save", self)
        cancel_button = QPushButton("Cancel", self)
        save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    @property
    def saved_settings(self) -> AppSettings | None:
        return self._saved_settings

    def _browse_yaz_path(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select yaz-client executable")
        if file_path:
            self.yaz_path_input.setText(file_path)

    def _browse_catalog_path(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select server catalog",
            self.server_catalog_input.text() or str(Path.home()),
            "JSON Files (*.json)",
        )
        if file_path:
            self.server_catalog_input.setText(file_path)

    def _browse_save_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select default save directory",
            self.default_save_directory_input.text() or str(Path.home()),
        )
        if directory:
            self.default_save_directory_input.setText(directory)

    def _save(self) -> None:
        self._saved_settings = AppSettings(
            yaz_executable=self.yaz_path_input.text(),
            server_catalog_path=self.server_catalog_input.text(),
            max_concurrent_queries=self.max_threads_input.value(),
            server_timeout_seconds=self.timeout_input.value(),
            default_save_directory=self.default_save_directory_input.text(),
            trim_records=self.trim_records_checkbox.isChecked(),
        ).normalized()
        self.accept()


class Z3950SearchApp(QWidget):
    """Main application window."""

    def __init__(self, qsettings: QSettings | None = None) -> None:
        super().__init__()
        self.qsettings = qsettings or QSettings()
        self.settings_store = SettingsStore(self.qsettings)
        self.app_settings = self.settings_store.load()
        self.servers: list[ServerConfig] = []
        self.search_state = SearchState()
        self.worker_manager = WorkerManager()
        self.next_record_worker_manager = WorkerManager()
        self.fetch_in_progress = False

        self._init_ui()
        self._apply_window_icon()
        self._load_servers()
        self._warn_if_yaz_missing()

    def _init_ui(self) -> None:
        self.setWindowTitle("Z39.50 MARC Record Search")
        self.resize(1000, 720)

        self.isbn_input = QLineEdit(self)
        self.isbn_input.setPlaceholderText("Enter ISBN")
        self.search_isbn_button = QPushButton("Search ISBN", self)
        self.search_isbn_button.clicked.connect(self._start_isbn_search)

        self.title_input = QLineEdit(self)
        self.title_input.setPlaceholderText("Enter Title")
        self.author_input = QLineEdit(self)
        self.author_input.setPlaceholderText("Enter Author")
        self.search_title_author_button = QPushButton("Search Title && Author", self)
        self.search_title_author_button.clicked.connect(self._start_title_author_search)

        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_search)

        self.settings_button = QPushButton("Settings", self)
        self.settings_button.clicked.connect(self._open_settings_dialog)

        self.usa_checkbox = QCheckBox("USA", self)
        self.usa_checkbox.setChecked(True)
        self.worldwide_checkbox = QCheckBox("Worldwide", self)
        self.worldwide_checkbox.setChecked(True)

        self.progress_bar = QProgressBar(self)
        self.results_window = QListWidget(self)
        self.results_window.itemClicked.connect(self._on_result_clicked)
        self.record_details_window = QTextEdit(self)
        self.record_details_window.setReadOnly(True)
        self.download_button = QPushButton("Download Record", self)
        self.download_button.clicked.connect(self._download_marc_record)
        self.download_button.setEnabled(False)

        self.prev_record_button = QPushButton("Previous Record", self)
        self.prev_record_button.clicked.connect(self._show_prev_record)
        self.prev_record_button.setEnabled(False)
        self.next_record_button = QPushButton("Next Record", self)
        self.next_record_button.clicked.connect(self._show_next_record)
        self.next_record_button.setEnabled(False)

        self.log_window = QTextEdit(self)
        self.log_window.setReadOnly(True)
        self.log_window.setMaximumHeight(160)

        top_layout = QHBoxLayout()

        isbn_group = QGroupBox("Search by ISBN")
        isbn_layout = QVBoxLayout()
        isbn_layout.addWidget(self.isbn_input)
        isbn_layout.addWidget(self.search_isbn_button)
        isbn_group.setLayout(isbn_layout)

        title_group = QGroupBox("Search by Title && Author")
        title_layout = QVBoxLayout()
        title_layout.addWidget(self.title_input)
        title_layout.addWidget(self.author_input)
        title_layout.addWidget(self.search_title_author_button)
        title_group.setLayout(title_layout)

        location_group = QGroupBox("Filter by Location")
        location_layout = QVBoxLayout()
        location_layout.addWidget(self.usa_checkbox)
        location_layout.addWidget(self.worldwide_checkbox)
        location_layout.addWidget(self.settings_button)
        location_layout.addWidget(self.cancel_button)
        location_group.setLayout(location_layout)

        top_layout.addWidget(isbn_group)
        top_layout.addWidget(title_group)
        top_layout.addWidget(location_group)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(self.prev_record_button)
        nav_layout.addWidget(self.next_record_button)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(QLabel("Search Results:", self))
        main_layout.addWidget(self.results_window)
        main_layout.addWidget(QLabel("Record Details:", self))
        main_layout.addWidget(self.record_details_window)
        main_layout.addLayout(nav_layout)
        main_layout.addWidget(self.download_button)
        main_layout.addWidget(QLabel("Log:", self))
        main_layout.addWidget(self.log_window)

    def _apply_window_icon(self) -> None:
        icon_path = resource_path("app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def log_message(self, message: str) -> None:
        self.log_window.append(message)
        self.log_window.moveCursor(QTextCursor.MoveOperation.End)
        self.log_window.ensureCursorVisible()

    def _warn_if_yaz_missing(self) -> None:
        if not is_yaz_client_installed(self.app_settings.yaz_executable):
            self.log_message(
                "Configured yaz-client executable was not found. "
                "Update it in Settings before searching."
            )

    def _load_servers(self) -> bool:
        catalog_path = resolve_server_catalog_path(self.app_settings.server_catalog_path)
        try:
            self.servers = load_servers(catalog_path)
            self.log_message(f"Loaded {len(self.servers)} servers from '{catalog_path}'.")
            return True
        except FileNotFoundError:
            self.servers = []
            self.log_message(f"Server configuration file not found: {catalog_path}")
            QMessageBox.critical(
                self,
                "Configuration Error",
                f"Server catalog not found:\n{catalog_path}",
            )
            return False
        except (OSError, ValueError) as exc:
            self.servers = []
            self.log_message(f"Failed to load server catalog: {exc}")
            QMessageBox.critical(self, "Configuration Error", str(exc))
            return False

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.app_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_settings is None:
            return

        self.app_settings = self.settings_store.save(dialog.saved_settings)
        self.log_message("Settings saved.")
        self._load_servers()
        self._warn_if_yaz_missing()

    @staticmethod
    def validate_isbn(isbn: str) -> bool:
        isbn = isbn.replace("-", "").replace(" ", "").upper()
        if not re.fullmatch(r"(97[89])?\d{9}[\dX]", isbn):
            return False
        if len(isbn) == 10:
            total = sum(
                (10 - i) * (10 if char == "X" else int(char))
                for i, char in enumerate(isbn)
            )
            return total % 11 == 0
        if len(isbn) == 13 and "X" not in isbn:
            total = sum((1 if i % 2 == 0 else 3) * int(char) for i, char in enumerate(isbn))
            return total % 10 == 0
        return False

    def _selected_locations(self) -> list[str]:
        locations: list[str] = []
        if self.usa_checkbox.isChecked():
            locations.append("USA")
        if self.worldwide_checkbox.isChecked():
            locations.append("Worldwide")
        return locations

    def _ensure_search_prereqs(self) -> list[ServerConfig] | None:
        if not is_yaz_client_installed(self.app_settings.yaz_executable):
            QMessageBox.critical(
                self,
                "Dependency Missing",
                "Configured yaz-client executable was not found. Update the path in Settings.",
            )
            return None
        if not self.servers and not self._load_servers():
            return None
        selected_locations = self._selected_locations()
        if not selected_locations:
            QMessageBox.warning(self, "Selection Error", "Select at least one location filter.")
            return None
        filtered = [server for server in self.servers if server.location in selected_locations]
        if not filtered:
            QMessageBox.warning(
                self,
                "Filter Error",
                "No servers match the selected location filters.",
            )
            return None
        return filtered

    def _start_isbn_search(self) -> None:
        query = self.isbn_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Input Error", "Please enter an ISBN.")
            return
        if not self.validate_isbn(query):
            QMessageBox.warning(
                self,
                "Validation Error",
                "Invalid ISBN. Please enter a valid ISBN.",
            )
            return
        self.search_state.current_query_type = QueryType.ISBN
        self.search_state.current_query = query
        self._start_search()

    def _start_title_author_search(self) -> None:
        title = self.title_input.text().strip()
        author = self.author_input.text().strip()
        if not title or not author:
            QMessageBox.warning(self, "Input Error", "Please enter both Title and Author.")
            return
        self.search_state.current_query_type = QueryType.TITLE_AUTHOR
        self.search_state.current_query = (title, author)
        self._start_search()

    def _start_search(self) -> None:
        filtered_servers = self._ensure_search_prereqs()
        if (
            filtered_servers is None
            or self.search_state.current_query_type is None
            or self.search_state.current_query is None
        ):
            return

        self.worker_manager.cleanup_worker_thread()
        self.next_record_worker_manager.cleanup_worker_thread()
        self.fetch_in_progress = False
        self.search_state.reset_results()
        self.results_window.clear()
        self.record_details_window.clear()
        self.download_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self._manage_navigation_buttons(False, False)

        self.log_message(
            f"Starting {self.search_state.current_query_type.value} search with query: "
            f"{self.search_state.current_query}"
        )
        query_type = self.search_state.current_query_type
        query = self.search_state.current_query
        assert query_type is not None
        assert query is not None

        def factory() -> Worker:
            return Worker(
                WorkerConfig(
                    servers=filtered_servers,
                    query_type=query_type,
                    query=query,
                    start=1,
                    timeout_seconds=self.app_settings.server_timeout_seconds,
                    max_threads=self.app_settings.max_concurrent_queries,
                ),
                self._make_yaz_client,
            )

        self.worker_manager.worker_info.worker, self.worker_manager.worker_info.thread = (
            self.worker_manager.create_worker_thread(
                factory,
                {
                    "progress": self.progress_bar.setValue,
                    "log_message": self.log_message,
                    "result_found": self._display_result,
                    "finished": self._on_worker_finished,
                    "error": self._handle_worker_error,
                },
            )
        )
        self._toggle_search_buttons(False)

    def _make_yaz_client(self) -> YAZClient:
        return YAZClient(self.app_settings.yaz_executable)

    def _toggle_search_buttons(self, enabled: bool) -> None:
        self.search_isbn_button.setEnabled(enabled)
        self.search_title_author_button.setEnabled(enabled)
        self.cancel_button.setEnabled(not enabled)

    def _manage_navigation_buttons(self, prev_enabled: bool, next_enabled: bool) -> None:
        self.prev_record_button.setEnabled(prev_enabled)
        self.next_record_button.setEnabled(next_enabled)

    def _cancel_search(self) -> None:
        self.worker_manager.cleanup_worker_thread()
        self.next_record_worker_manager.cleanup_worker_thread()
        self.progress_bar.setValue(0)
        self.fetch_in_progress = False
        self._toggle_search_buttons(True)
        self._update_navigation_buttons()
        self.log_message("Search cancelled.")

    def _on_worker_finished(self) -> None:
        canceled = bool(
            self.worker_manager.worker_info.worker
            and getattr(self.worker_manager.worker_info.worker, "cancel_requested", False)
        )
        self.worker_manager.cleanup_worker_thread()
        self._toggle_search_buttons(True)
        self.fetch_in_progress = False
        if canceled:
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setValue(100)
            self.log_message("Search completed.")
        self._update_navigation_buttons()

    def _handle_worker_error(self, message: str) -> None:
        self.log_message(f"Error: {message}")
        QMessageBox.warning(self, "Search Error", message)
        self._toggle_search_buttons(True)
        self.fetch_in_progress = False

    def _display_result(self, result: SearchResult) -> None:
        item = QListWidgetItem(f"{result.summary} - {result.number_of_hits} hits")
        item.setData(Qt.ItemDataRole.UserRole, result)
        self.results_window.addItem(item)
        self.log_message(f"Displaying result from {result.summary}")

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        result = cast(SearchResult, item.data(Qt.ItemDataRole.UserRole))
        record = extract_marc_record(
            result.raw_data,
            trim_records=self.app_settings.trim_records,
            log_callback=self.log_message,
        )
        self.search_state.current_server_info = result.server
        self.search_state.current_marc_records = [record] if record else []
        self.search_state.current_record_index = 0
        self.search_state.total_records = result.number_of_hits
        self._display_current_record()

    def _display_current_record(self) -> None:
        if self.search_state.current_marc_records and self.search_state.current_record_index < len(
            self.search_state.current_marc_records
        ):
            record = self.search_state.current_marc_records[self.search_state.current_record_index]
            self.record_details_window.setPlainText(format_record_for_display(record))
            self.download_button.setEnabled(True)
            self.log_message("Record displayed.")
        else:
            self.record_details_window.setPlainText("No record available.")
            self.download_button.setEnabled(False)
            self.log_message("No record available to display.")
        self._update_navigation_buttons()

    def _update_navigation_buttons(self) -> None:
        self._manage_navigation_buttons(
            self.search_state.current_record_index > 0,
            self.search_state.current_record_index < self.search_state.total_records - 1,
        )

    def _show_next_record(self) -> None:
        if self.fetch_in_progress:
            QMessageBox.information(
                self,
                "Info",
                "Next record is already being fetched. Please wait.",
            )
            return

        if self.search_state.current_record_index + 1 < len(self.search_state.current_marc_records):
            self.search_state.current_record_index += 1
            self._display_current_record()
            return

        if (
            self.search_state.current_server_info is None
            or self.search_state.current_query_type is None
            or self.search_state.current_query is None
        ):
            return

        if self.search_state.current_record_index + 1 >= self.search_state.total_records:
            QMessageBox.information(self, "Info", "No more records to display.")
            return

        self.fetch_in_progress = True
        self._manage_navigation_buttons(False, False)
        self.next_record_worker_manager.cleanup_worker_thread()

        start = self.search_state.current_record_index + 2
        server_info = self.search_state.current_server_info
        query_type = self.search_state.current_query_type
        query = self.search_state.current_query
        assert server_info is not None
        assert query_type is not None
        assert query is not None

        def factory() -> NextRecordWorker:
            return NextRecordWorker(
                NextRecordWorkerConfig(
                    server_info=server_info,
                    query_type=query_type,
                    query=query,
                    start=start,
                    timeout_seconds=self.app_settings.server_timeout_seconds,
                    trim_records=self.app_settings.trim_records,
                ),
                self._make_yaz_client,
            )

        (
            self.next_record_worker_manager.worker_info.worker,
            self.next_record_worker_manager.worker_info.thread,
        ) = self.next_record_worker_manager.create_worker_thread(
            factory,
            {
                "record_fetched": self._handle_next_record_fetched,
                "error": self._handle_next_record_error,
                "finished": self._on_next_record_worker_finished,
                "log_message": self.log_message,
            },
        )

    def _handle_next_record_fetched(self, record: Record) -> None:
        self.search_state.current_marc_records.append(record)
        self.search_state.current_record_index += 1
        self._display_current_record()

    def _handle_next_record_error(self, message: str) -> None:
        self.log_message(f"Error fetching next record: {message}")
        QMessageBox.warning(self, "Record Fetch Error", message)
        self.fetch_in_progress = False
        self._update_navigation_buttons()

    def _on_next_record_worker_finished(self) -> None:
        self.next_record_worker_manager.cleanup_worker_thread()
        self.fetch_in_progress = False
        self._update_navigation_buttons()

    def _show_prev_record(self) -> None:
        if self.search_state.current_record_index == 0:
            QMessageBox.information(self, "Info", "Already at the first record.")
            return
        self.search_state.current_record_index -= 1
        self._display_current_record()

    def _download_marc_record(self) -> None:
        if not self.search_state.current_marc_records:
            QMessageBox.warning(self, "Error", "No MARC record to save.")
            return

        record = self.search_state.current_marc_records[self.search_state.current_record_index]
        if not isinstance(record, Record):
            QMessageBox.warning(self, "Error", "Invalid MARC record format.")
            return

        author, title = get_record_info(record)
        suggested_name = sanitize_filename(f"{author}_{title}") + ".mrc"
        default_directory = Path(self.app_settings.default_save_directory).expanduser()
        if not default_directory.exists():
            default_directory = Path.home()
        default_path = default_directory / suggested_name

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save MARC Record",
            str(default_path),
            "MARC Files (*.mrc)",
        )
        if not file_name:
            return
        try:
            Path(file_name).write_bytes(record.as_marc())
        except OSError as exc:
            QMessageBox.warning(self, "Save Error", f"Failed to save file: {exc}")
            self.log_message(f"Failed to save MARC record to {file_name}: {exc}")
            return

        self.log_message(f"MARC record saved to {file_name}.")
        QMessageBox.information(self, "Success", "MARC record saved successfully.")

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.worker_manager.cleanup_worker_thread()
        self.next_record_worker_manager.cleanup_worker_thread()
        self.fetch_in_progress = False
        self.search_state.reset_results()
        event.accept()


def build_application() -> QApplication:
    """Create the Qt application object with stable settings metadata."""
    app = cast(QApplication | None, QApplication.instance())
    if app is None:
        app = QApplication(sys.argv)
    app.setOrganizationName("z3950_search_for_marc")
    app.setApplicationName("z3950_search_for_marc")
    return app


def run() -> int:
    """Launch the main application window."""
    app = build_application()
    window = Z3950SearchApp()
    window.show()
    return app.exec()
