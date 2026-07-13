from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt

from z3950_search_for_marc.app import SettingsDialog, Z3950SearchApp
from z3950_search_for_marc.backend import CancellationToken
from z3950_search_for_marc.models import BackendResponse, ServerConfig
from z3950_search_for_marc.settings import SettingsStore


class FakeBackend:
    def search_server(self, request, server, position, cancellation):
        if cancellation.is_canceled:
            raise AssertionError("Canceled work should not be queried")
        return BackendResponse(
            f"Number of hits: 2\n245 10 $a Record {position}\n",
            f"245 10 $a Record {position}",
            2,
        )

    def cancel(self, cancellation: CancellationToken) -> None:
        cancellation.cancel()


def test_settings_dialog_collects_values(qtbot, tmp_path) -> None:
    ini_path = tmp_path / "dialog.ini"
    yaz_executable = tmp_path / "yaz-client.exe"
    yaz_executable.write_bytes(b"")
    dialog = SettingsDialog(
        SettingsStore(QSettings(str(ini_path), QSettings.Format.IniFormat)).load()
    )
    qtbot.addWidget(dialog)

    dialog.yaz_path_input.setText(str(yaz_executable))
    dialog.server_catalog_input.clear()
    dialog.max_threads_input.setValue(7)
    dialog.timeout_input.setValue(9)
    dialog.default_save_directory_input.setText(str(tmp_path))
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


def test_complete_search_navigation_and_export_workflow(qtbot, tmp_path: Path, monkeypatch) -> None:
    window = Z3950SearchApp(
        qsettings=QSettings(str(tmp_path / "workflow.ini"), QSettings.Format.IniFormat),
        backend=FakeBackend(),
    )
    qtbot.addWidget(window)
    window.servers = [ServerConfig("Test Library", "example.org", 210, "db", "USA")]
    window.search_panel.isbn_input.setText("9780306406157")

    qtbot.mouseClick(window.search_panel.search_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not window._search_running, timeout=2000)
    assert window.results_panel.table.rowCount() == 1

    window.results_panel.table.selectRow(0)
    qtbot.waitUntil(lambda: "Record 1" in window.record_panel.details.toPlainText())
    qtbot.mouseClick(window.record_panel.next_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.search_state.current_position == 2)
    assert "Record 2" in window.record_panel.details.toPlainText()

    qtbot.mouseClick(window.record_panel.previous_button, Qt.MouseButton.LeftButton)
    assert window.search_state.current_position == 1

    export_path = tmp_path / "record.mrc"
    monkeypatch.setattr(
        "z3950_search_for_marc.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "MARC records (*.mrc)"),
    )
    qtbot.mouseClick(window.record_panel.export_button, Qt.MouseButton.LeftButton)
    assert export_path.read_bytes()
