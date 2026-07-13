"""Convert a legacy server array into the canonical v2 catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def convert(source: Path, version: str) -> dict[str, object]:
    legacy = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(legacy, list):
        raise ValueError("Legacy catalog must be an array.")

    converted: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in legacy:
        host = str(item["host"]).strip().lower().rstrip(".")
        port = int(item["port"])
        database = str(item["database"]).strip()
        endpoint = f"{host}:{port}/{database}".casefold()
        if endpoint in seen:
            continue
        seen.add(endpoint)
        name = str(item["name"]).strip()
        location = str(item.get("location", "Worldwide"))
        converted.append(
            {
                "id": str(uuid5(NAMESPACE_URL, f"z3950://{endpoint}")),
                "name": name,
                "host": host,
                "port": port,
                "database": database,
                "country_code": "US" if location == "USA" else "ZZ",
                "location_group": location,
                "record_syntax": "USMARC",
                "query_charset": "utf-8",
                "marc_charset": "auto",
                "priority": 100 if "library of congress" in name.casefold() else 500,
                "status": "active",
                "last_verified_at": None,
            }
        )
    converted.sort(key=lambda server: (int(server["priority"]), str(server["name"]).casefold()))
    return {
        "schema_version": 2,
        "catalog_version": version,
        "published_at": "2026-07-13T00:00:00Z",
        "servers": converted,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--version", default="2026.07.13.2")
    args = parser.parse_args()
    document = convert(args.source, args.version)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
