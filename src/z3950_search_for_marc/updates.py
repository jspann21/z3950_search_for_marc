"""Read-only application update checks against published GitHub releases."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from . import __version__

LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/jspann21/z3950_search_for_marc/releases/latest"
)
RELEASE_PAGE_PREFIX = "https://github.com/jspann21/z3950_search_for_marc/releases/"


@dataclass(frozen=True, slots=True)
class AvailableUpdate:
    version: str
    page_url: str


def _version_key(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"[vV]?(\d+(?:\.\d+)*)", value.strip())
    if match is None:
        raise ValueError(f"GitHub returned an invalid release version: {value!r}.")
    return tuple(int(part) for part in match.group(1).split("."))


def _is_newer(candidate: str, current: str) -> bool:
    candidate_parts = _version_key(candidate)
    current_parts = _version_key(current)
    width = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (width - len(candidate_parts)) > current_parts + (0,) * (
        width - len(current_parts)
    )


def check_for_application_update(
    *, current_version: str = __version__, timeout_seconds: float = 10
) -> AvailableUpdate | None:
    """Return the latest release when it is newer, without downloading any asset."""
    request = Request(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Z3950MarcSearch/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload: Any = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an invalid latest-release response.")
    tag_name = payload.get("tag_name")
    page_url = payload.get("html_url")
    if not isinstance(tag_name, str) or not isinstance(page_url, str):
        raise ValueError("GitHub's latest release is missing its version or web page.")
    if not page_url.startswith(RELEASE_PAGE_PREFIX):
        raise ValueError("GitHub returned an unexpected release page address.")
    if not _is_newer(tag_name, current_version):
        return None
    return AvailableUpdate(version=tag_name.removeprefix("v").removeprefix("V"), page_url=page_url)
