"""Atomic JSON settings with one-time migration from the v1 Qt registry keys."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .domain.models import AppSettings, Theme
from .infrastructure.atomic import atomic_write_json
from .infrastructure.paths import AppDataPaths


class LegacySettings(Protocol):
    def value(self, key: str, default_value: Any = None, type: type[Any] | None = None) -> Any: ...


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class SettingsStore:
    def __init__(
        self,
        legacy_settings: LegacySettings | None = None,
        *,
        path: Path | None = None,
    ) -> None:
        self._legacy = legacy_settings
        self.path = path or AppDataPaths.default().settings

    def load(self) -> AppSettings:
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return self._from_mapping(raw).normalized()
            except OSError, TypeError, ValueError, json.JSONDecodeError:
                return AppSettings()
        migrated = self._load_legacy() if self._legacy is not None else AppSettings()
        self.save(migrated)
        return migrated.normalized()

    def save(self, settings: AppSettings) -> AppSettings:
        normalized = settings.normalized()
        atomic_write_json(
            self.path,
            {
                "schema_version": 3,
                "max_concurrent_queries": normalized.max_concurrent_queries,
                "server_timeout_seconds": normalized.server_timeout_seconds,
                "default_save_directory": normalized.default_save_directory,
                "trim_records": normalized.trim_records,
                "theme": normalized.theme.value,
                "automatic_catalog_updates": normalized.automatic_catalog_updates,
                "check_for_app_updates_at_startup": (normalized.check_for_app_updates_at_startup),
                "disabled_server_ids": list(normalized.disabled_server_ids),
                "last_catalog_check_at": (
                    normalized.last_catalog_check_at.isoformat().replace("+00:00", "Z")
                    if normalized.last_catalog_check_at
                    else None
                ),
            },
        )
        return normalized

    @staticmethod
    def _from_mapping(raw: dict[str, Any]) -> AppSettings:
        return AppSettings(
            max_concurrent_queries=int(raw.get("max_concurrent_queries", 12)),
            server_timeout_seconds=int(raw.get("server_timeout_seconds", 5)),
            default_save_directory=str(raw.get("default_save_directory", "")),
            trim_records=bool(raw.get("trim_records", True)),
            theme=_parse_theme(raw.get("theme")),
            automatic_catalog_updates=bool(raw.get("automatic_catalog_updates", True)),
            check_for_app_updates_at_startup=bool(
                raw.get("check_for_app_updates_at_startup", True)
            ),
            disabled_server_ids=tuple(str(value) for value in raw.get("disabled_server_ids", [])),
            last_catalog_check_at=_parse_datetime(raw.get("last_catalog_check_at")),
        )

    def _load_legacy(self) -> AppSettings:
        assert self._legacy is not None
        return AppSettings(
            max_concurrent_queries=int(self._legacy.value("max_concurrent_queries", 12)),
            server_timeout_seconds=int(self._legacy.value("server_timeout_seconds", 5)),
            default_save_directory=str(self._legacy.value("default_save_directory", "")),
            trim_records=bool(self._legacy.value("trim_records", True, type=bool)),
        ).normalized()


def _parse_theme(value: Any) -> Theme:
    try:
        return Theme(str(value))
    except ValueError:
        return Theme.LIGHT
