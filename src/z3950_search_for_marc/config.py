"""Configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ServerConfig
from .resources import resource_path

REQUIRED_SERVER_KEYS = {"name", "host", "port", "database", "location"}


def bundled_server_catalog_path() -> Path:
    """Return the bundled server catalog path."""
    return resource_path("servers.json")


def resolve_server_catalog_path(configured_path: str) -> Path:
    """Resolve the configured server catalog or fall back to the bundled catalog."""
    if configured_path.strip():
        return Path(configured_path).expanduser().resolve()
    return bundled_server_catalog_path()


def load_servers(catalog_path: Path) -> list[ServerConfig]:
    """Load and validate server definitions from JSON."""
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Server catalog must be a JSON array.")

    servers = [normalize_server(entry, index) for index, entry in enumerate(raw)]
    return sorted(
        servers,
        key=lambda server: (0 if "library of congress" in server.name.lower() else 1, server.name),
    )


def normalize_server(entry: Any, index: int) -> ServerConfig:
    """Validate and normalize a single server row."""
    if not isinstance(entry, dict):
        raise ValueError(f"Server entry {index} is not an object.")

    missing = REQUIRED_SERVER_KEYS - set(entry)
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"Server entry {index} is missing keys: {joined}.")

    try:
        port = int(entry["port"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Server entry {index} has an invalid port: {entry['port']!r}.") from exc

    if port < 1 or port > 65535:
        raise ValueError(f"Server entry {index} port {port} is out of range.")

    name = str(entry["name"]).strip()
    host = str(entry["host"]).strip()
    database = str(entry["database"]).strip()
    if not name or not host or not database:
        raise ValueError(f"Server entry {index} has an empty name, host, or database.")

    raw_location = str(entry["location"]).strip() or "Worldwide"
    location_lookup = {"usa": "USA", "worldwide": "Worldwide"}
    location = location_lookup.get(raw_location.casefold())
    if location is None:
        raise ValueError(
            f"Server entry {index} has an invalid location: {raw_location!r}. "
            "Expected 'USA' or 'Worldwide'."
        )
    return ServerConfig(
        name=name,
        host=host,
        port=port,
        database=database,
        location=location,
    )
