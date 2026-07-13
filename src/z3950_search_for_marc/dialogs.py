"""Application dialogs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .backend import resolve_yaz_executable
from .config import load_servers, resolve_server_catalog_path
from .models import AppSettings


class SettingsDialog(QDialog):
    """Validated settings editor backed by the existing AppSettings schema."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(590)
        self._saved_settings: AppSettings | None = None

        intro = QLabel(
            "Configure the YAZ client, server catalog, search limits, and record export defaults.",
            self,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #526176;")

        self.yaz_path_input = QLineEdit(settings.yaz_executable, self)
        self.server_catalog_input = QLineEdit(settings.server_catalog_path, self)
        self.server_catalog_input.setPlaceholderText("Bundled catalog")
        self.max_threads_input = QSpinBox(self)
        self.max_threads_input.setRange(1, 32)
        self.max_threads_input.setValue(settings.max_concurrent_queries)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 60)
        self.timeout_input.setSuffix(" seconds")
        self.timeout_input.setValue(settings.server_timeout_seconds)
        self.default_save_directory_input = QLineEdit(settings.default_save_directory, self)
        self.trim_records_checkbox = QCheckBox("Remove tags 000–009 and 900+", self)
        self.trim_records_checkbox.setChecked(settings.trim_records)

        form = QFormLayout()
        form.addRow("YAZ executable", self._browse_row(self.yaz_path_input, self._browse_yaz_path))
        form.addRow(
            "Server catalog", self._browse_row(self.server_catalog_input, self._browse_catalog_path)
        )
        form.addRow("Concurrent queries", self.max_threads_input)
        form.addRow("Server timeout", self.timeout_input)
        form.addRow(
            "Save directory",
            self._browse_row(self.default_save_directory_input, self._browse_save_directory),
        )
        form.addRow("Record trimming", self.trim_records_checkbox)

        save_button = QPushButton("Save settings", self)
        save_button.setProperty("primary", True)
        cancel_button = QPushButton("Cancel", self)
        save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(cancel_button)
        actions.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addLayout(actions)

    @property
    def saved_settings(self) -> AppSettings | None:
        return self._saved_settings

    def _browse_row(self, field: QLineEdit, callback: object) -> QWidget:
        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        button = QPushButton("Browse…", container)
        button.clicked.connect(callback)  # type: ignore[arg-type]
        row.addWidget(button)
        return container

    def _browse_yaz_path(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select yaz-client executable", self.yaz_path_input.text()
        )
        if file_path:
            self.yaz_path_input.setText(file_path)

    def _browse_catalog_path(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select server catalog",
            self.server_catalog_input.text() or str(Path.home()),
            "JSON files (*.json)",
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
        candidate = AppSettings(
            yaz_executable=self.yaz_path_input.text(),
            server_catalog_path=self.server_catalog_input.text(),
            max_concurrent_queries=self.max_threads_input.value(),
            server_timeout_seconds=self.timeout_input.value(),
            default_save_directory=self.default_save_directory_input.text(),
            trim_records=self.trim_records_checkbox.isChecked(),
        ).normalized()

        if resolve_yaz_executable(candidate.yaz_executable) is None:
            QMessageBox.warning(
                self,
                "YAZ executable not found",
                "The selected yaz-client executable could not be found. "
                "Choose its full path or install YAZ and add it to PATH.",
            )
            return
        try:
            load_servers(resolve_server_catalog_path(candidate.server_catalog_path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid server catalog", str(exc))
            return
        save_directory = Path(candidate.default_save_directory).expanduser()
        if not save_directory.is_dir():
            QMessageBox.warning(
                self,
                "Invalid save directory",
                "Choose an existing directory for exported MARC records.",
            )
            return

        self._saved_settings = candidate
        self.accept()
