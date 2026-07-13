"""Settings and catalog import dialogs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from .domain.models import AppSettings, Theme


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        *,
        engine_version: str,
        catalog_version: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(610)
        self._saved_settings: AppSettings | None = None
        self._legacy_catalog_path: Path | None = None

        intro = QLabel(
            f"Embedded YAZ {engine_version} · Server catalog {catalog_version}. "
            "No external protocol software is required.",
            self,
        )
        intro.setWordWrap(True)
        intro.setObjectName("secondaryText")
        defaults = AppSettings()
        self.max_threads_input = QSpinBox(self)
        self.max_threads_input.setRange(1, 32)
        self.max_threads_input.setValue(settings.max_concurrent_queries)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 60)
        self.timeout_input.setSuffix(" seconds")
        self.timeout_input.setValue(settings.server_timeout_seconds)
        self.default_save_directory_input = QLineEdit(settings.default_save_directory, self)
        self.trim_records_checkbox = QCheckBox(
            "Hide and remove tags 000–009 and 900+ from exported records", self
        )
        self.trim_records_checkbox.setChecked(settings.trim_records)
        self.theme_input = QComboBox(self)
        self.theme_input.setAccessibleName("Theme")
        self.theme_input.addItem("Light", Theme.LIGHT)
        self.theme_input.addItem("Dark", Theme.DARK)
        self.theme_input.setCurrentIndex(self.theme_input.findData(settings.theme))
        self.automatic_updates_checkbox = QCheckBox("Update the server catalog automatically", self)
        self.automatic_updates_checkbox.setChecked(settings.automatic_catalog_updates)
        self.import_catalog_input = QLineEdit(self)
        self.import_catalog_input.setReadOnly(True)
        self.import_catalog_input.setPlaceholderText("No legacy catalog selected")

        form = QFormLayout()
        form.addRow(
            "Concurrent targets",
            self._field_with_default(
                self.max_threads_input, f"Default: {defaults.max_concurrent_queries}"
            ),
        )
        form.addRow(
            "Server timeout",
            self._field_with_default(
                self.timeout_input, f"Default: {defaults.server_timeout_seconds} seconds"
            ),
        )
        form.addRow(
            "Save directory",
            self._browse_row(self.default_save_directory_input, self._browse_save_directory),
        )
        form.addRow("Record trimming", self.trim_records_checkbox)
        form.addRow("Catalog updates", self.automatic_updates_checkbox)
        form.addRow(
            "Import old JSON",
            self._browse_row(self.import_catalog_input, self._browse_legacy_catalog),
        )
        form.addRow("Theme", self.theme_input)

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

    @property
    def legacy_catalog_path(self) -> Path | None:
        return self._legacy_catalog_path

    def _browse_row(self, field: QLineEdit, callback: Callable[[], None]) -> QWidget:
        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        button = QPushButton("Browse…", container)
        button.clicked.connect(callback)
        row.addWidget(button)
        return container

    def _field_with_default(self, field: QWidget, text: str) -> QWidget:
        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(field, 1)
        default_label = QLabel(text, container)
        default_label.setObjectName("fieldHint")
        row.addWidget(default_label)
        return container

    def _browse_save_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select default save directory",
            self.default_save_directory_input.text() or str(Path.home()),
        )
        if directory:
            self.default_save_directory_input.setText(directory)

    def _browse_legacy_catalog(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Import legacy server JSON",
            str(Path.home()),
            "JSON files (*.json)",
        )
        if file_name:
            self._legacy_catalog_path = Path(file_name)
            self.import_catalog_input.setText(file_name)

    def _save(self) -> None:
        directory = Path(self.default_save_directory_input.text()).expanduser()
        if not directory.is_dir():
            QMessageBox.warning(self, "Invalid save directory", "Choose an existing directory.")
            return
        self._saved_settings = AppSettings(
            max_concurrent_queries=self.max_threads_input.value(),
            server_timeout_seconds=self.timeout_input.value(),
            default_save_directory=str(directory),
            trim_records=self.trim_records_checkbox.isChecked(),
            theme=Theme(self.theme_input.currentData()),
            automatic_catalog_updates=self.automatic_updates_checkbox.isChecked(),
        ).normalized()
        self.accept()
