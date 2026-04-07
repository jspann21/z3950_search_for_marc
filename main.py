"""Compatibility launcher for the packaged application."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Run the packaged entrypoint from a source checkout."""
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from z3950_search_for_marc.__main__ import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
