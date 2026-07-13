from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from z3950_search_for_marc.infrastructure.catalog import (
    CatalogManifest,
    CatalogRepository,
    import_legacy_servers,
    overlay_servers,
    parse_catalog_bytes,
)
from z3950_search_for_marc.infrastructure.paths import AppDataPaths
from z3950_search_for_marc.resources import resource_path

from .helpers import server, write_catalog


def test_bundled_catalog_has_expected_verified_inventory() -> None:
    repository = CatalogRepository()
    catalog = repository.load_upstream()

    assert catalog.schema_version == 2
    assert len(catalog.servers) == 390
    assert len(catalog.active_servers) == 215
    assert len({item.id for item in catalog.servers}) == 390
    assert all(isinstance(item.port, int) for item in catalog.servers)
    assert catalog.active_servers[0].name == "Library of Congress (LC Catalog)"
    assert catalog.active_servers[0].priority == 0


def test_legacy_import_is_stable_and_deduplicated() -> None:
    legacy = [
        {
            "name": "Example",
            "host": "EXAMPLE.ORG",
            "port": "210",
            "database": "books",
            "location": "Worldwide",
        },
        {
            "name": "Duplicate",
            "host": "example.org.",
            "port": 210,
            "database": "books",
            "location": "Worldwide",
        },
    ]

    first = import_legacy_servers(legacy)
    second = import_legacy_servers(legacy)

    assert len(first) == 1
    assert first[0].id == second[0].id
    assert first[0].port == 210


def test_overlay_keeps_custom_data_separate_and_honors_disabled_ids() -> None:
    upstream = server("00000000-0000-4000-8000-000000000001")
    custom = server("00000000-0000-4000-8000-000000000002", "Custom")

    merged = overlay_servers([upstream], [custom], [upstream.id])

    assert merged == (custom,)


def test_signed_catalog_update_is_verified_and_installed(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    bundled = tmp_path / "bundled.json"
    cached = tmp_path / "data" / "catalog" / "servers.v2.json"
    write_catalog(bundled, [server()])
    updated_raw = json.loads(bundled.read_text(encoding="utf-8"))
    updated_raw["catalog_version"] = "test-2"
    payload = (json.dumps(updated_raw) + "\n").encode()
    manifest = CatalogManifest(
        schema_version=2,
        catalog_version="test-2",
        published_at=datetime.now(UTC),
        catalog_url="https://example.invalid/catalog.json",
        sha256=hashlib.sha256(payload).hexdigest(),
        signature=base64.b64encode(key.sign(payload)).decode(),
    )
    repository = CatalogRepository(
        AppDataPaths(tmp_path / "data", tmp_path / "logs"),
        bundled_path=bundled,
        schema_path=resource_path("servers.v2.schema.json"),
        public_key_path=public_path,
    )

    installed = repository.install_verified_update(manifest, payload)

    assert installed is not None
    assert installed.catalog_version == "test-2"
    assert cached.read_bytes() == payload


def test_invalid_signature_never_replaces_cached_catalog(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    bundled = tmp_path / "bundled.json"
    write_catalog(bundled, [server()])
    paths = AppDataPaths(tmp_path / "data", tmp_path / "logs")
    repository = CatalogRepository(
        paths,
        bundled_path=bundled,
        schema_path=resource_path("servers.v2.schema.json"),
        public_key_path=public_path,
    )
    payload = bundled.read_bytes()
    manifest = CatalogManifest(
        2,
        "test-1",
        datetime.now(UTC),
        "https://example.invalid/catalog.json",
        hashlib.sha256(payload).hexdigest(),
        base64.b64encode(b"x" * 64).decode(),
    )

    with pytest.raises(ValueError, match="signature"):
        repository.install_verified_update(manifest, payload)

    assert not paths.cached_catalog.exists()


def test_incompatible_schema_never_replaces_cached_catalog(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    bundled = tmp_path / "bundled.json"
    write_catalog(bundled, [server()])
    payload = bundled.read_bytes()
    paths = AppDataPaths(tmp_path / "data", tmp_path / "logs")
    repository = CatalogRepository(paths, bundled_path=bundled, public_key_path=public_path)
    manifest = CatalogManifest(
        2,
        "test-1",
        datetime.now(UTC),
        "https://example.invalid/catalog.json",
        hashlib.sha256(payload).hexdigest(),
        base64.b64encode(key.sign(payload)).decode(),
        minimum_schema_version=3,
    )

    with pytest.raises(ValueError, match="newer schema"):
        repository.install_verified_update(manifest, payload)

    assert not paths.cached_catalog.exists()


def test_disabled_server_ids_are_stored_separately(tmp_path: Path) -> None:
    paths = AppDataPaths(tmp_path / "data", tmp_path / "logs")
    repository = CatalogRepository(paths)

    repository.save_disabled_ids(["two", "one", "one"])

    assert repository.load_disabled_ids() == ("one", "two")
    assert paths.disabled_servers.is_file()


def test_update_manifest_requires_an_https_origin() -> None:
    repository = CatalogRepository(manifest_url="http://example.invalid/manifest.json")

    with pytest.raises(ValueError, match="HTTPS origin"):
        repository.check_for_update()


def test_committed_publication_matches_the_bundled_ed25519_key() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest_raw = json.loads((root / "site/catalog/v2/manifest.json").read_text(encoding="utf-8"))
    payload = (root / "site/catalog/v2/servers.v2.json").read_bytes()
    manifest = CatalogManifest(
        schema_version=int(manifest_raw["schema_version"]),
        catalog_version=str(manifest_raw["catalog_version"]),
        published_at=datetime.fromisoformat(
            str(manifest_raw["published_at"]).replace("Z", "+00:00")
        ),
        catalog_url=str(manifest_raw["catalog_url"]),
        sha256=str(manifest_raw["sha256"]),
        signature=str(manifest_raw["signature"]),
        minimum_schema_version=int(manifest_raw["minimum_schema_version"]),
    )

    assert CatalogRepository().install_verified_update(manifest, payload) is None


def test_duplicate_endpoint_is_rejected() -> None:
    payload = json.loads(resource_path("servers.v2.json").read_text(encoding="utf-8"))
    payload["servers"][1]["host"] = payload["servers"][0]["host"]
    payload["servers"][1]["port"] = payload["servers"][0]["port"]
    payload["servers"][1]["database"] = payload["servers"][0]["database"]
    schema = json.loads(resource_path("servers.v2.schema.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="duplicate normalized endpoints"):
        parse_catalog_bytes(json.dumps(payload).encode(), schema)
