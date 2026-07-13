"""Package entrypoint."""

from __future__ import annotations

import sys

from .app import run


def main() -> int:
    """Run the desktop application."""
    return run(smoke_test="--smoke-test" in sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
