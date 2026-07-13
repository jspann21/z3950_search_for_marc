from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from z3950_search_for_marc.app import Z3950SearchApp
from z3950_search_for_marc.domain.models import AppSettings
from z3950_search_for_marc.infrastructure.catalog import CatalogRepository
from z3950_search_for_marc.infrastructure.paths import AppDataPaths
from z3950_search_for_marc.settings import SettingsStore

from .helpers import server, write_catalog
from .test_search import FakeEngine


def test_main_window_searches_and_displays_record(qtbot, tmp_path: Path) -> None:
    bundled = tmp_path / "catalog.json"
    write_catalog(bundled, [server()])
    paths = AppDataPaths(tmp_path / "data", tmp_path / "logs")
    repository = CatalogRepository(paths, bundled_path=bundled)
    settings = SettingsStore(path=paths.settings)
    settings.save(AppSettings(automatic_catalog_updates=False))
    qsettings = QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat)
    window = Z3950SearchApp(
        qsettings,
        FakeEngine(),
        settings_store=settings,
        catalog_repository=repository,
    )
    qtbot.addWidget(window)
    window.show()
    window.isbn_input.setText("9780306406157")

    try:
        window._start_isbn_search()
        qtbot.waitUntil(lambda: window.results_panel.model.available_count == 1, timeout=2000)
        window.results_window.selectRow(0)
        qtbot.waitUntil(
            lambda: "Test title" in window.record_details_window.toPlainText(), timeout=2000
        )

        assert window.engine.version == "test"
        assert window.download_button.isEnabled()
    finally:
        window.close()
