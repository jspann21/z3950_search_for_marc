"""Helpers for accessing bundled resource files."""

from __future__ import annotations

from pathlib import Path


def package_root() -> Path:
    """Return the package root directory."""
    return Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    """Return the absolute path to a packaged resource."""
    return package_root() / "resources" / name
