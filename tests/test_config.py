from __future__ import annotations

import json
from pathlib import Path

import pytest

from z3950_search_for_marc.config import load_servers, normalize_server


def test_load_servers_normalizes_ports_and_prioritizes_loc(tmp_path: Path) -> None:
    catalog = tmp_path / "servers.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "name": "Other Library",
                    "host": "example.org",
                    "port": "210",
                    "database": "books",
                    "location": "Worldwide",
                },
                {
                    "name": "Library of Congress -- Washington, DC",
                    "host": "z3950.loc.gov",
                    "port": "7090",
                    "database": "Voyager",
                    "location": "USA",
                },
            ]
        ),
        encoding="utf-8",
    )

    servers = load_servers(catalog)

    assert servers[0].name.startswith("Library of Congress")
    assert servers[0].port == 7090
    assert servers[1].port == 210


def test_normalize_server_rejects_missing_keys() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        normalize_server({"name": "Broken"}, 0)
