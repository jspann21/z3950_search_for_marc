"""Package entrypoint."""

from .app import run


def main() -> int:
    """Run the desktop application."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
