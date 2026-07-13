from __future__ import annotations

import tomllib
from pathlib import Path

from z3950_search_for_marc import __version__


def test_release_version_is_consistent() -> None:
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as stream:
        project_version = tomllib.load(stream)["project"]["version"]

    assert __version__ == project_version
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    assert f"Z3950MarcSearch-{project_version}-x64.msi" in readme
