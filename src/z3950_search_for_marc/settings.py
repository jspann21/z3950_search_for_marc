"""Settings persistence helpers."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from .models import AppSettings


class SettingsStore:
    """Read and write application settings via QSettings."""

    def __init__(self, qsettings: QSettings):
        self._settings = qsettings

    def load(self) -> AppSettings:
        """Load persisted settings with defaults."""
        data = AppSettings(
            yaz_executable=str(self._settings.value("yaz_executable", "yaz-client")),
            server_catalog_path=str(self._settings.value("server_catalog_path", "")),
            max_concurrent_queries=int(self._settings.value("max_concurrent_queries", 12)),
            server_timeout_seconds=int(self._settings.value("server_timeout_seconds", 5)),
            default_save_directory=str(self._settings.value("default_save_directory", "")),
            trim_records=self._settings.value("trim_records", True, type=bool),
        )
        return data.normalized()

    def save(self, app_settings: AppSettings) -> AppSettings:
        """Persist the supplied settings and return the normalized copy."""
        normalized = app_settings.normalized()
        self._settings.setValue("yaz_executable", normalized.yaz_executable)
        self._settings.setValue("server_catalog_path", normalized.server_catalog_path)
        self._settings.setValue("max_concurrent_queries", normalized.max_concurrent_queries)
        self._settings.setValue("server_timeout_seconds", normalized.server_timeout_seconds)
        self._settings.setValue("default_save_directory", normalized.default_save_directory)
        self._settings.setValue("trim_records", normalized.trim_records)
        self._settings.sync()
        return normalized
