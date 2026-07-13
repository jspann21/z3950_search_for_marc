"""Versioned catalog loading, legacy import, overlay, and signed updates."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from jsonschema import Draft202012Validator

from ..domain.models import (
    CatalogDocument,
    CatalogStatus,
    LocationGroup,
    ServerDefinition,
)
from ..resources import resource_path
from .atomic import atomic_write_bytes, atomic_write_json
from .paths import AppDataPaths

CATALOG_SCHEMA_VERSION = 2
DEFAULT_MANIFEST_URL = "https://jspann21.github.io/z3950_search_for_marc/catalog/v2/manifest.json"


@dataclass(frozen=True, slots=True)
class CatalogManifest:
    schema_version: int
    catalog_version: str
    published_at: datetime
    catalog_url: str
    sha256: str
    signature: str
    minimum_schema_version: int = CATALOG_SCHEMA_VERSION


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("Catalog update URLs must use an HTTPS origin.")
    return parsed.scheme.casefold(), parsed.hostname.casefold(), parsed.port


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _server_from_mapping(value: Mapping[str, Any]) -> ServerDefinition:
    return ServerDefinition(
        id=str(value["id"]),
        name=str(value["name"]),
        host=str(value["host"]),
        port=int(value["port"]),
        database=str(value["database"]),
        country_code=str(value.get("country_code", "ZZ")).upper(),
        location_group=LocationGroup(str(value.get("location_group", "Worldwide"))),
        record_syntax=str(value.get("record_syntax", "USMARC")),
        query_charset=str(value.get("query_charset", "utf-8")),
        marc_charset=str(value.get("marc_charset", "auto")),
        priority=int(value.get("priority", 500)),
        status=CatalogStatus(str(value.get("status", "active"))),
        last_verified_at=_parse_datetime(value.get("last_verified_at")),
    )


def server_to_mapping(server: ServerDefinition) -> dict[str, Any]:
    value = asdict(server)
    value["location_group"] = server.location_group.value
    value["status"] = server.status.value
    value["last_verified_at"] = (
        server.last_verified_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if server.last_verified_at
        else None
    )
    return value


def parse_catalog_bytes(payload: bytes, schema: Mapping[str, Any]) -> CatalogDocument:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Catalog is not valid UTF-8 JSON: {exc}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "catalog"
        raise ValueError(f"Invalid catalog at {location}: {first.message}")

    servers = tuple(_server_from_mapping(item) for item in raw["servers"])
    for server in servers:
        try:
            UUID(server.id)
        except ValueError as exc:
            raise ValueError(f"Catalog server ID is not a UUID: {server.id}") from exc
    ids = [server.id.casefold() for server in servers]
    endpoints = [server.endpoint.casefold() for server in servers]
    if len(ids) != len(set(ids)):
        raise ValueError("Catalog contains duplicate server IDs.")
    if len(endpoints) != len(set(endpoints)):
        raise ValueError("Catalog contains duplicate normalized endpoints.")
    return CatalogDocument(
        schema_version=int(raw["schema_version"]),
        catalog_version=str(raw["catalog_version"]),
        published_at=_parse_datetime(raw["published_at"]) or datetime.now(UTC),
        servers=tuple(
            sorted(servers, key=lambda server: (server.priority, server.name.casefold()))
        ),
    )


def import_legacy_servers(raw: Any) -> tuple[ServerDefinition, ...]:
    if not isinstance(raw, list):
        raise ValueError("Legacy server catalog must be a JSON array.")
    servers: dict[str, ServerDefinition] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Legacy server entry {index} is not an object.")
        try:
            name = str(item["name"]).strip()
            host = str(item["host"]).strip().lower().rstrip(".")
            port = int(item["port"])
            database = str(item["database"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Legacy server entry {index} is invalid.") from exc
        if not name or not host or not database or not 1 <= port <= 65535:
            raise ValueError(f"Legacy server entry {index} has invalid endpoint data.")
        location = LocationGroup(str(item.get("location", "Worldwide")))
        endpoint = f"{host}:{port}/{database}".casefold()
        if endpoint in servers:
            continue
        stable_id = str(uuid5(NAMESPACE_URL, f"z3950://{endpoint}"))
        is_loc = "library of congress" in name.casefold()
        servers[endpoint] = ServerDefinition(
            id=stable_id,
            name=name,
            host=host,
            port=port,
            database=database,
            country_code="US" if location == LocationGroup.USA else "ZZ",
            location_group=location,
            priority=100 if is_loc else 500,
        )
    return tuple(
        sorted(servers.values(), key=lambda server: (server.priority, server.name.casefold()))
    )


def overlay_servers(
    upstream: Iterable[ServerDefinition],
    custom: Iterable[ServerDefinition],
    disabled_ids: Iterable[str],
) -> tuple[ServerDefinition, ...]:
    disabled = {value.casefold() for value in disabled_ids}
    combined = {server.id.casefold(): server for server in upstream}
    for server in custom:
        combined[server.id.casefold()] = server
    active = [
        server
        for key, server in combined.items()
        if key not in disabled and server.status == CatalogStatus.ACTIVE
    ]
    return tuple(sorted(active, key=lambda server: (server.priority, server.name.casefold())))


class CatalogRepository:
    def __init__(
        self,
        paths: AppDataPaths | None = None,
        *,
        bundled_path: Path | None = None,
        schema_path: Path | None = None,
        public_key_path: Path | None = None,
        manifest_url: str = DEFAULT_MANIFEST_URL,
    ) -> None:
        self.paths = paths or AppDataPaths.default()
        self.bundled_path = bundled_path or resource_path("servers.v2.json")
        self.schema_path = schema_path or resource_path("servers.v2.schema.json")
        self.public_key_path = public_key_path or resource_path("catalog-public-key.pem")
        self.manifest_url = manifest_url

    @property
    def schema(self) -> Mapping[str, Any]:
        value = json.loads(self.schema_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("The catalog schema root must be an object.")
        return value

    def load_upstream(self) -> CatalogDocument:
        candidates = (self.paths.cached_catalog, self.bundled_path)
        errors: list[str] = []
        for candidate in candidates:
            try:
                return parse_catalog_bytes(candidate.read_bytes(), self.schema)
            except (OSError, ValueError) as exc:
                errors.append(f"{candidate}: {exc}")
        raise ValueError("No valid server catalog is available. " + " | ".join(errors))

    def load_custom(self) -> tuple[ServerDefinition, ...]:
        if not self.paths.custom_servers.exists():
            return ()
        return parse_catalog_bytes(self.paths.custom_servers.read_bytes(), self.schema).servers

    def save_custom(self, servers: Iterable[ServerDefinition]) -> None:
        values = tuple(servers)
        document = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "catalog_version": "user-1",
            "published_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "servers": [server_to_mapping(server) for server in values],
        }
        # Validate before replacing the user's last-known-good custom data.
        parse_catalog_bytes((json.dumps(document) + "\n").encode(), self.schema)
        atomic_write_json(self.paths.custom_servers, document)

    def load_disabled_ids(self) -> tuple[str, ...]:
        if not self.paths.disabled_servers.is_file():
            return ()
        try:
            raw = json.loads(self.paths.disabled_servers.read_text(encoding="utf-8"))
            if raw.get("schema_version") != 1 or not isinstance(raw.get("server_ids"), list):
                raise ValueError
            return tuple(sorted({str(value) for value in raw["server_ids"]}))
        except AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError:
            return ()

    def save_disabled_ids(self, server_ids: Iterable[str]) -> None:
        atomic_write_json(
            self.paths.disabled_servers,
            {"schema_version": 1, "server_ids": sorted({str(value) for value in server_ids})},
        )

    def import_legacy_file(self, path: Path) -> tuple[ServerDefinition, ...]:
        legacy = json.loads(path.read_text(encoding="utf-8"))
        servers = import_legacy_servers(legacy)
        self.save_custom(servers)
        return servers

    def update_due(self, last_checked: datetime | None, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return last_checked is None or current - last_checked.astimezone(UTC) >= timedelta(hours=24)

    def check_for_update(self, *, timeout_seconds: int = 15) -> CatalogDocument | None:
        expected_origin = _origin(self.manifest_url)
        with urllib.request.urlopen(self.manifest_url, timeout=timeout_seconds) as response:
            if _origin(response.geturl()) != expected_origin:
                raise ValueError("Catalog manifest redirected to an unexpected origin.")
            manifest_bytes = response.read()
        manifest = self._parse_manifest(manifest_bytes)
        if _origin(manifest.catalog_url) != expected_origin:
            raise ValueError("Catalog payload URL has an unexpected origin.")
        with urllib.request.urlopen(manifest.catalog_url, timeout=timeout_seconds) as response:
            if _origin(response.geturl()) != expected_origin:
                raise ValueError("Catalog payload redirected to an unexpected origin.")
            catalog_bytes = response.read()
        return self.install_verified_update(manifest, catalog_bytes)

    def install_verified_update(
        self, manifest: CatalogManifest, catalog_bytes: bytes
    ) -> CatalogDocument | None:
        if manifest.minimum_schema_version > CATALOG_SCHEMA_VERSION:
            raise ValueError("Catalog update requires a newer schema implementation.")
        if manifest.schema_version != CATALOG_SCHEMA_VERSION:
            raise ValueError("Catalog manifest schema version is incompatible.")
        digest = hashlib.sha256(catalog_bytes).hexdigest()
        if digest.casefold() != manifest.sha256.casefold():
            raise ValueError("Downloaded catalog SHA-256 does not match its manifest.")
        self._verify_signature(catalog_bytes, manifest.signature)
        document = parse_catalog_bytes(catalog_bytes, self.schema)
        if document.catalog_version != manifest.catalog_version:
            raise ValueError("Catalog version does not match its manifest.")
        current = self.load_upstream()
        if document.catalog_version == current.catalog_version:
            return None
        atomic_write_bytes(self.paths.cached_catalog, catalog_bytes)
        return document

    def _verify_signature(self, payload: bytes, encoded_signature: str) -> None:
        key = load_pem_public_key(self.public_key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Catalog public key is not an Ed25519 key.")
        try:
            key.verify(base64.b64decode(encoded_signature, validate=True), payload)
        except (InvalidSignature, ValueError) as exc:
            raise ValueError("Catalog signature is invalid.") from exc

    @staticmethod
    def _parse_manifest(payload: bytes) -> CatalogManifest:
        try:
            raw = json.loads(payload.decode("utf-8"))
            return CatalogManifest(
                schema_version=int(raw["schema_version"]),
                catalog_version=str(raw["catalog_version"]),
                published_at=_parse_datetime(raw["published_at"]) or datetime.now(UTC),
                catalog_url=str(raw["catalog_url"]),
                sha256=str(raw["sha256"]),
                signature=str(raw["signature"]),
                minimum_schema_version=int(
                    raw.get("minimum_schema_version", raw["schema_version"])
                ),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Catalog manifest is invalid.") from exc
