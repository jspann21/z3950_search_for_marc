"""Compatibility catalog helpers backed by the v2 catalog implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain.models import ServerDefinition
from .infrastructure.catalog import CatalogRepository, import_legacy_servers
from .resources import resource_path


def bundled_server_catalog_path() -> Path:
    return resource_path("servers.v2.json")


def resolve_server_catalog_path(configured_path: str) -> Path:
    return (
        Path(configured_path).expanduser().resolve()
        if configured_path.strip()
        else bundled_server_catalog_path()
    )


def load_servers(catalog_path: Path) -> list[ServerDefinition]:
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return list(import_legacy_servers(raw))
    repository = CatalogRepository(bundled_path=catalog_path)
    return list(repository.load_upstream().active_servers)


def normalize_server(entry: Any, index: int) -> ServerDefinition:
    try:
        servers = import_legacy_servers([entry])
    except ValueError as exc:
        raise ValueError(f"Server entry {index} is invalid: {exc}") from exc
    return servers[0]
