from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

from z3950_search_for_marc.app import SettingsDialog, Z3950SearchApp
from z3950_search_for_marc.settings import SettingsStore


def test_settings_dialog_collects_values(qtbot, tmp_path) -> None:
    ini_path = tmp_path / "dialog.ini"
    dialog = SettingsDialog(
        SettingsStore(QSettings(str(ini_path), QSettings.Format.IniFormat)).load()
    )
    qtbot.addWidget(dialog)

    dialog.yaz_path_input.setText("C:/Tools/yaz-client.exe")
    dialog.server_catalog_input.setText("C:/data/servers.json")
    dialog.max_threads_input.setValue(7)
    dialog.timeout_input.setValue(9)
    dialog.default_save_directory_input.setText("C:/Temp")
    dialog.trim_records_checkbox.setChecked(False)
    dialog._save()

    assert dialog.saved_settings is not None
    assert dialog.saved_settings.max_concurrent_queries == 7
    assert dialog.saved_settings.server_timeout_seconds == 9
    assert dialog.saved_settings.trim_records is False


def test_window_loads_persisted_settings(qtbot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "app.ini"), QSettings.Format.IniFormat)
    settings.setValue("max_concurrent_queries", 6)
    settings.setValue("server_timeout_seconds", 8)
    settings.setValue("trim_records", False)

    window = Z3950SearchApp(qsettings=settings)
    qtbot.addWidget(window)

    assert window.app_settings.max_concurrent_queries == 6
    assert window.app_settings.server_timeout_seconds == 8
    assert window.app_settings.trim_records is False
    assert len(window.servers) > 0


def test_validate_isbn_accepts_known_valid_isbn() -> None:
    assert Z3950SearchApp.validate_isbn("9780306406157")
