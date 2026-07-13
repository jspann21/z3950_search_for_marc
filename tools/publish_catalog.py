"""Validate and sign a catalog for the GitHub Pages publication directory."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from jsonschema import Draft202012Validator

from z3950_search_for_marc.infrastructure.catalog import parse_catalog_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog/servers.v2.json"))
    parser.add_argument("--schema", type=Path, default=Path("catalog/servers.v2.schema.json"))
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("site/catalog/v2"))
    parser.add_argument(
        "--public-url",
        default=("https://jspann21.github.io/z3950_search_for_marc/catalog/v2/servers.v2.json"),
    )
    args = parser.parse_args()

    document = json.loads(args.catalog.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(document)
    parse_catalog_bytes(args.catalog.read_bytes(), schema)
    publication = dict(document)
    publication["servers"] = [
        server for server in document["servers"] if server["status"] == "active"
    ]
    catalog_bytes = (json.dumps(publication, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    key = load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Catalog signing key must be Ed25519.")
    signature = base64.b64encode(key.sign(catalog_bytes)).decode("ascii")
    manifest = {
        "schema_version": 2,
        "minimum_schema_version": 2,
        "catalog_version": document["catalog_version"],
        "published_at": document["published_at"],
        "catalog_url": args.public_url,
        "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "signature": signature,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "servers.v2.json").write_bytes(catalog_bytes)
    shutil.copyfile(args.schema, args.output / "servers.v2.schema.json")
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
