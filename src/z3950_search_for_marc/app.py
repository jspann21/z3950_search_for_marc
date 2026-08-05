"""Application composition and desktop workflow coordination."""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .dialogs import SettingsDialog
from .domain.models import (
    AppSettings,
    BackendFailure,
    FailureKind,
    QueryType,
    SearchProgress,
    SearchRequest,
    SearchSession,
    ServerDefinition,
    ServerResult,
    ServerStatus,
)
from .infrastructure.catalog import CatalogRepository, overlay_servers
from .infrastructure.paths import AppDataPaths
from .infrastructure.yaz_engine import SessionEngine, ZoomSessionEngine
from .marc import (
    format_record_for_display,
    get_record_info,
    record_bytes_for_export,
    sanitize_filename,
)
from .models import MarcRecord, RecordReference, SearchState
from .resources import resource_path
from .search import SearchCoordinator
from .settings import SettingsStore
from .theme import apply_theme
from .updates import AvailableUpdate, check_for_application_update
from .widgets import ActivityPanel, RecordPanel, ResultsPanel, SearchPanel

__all__ = ["SettingsDialog", "Z3950SearchApp", "build_application", "run"]

PROJECT_REPOSITORY_URL = "https://github.com/jspann21/z3950_search_for_marc"
APPLICATION_DISPLAY_NAME = f"Z39.50 MARC Search {__version__}"


class _CatalogUpdateSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _CatalogUpdateTask(QRunnable):
    def __init__(self, repository: CatalogRepository) -> None:
        super().__init__()
        self.repository = repository
        self.signals = _CatalogUpdateSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.repository.check_for_update()
        except Exception as exc:  # network and validation boundaries are reported to the UI
            self.signals.failed.emit(str(exc))
        else:
            self.signals.completed.emit(result)


class _ApplicationUpdateSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _ApplicationUpdateTask(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = _ApplicationUpdateSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = check_for_application_update()
        except Exception as exc:  # network and GitHub response failures are reported to the UI
            self.signals.failed.emit(str(exc))
        else:
            self.signals.completed.emit(result)


class Z3950SearchApp(QMainWindow):
    def __init__(
        self,
        qsettings: QSettings | None = None,
        engine: SessionEngine | None = None,
        *,
        settings_store: SettingsStore | None = None,
        catalog_repository: CatalogRepository | None = None,
    ) -> None:
        super().__init__()
        self.qsettings = qsettings or QSettings()
        self.paths = catalog_repository.paths if catalog_repository else AppDataPaths.default()
        self.settings_store = settings_store or SettingsStore(
            self.qsettings, path=self.paths.settings
        )
        self.app_settings = self.settings_store.load()
        application = cast(QApplication | None, QApplication.instance())
        if application is not None:
            apply_theme(application, self.app_settings.theme)
        self.catalog_repository = catalog_repository or CatalogRepository(self.paths)
        self._startup_warnings: list[str] = []
        if self.app_settings.disabled_server_ids and not self.paths.disabled_servers.exists():
            self.catalog_repository.save_disabled_ids(self.app_settings.disabled_server_ids)
        self.catalog_document = self.catalog_repository.load_upstream()
        self.servers: list[ServerDefinition] = []
        self._reload_catalog()
        self.search_state = SearchState()
        self.engine = engine or ZoomSessionEngine()
        self.coordinator = SearchCoordinator(self.engine, self)
        self._search_running = False
        self._successful_servers = 0
        self._failed_servers = 0
        self._update_task: _CatalogUpdateTask | None = None
        self._app_update_task: _ApplicationUpdateTask | None = None
        self._app_update_is_manual = False

        self._init_ui()
        self._connect_coordinator()
        self._report_engine_status()
        if self.app_settings.automatic_catalog_updates and self.catalog_repository.update_due(
            self.app_settings.last_catalog_check_at
        ):
            QTimer.singleShot(1500, self._check_catalog_update)
        if self.app_settings.check_for_app_updates_at_startup:
            QTimer.singleShot(2500, self._check_application_update)

    def _init_ui(self) -> None:
        self.setWindowTitle(APPLICATION_DISPLAY_NAME)
        self.setMinimumSize(1180, 700)
        self.resize(1520, 880)
        icon_path = resource_path("app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.search_panel = SearchPanel(self)
        self.results_panel = ResultsPanel(self)
        self.record_panel = RecordPanel(self)
        self.activity_panel = ActivityPanel(self)
        self.workspace = QSplitter(self)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.addWidget(self.search_panel)
        self.workspace.addWidget(self.results_panel)
        self.workspace.addWidget(self.record_panel)
        self.workspace.setStretchFactor(0, 0)
        self.workspace.setStretchFactor(1, 1)
        self.workspace.setStretchFactor(2, 1)
        self.workspace.setSizes([285, 610, 625])
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.workspace, 1)
        layout.addWidget(self.activity_panel)
        self.setCentralWidget(central)
        self._status_bar = self.statusBar()
        self._status_bar.showMessage("Ready")

        self.search_panel.search_requested.connect(self._start_search_from_panel)
        self.search_panel.cancel_requested.connect(self._cancel_search)
        self.search_panel.settings_requested.connect(self._open_settings_dialog)
        self.results_panel.result_selected.connect(self._select_result)
        self.record_panel.previous_requested.connect(self._show_previous_record)
        self.record_panel.next_requested.connect(self._show_next_record)
        self.record_panel.export_requested.connect(self._export_record)

        settings_action = QAction("Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings_dialog)
        update_action = QAction("Check server catalog for updates", self)
        update_action.triggered.connect(self._check_catalog_update)
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        github_action = QAction("View project on GitHub", self)
        github_action.triggered.connect(self._open_project_repository)
        app_update_action = QAction("Check for application updates…", self)
        app_update_action.triggered.connect(lambda: self._check_application_update(manual=True))
        self.addAction(settings_action)
        self.addAction(update_action)
        self.addAction(exit_action)
        self.addAction(github_action)
        self.addAction(app_update_action)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)
        catalog_menu = self.menuBar().addMenu("Server Catalog")
        catalog_menu.addAction(update_action)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(app_update_action)
        help_menu.addSeparator()
        help_menu.addAction(github_action)

        # Stable compatibility attributes for existing UI automation.
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

    def _report_engine_status(self) -> None:
        for warning in self._startup_warnings:
            self.log_message(warning)
        if self.engine.available:
            self.log_message(f"Embedded YAZ engine ready: {self.engine.version}")
            self._status_bar.showMessage(
                f"Ready · catalog {self.catalog_document.catalog_version} · "
                f"{len(self.servers)} servers"
            )
        else:
            self.log_message(
                "Embedded YAZ engine is unavailable; reinstall the complete application."
            )
            self._status_bar.showMessage("Embedded protocol engine unavailable")

    def _reload_catalog(self) -> None:
        self.catalog_document = self.catalog_repository.load_upstream()
        try:
            custom = self.catalog_repository.load_custom()
        except (OSError, ValueError) as exc:
            custom = ()
            self._startup_warnings.append(
                f"Custom server catalog was ignored because it is invalid: {exc}"
            )
        self.servers = list(
            overlay_servers(
                self.catalog_document.servers,
                custom,
                self.catalog_repository.load_disabled_ids(),
            )
        )

    @staticmethod
    def validate_isbn(isbn: str) -> bool:
        normalized = isbn.replace("-", "").replace(" ", "").upper()
        if not re.fullmatch(r"(97[89])?\d{9}[\dX]", normalized):
            return False
        if len(normalized) == 10:
            return (
                sum(
                    (10 - index) * (10 if char == "X" else int(char))
                    for index, char in enumerate(normalized)
                )
                % 11
                == 0
            )
        return (
            len(normalized) == 13
            and "X" not in normalized
            and sum(
                (1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(normalized)
            )
            % 10
            == 0
        )

    def _request_from_panel(self) -> SearchRequest | None:
        locations = self.search_panel.selected_locations
        if not locations:
            QMessageBox.warning(self, "Choose a location", "Select at least one location filter.")
            return None
        if self.search_panel.query_type == QueryType.ISBN:
            isbn = self.isbn_input.text().strip()
            if not self.validate_isbn(isbn):
                QMessageBox.warning(self, "Invalid ISBN", "Enter a valid ISBN-10 or ISBN-13.")
                return None
            query: str | tuple[str, str] = isbn
        else:
            title = self.title_input.text().strip()
            author = self.author_input.text().strip()
            if not title or not author:
                QMessageBox.warning(
                    self, "Title and author required", "Enter both a title and an author."
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
        if not self.engine.available:
            QMessageBox.critical(
                self,
                "Protocol engine unavailable",
                "The embedded YAZ library could not be loaded. Reinstall the complete application.",
            )
            return
        filtered = [server for server in self.servers if server.location in request.locations]
        if not filtered:
            QMessageBox.warning(self, "No servers", "No active servers match those locations.")
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
        self.log_message(f"Starting search across {len(filtered)} active servers.")
        self.coordinator.start(session, filtered, self.app_settings.max_concurrent_queries)

    def _start_isbn_search(self) -> None:
        self.search_panel.tabs.setCurrentIndex(0)
        self._start_search_from_panel()

    def _start_title_author_search(self) -> None:
        self.search_panel.tabs.setCurrentIndex(1)
        self._start_search_from_panel()

    def _start_search(self) -> None:
        self._start_search_from_panel()

    @Slot(object)
    def _handle_server_change(self, result: ServerResult) -> None:
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

    @Slot(object)
    def _handle_progress(self, progress: SearchProgress) -> None:
        session = self.search_state.session
        if session and progress.session_id == session.id:
            self.results_panel.set_progress(progress.completed, progress.total, progress.percentage)

    @Slot(object)
    def _handle_search_finished(self, session_id: UUID) -> None:
        session = self.search_state.session
        if session is None or session.id != session_id or not self._search_running:
            return
        self._search_running = False
        self.search_panel.set_searching(False)
        self.results_panel.finish()
        self._status_bar.showMessage(
            f"Search complete · {self._successful_servers} servers with records"
        )
        self.log_message(
            f"Search complete: {self._successful_servers} available; "
            f"{self._failed_servers} failed or timed out."
        )

    def _cancel_search(self) -> None:
        self.coordinator.cancel()
        self._search_running = False
        self.search_state.fetch_in_progress = False
        self.search_panel.set_searching(False)
        self.results_panel.finish(canceled=True)
        self._status_bar.showMessage("Search canceled")
        self.log_message("Search canceled; native session cleanup requested.")

    def _select_result(self, result: ServerResult) -> None:
        session = self.search_state.session
        if session is None or result.session_id != session.id or result.record is None:
            return
        self.search_state.select(result, result.record)
        self._display_current_record()

    def _display_current_record(self) -> None:
        result = self.search_state.selected_result
        record = self.search_state.current_marc_record
        if result is None or record is None:
            self.record_panel.clear()
            return
        self.record_panel.show_record(
            result.server.name,
            self.search_state.current_position,
            result.number_of_hits,
            format_record_for_display(record, trim_records=self.app_settings.trim_records),
            trimmed_export=self.app_settings.trim_records,
        )

    def _show_previous_record(self) -> None:
        if not self.search_state.fetch_in_progress and self.search_state.current_position > 1:
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
        cached = self.search_state.records.get((result.server.id, position))
        if cached:
            self.search_state.current_position = position
            self._display_current_record()
            return
        self.search_state.fetch_in_progress = True
        self.record_panel.show_loading(result.server.name, position, result.number_of_hits)
        self.coordinator.fetch_record(RecordReference(session.id, result.server, position))

    @Slot(object, object)
    def _handle_record_fetched(
        self, reference: RecordReference, outcome: MarcRecord | BackendFailure
    ) -> None:
        session = self.search_state.session
        if session is None or reference.session_id != session.id:
            return
        self.search_state.fetch_in_progress = False
        if isinstance(outcome, BackendFailure):
            if outcome.kind != FailureKind.CANCELED:
                self.log_message(f"Record fetch failed: {outcome.message}")
                QMessageBox.warning(self, "Record fetch failed", outcome.message)
            self._display_current_record()
            return
        self.search_state.records[reference.cache_key] = outcome
        self.search_state.current_position = reference.position
        self._display_current_record()

    def _export_record(self) -> None:
        record = self.search_state.current_marc_record
        if record is None:
            return
        author, title = get_record_info(record)
        suggested = sanitize_filename(f"{author}_{title}") + ".mrc"
        directory = Path(self.app_settings.default_save_directory).expanduser()
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Export trimmed MARC record"
            if self.app_settings.trim_records
            else "Export MARC record",
            str(directory / suggested),
            "MARC records (*.mrc)",
        )
        if not file_name:
            return
        try:
            Path(file_name).write_bytes(
                record_bytes_for_export(record, trim_records=self.app_settings.trim_records)
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        mode = "trimmed" if self.app_settings.trim_records else "original"
        self.log_message(f"Exported {mode} MARC record to {file_name}.")

    def _download_marc_record(self) -> None:
        self._export_record()

    def _open_project_repository(self) -> None:
        QDesktopServices.openUrl(QUrl(PROJECT_REPOSITORY_URL))

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(
            self.app_settings,
            app_version=__version__,
            engine_version=self.engine.version,
            catalog_version=self.catalog_document.catalog_version,
            parent=self,
        )
        dialog.app_update_check_requested.connect(
            lambda: self._check_application_update(manual=True)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_settings is None:
            return
        old = self.app_settings
        candidate = dialog.saved_settings
        self.app_settings = AppSettings(
            max_concurrent_queries=candidate.max_concurrent_queries,
            server_timeout_seconds=candidate.server_timeout_seconds,
            default_save_directory=candidate.default_save_directory,
            trim_records=candidate.trim_records,
            theme=candidate.theme,
            automatic_catalog_updates=candidate.automatic_catalog_updates,
            check_for_app_updates_at_startup=candidate.check_for_app_updates_at_startup,
            disabled_server_ids=old.disabled_server_ids,
            last_catalog_check_at=old.last_catalog_check_at,
        ).normalized()
        application = cast(QApplication | None, QApplication.instance())
        if application is not None:
            apply_theme(application, self.app_settings.theme)
        self.results_panel.refresh_theme()
        if dialog.legacy_catalog_path:
            try:
                imported = self.catalog_repository.import_legacy_file(dialog.legacy_catalog_path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Catalog import failed", str(exc))
            else:
                self.log_message(f"Imported {len(imported)} custom servers.")
        self.settings_store.save(self.app_settings)
        self._reload_catalog()
        self._display_current_record()
        self.log_message("Settings saved and applied.")

    def _check_application_update(self, *, manual: bool = False) -> None:
        if self._app_update_task is not None:
            self._app_update_is_manual = self._app_update_is_manual or manual
            if manual:
                self._status_bar.showMessage(
                    "An application update check is already running.", 4000
                )
            return
        self._app_update_is_manual = manual
        if manual:
            self._status_bar.showMessage("Checking GitHub for application updates…")
        task = _ApplicationUpdateTask()
        task.signals.completed.connect(self._application_update_completed)
        task.signals.failed.connect(self._application_update_failed)
        self._app_update_task = task
        QThreadPool.globalInstance().start(task)

    @Slot(object)
    def _application_update_completed(self, update: object) -> None:
        manual = self._app_update_is_manual
        self._app_update_task = None
        if update is not None and not isinstance(update, AvailableUpdate):
            self._application_update_failed("GitHub returned an invalid update result.")
            return
        self._app_update_is_manual = False
        if update is None:
            self._status_bar.showMessage(f"Z39.50 MARC Search {__version__} is current.", 5000)
            if manual:
                QMessageBox.information(
                    self,
                    "No application update available",
                    f"You are using the latest released version ({__version__}).",
                )
            return
        assert isinstance(update, AvailableUpdate)
        self.log_message(f"Application version {update.version} is available on GitHub.")
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Application update available")
        message.setText(f"Z39.50 MARC Search {update.version} is available.")
        message.setInformativeText(
            f"You are using version {__version__}. Open the GitHub release page to view the "
            "installer and release notes. Your settings and chosen save directory are preserved "
            "when you install the update over this version."
        )
        view_button = message.addButton("View release on GitHub", QMessageBox.ButtonRole.AcceptRole)
        message.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        message.exec()
        if message.clickedButton() is view_button:
            QDesktopServices.openUrl(QUrl(update.page_url))

    @Slot(str)
    def _application_update_failed(self, message: str) -> None:
        manual = self._app_update_is_manual
        self._app_update_task = None
        self._app_update_is_manual = False
        self.log_message(f"Could not check for an application update: {message}")
        self._status_bar.showMessage("The application update check could not be completed.", 5000)
        if manual:
            QMessageBox.warning(
                self,
                "Application update check failed",
                "The latest release could not be checked. Confirm that you are online and try "
                "again later.\n\n"
                f"Details: {message}",
            )

    def _check_catalog_update(self) -> None:
        if self._update_task is not None:
            return
        self.log_message("Checking the signed server catalog for updates…")
        task = _CatalogUpdateTask(self.catalog_repository)
        task.signals.completed.connect(self._catalog_update_completed)
        task.signals.failed.connect(self._catalog_update_failed)
        self._update_task = task
        QThreadPool.globalInstance().start(task)

    @Slot(object)
    def _catalog_update_completed(self, updated: object) -> None:
        self._update_task = None
        self.app_settings = replace(self.app_settings, last_catalog_check_at=datetime.now(UTC))
        self.settings_store.save(self.app_settings)
        if updated is None:
            self.log_message("The server catalog is already current.")
            return
        self._reload_catalog()
        self.log_message(
            f"Installed catalog {self.catalog_document.catalog_version} with "
            f"{len(self.servers)} active servers."
        )

    @Slot(str)
    def _catalog_update_failed(self, message: str) -> None:
        self._update_task = None
        self.app_settings = replace(self.app_settings, last_catalog_check_at=datetime.now(UTC))
        self.settings_store.save(self.app_settings)
        self.log_message(f"Catalog update was not installed: {message}")

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802
        self.coordinator.shutdown()
        if event is not None:
            event.accept()


def build_application() -> QApplication:
    app = cast(QApplication | None, QApplication.instance())
    if app is None:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
        app = QApplication(sys.argv)
    app.setOrganizationName("z3950_search_for_marc")
    app.setApplicationName("z3950_search_for_marc")
    app.setApplicationDisplayName(APPLICATION_DISPLAY_NAME)
    apply_theme(app)
    return app


def run(*, smoke_test: bool = False) -> int:
    app = build_application()
    try:
        window = Z3950SearchApp()
    except (OSError, ValueError) as exc:
        QMessageBox.critical(
            None,
            "Z39.50 MARC Search could not start",
            f"No valid server catalog or settings could be loaded.\n\n{exc}",
        )
        return 1
    window.show()
    if smoke_test:
        QTimer.singleShot(500, app.quit)
    return app.exec()
