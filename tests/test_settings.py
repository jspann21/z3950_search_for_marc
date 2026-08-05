from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from z3950_search_for_marc.domain.models import AppSettings
from z3950_search_for_marc.settings import SettingsStore


class Legacy:
    values = {
        "max_concurrent_queries": 50,
        "server_timeout_seconds": 7,
        "default_save_directory": "C:/Exports",
        "trim_records": False,
        "yaz_executable": "ignored.exe",
    }

    def value(self, key: str, default_value: Any = None, type: type[Any] | None = None) -> Any:
        value = self.values.get(key, default_value)
        return type(value) if type else value


def test_legacy_settings_migrate_once_and_obsolete_yaz_path_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(Legacy(), path=path)

    settings = store.load()

    assert settings.max_concurrent_queries == 32
    assert settings.server_timeout_seconds == 7
    assert settings.trim_records is False
    assert "yaz" not in path.read_text(encoding="utf-8").casefold()


def test_invalid_settings_file_falls_back_safely(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")

    settings = SettingsStore(path=path).load()

    assert settings == AppSettings()


def test_settings_write_is_complete_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    SettingsStore(path=path).save(AppSettings(trim_records=False))

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 3
    assert payload["trim_records"] is False
