"""Typed models used throughout the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pymarc import Record


class QueryType(StrEnum):
    """Supported Z39.50 query types."""

    ISBN = "isbn"
    TITLE_AUTHOR = "title_author"


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Validated Z39.50 server configuration."""

    name: str
    host: str
    port: int
    database: str
    location: str

    @property
    def endpoint(self) -> str:
        """Return the yaz-client endpoint string."""
        return f"{self.host}:{self.port}/{self.database}"

    @property
    def summary(self) -> str:
        """Return the human-readable search result summary."""
        return f"{self.name} ({self.endpoint})"


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A result row representing one responding server."""

    server: ServerConfig
    number_of_hits: int
    raw_data: str

    @property
    def summary(self) -> str:
        """Return the list item text prefix."""
        return self.server.summary


def _default_save_directory() -> str:
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.exists() else Path.home())


@dataclass(slots=True)
class AppSettings:
    """Persisted application settings."""

    yaz_executable: str = "yaz-client"
    server_catalog_path: str = ""
    max_concurrent_queries: int = 12
    server_timeout_seconds: int = 5
    default_save_directory: str = field(default_factory=_default_save_directory)
    trim_records: bool = True

    def normalized(self) -> AppSettings:
        """Return a validated copy with bounded values."""
        return AppSettings(
            yaz_executable=self.yaz_executable.strip() or "yaz-client",
            server_catalog_path=self.server_catalog_path.strip(),
            max_concurrent_queries=max(1, min(32, int(self.max_concurrent_queries))),
            server_timeout_seconds=max(1, min(60, int(self.server_timeout_seconds))),
            default_save_directory=self.default_save_directory.strip() or _default_save_directory(),
            trim_records=bool(self.trim_records),
        )


@dataclass(slots=True)
class SearchState:
    """Mutable state for the active search session."""

    current_marc_records: list[Record] = field(default_factory=list)
    current_record_index: int = 0
    total_records: int = 0
    current_server_info: ServerConfig | None = None
    current_query_type: QueryType | None = None
    current_query: str | tuple[str, str] | None = None

    def reset_results(self) -> None:
        """Clear the current result state."""
        self.current_marc_records.clear()
        self.current_record_index = 0
        self.total_records = 0
        self.current_server_info = None
