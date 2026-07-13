"""Package entrypoint."""

from __future__ import annotations

import sys

from .app import run
from .infrastructure.catalog import CatalogRepository
from .infrastructure.yaz_engine import ZoomSessionEngine


def self_test() -> int:
    """Verify packaged native and data dependencies without opening the GUI."""
    engine = ZoomSessionEngine()
    if not engine.available:
        print("FAIL: embedded YAZ could not be loaded", file=sys.stderr)
        return 2
    catalog = CatalogRepository().load_upstream()
    if not catalog.active_servers:
        print("FAIL: bundled catalog has no active servers", file=sys.stderr)
        return 3
    print(
        f"OK: YAZ {engine.version}; catalog {catalog.catalog_version}; "
        f"{len(catalog.active_servers)} active servers"
    )
    engine.close()
    return 0


def main() -> int:
    """Run the desktop application."""
    if "--self-test" in sys.argv[1:]:
        return self_test()
    return run(smoke_test="--smoke-test" in sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
