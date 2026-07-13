"""Typed domain models shared by the application layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pymarc import Record


class QueryType(StrEnum):
    """Supported Z39.50 query forms."""

    ISBN = "isbn"
    TITLE_AUTHOR = "title_author"


class ServerStatus(StrEnum):
    """Lifecycle state of one server in a search session."""

    PENDING = "Pending"
    SEARCHING = "Searching"
    SUCCESS = "Available"
    EMPTY = "No results"
    FAILED = "Failed"
    TIMED_OUT = "Timed out"
    CANCELED = "Canceled"


class FailureKind(StrEnum):
    """Stable categories for backend failures."""

    MISSING_EXECUTABLE = "missing_executable"
    TIMEOUT = "timeout"
    CANCELED = "canceled"
    PROCESS = "process"
    MALFORMED_RESPONSE = "malformed_response"


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
        return f"{self.host}:{self.port}/{self.database}"

    @property
    def key(self) -> str:
        return self.endpoint.casefold()

    @property
    def summary(self) -> str:
        return f"{self.name} ({self.endpoint})"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Validated inputs for a search."""

    query_type: QueryType
    query: str | tuple[str, str]
    locations: frozenset[str]
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class SearchSession:
    """Identity and request data for one search run."""

    request: SearchRequest
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class SearchProgress:
    """Completion state for a multi-server search."""

    session_id: UUID
    completed: int
    total: int

    @property
    def percentage(self) -> int:
        return int((self.completed / self.total) * 100) if self.total else 100


@dataclass(frozen=True, slots=True)
class BackendResponse:
    """Successful response from a search backend."""

    stdout_text: str
    cleaned_data: str
    number_of_hits: int


@dataclass(frozen=True, slots=True)
class BackendFailure:
    """Typed backend failure suitable for UI presentation."""

    kind: FailureKind
    message: str


BackendResult = BackendResponse | BackendFailure


@dataclass(frozen=True, slots=True)
class ServerSearchResult:
    """Current state of one server in a search session."""

    session_id: UUID
    server: ServerConfig
    status: ServerStatus
    number_of_hits: int = 0
    raw_data: str = ""
    message: str = ""

    @property
    def summary(self) -> str:
        return self.server.summary


# Backward-compatible name used by older integrations and tests.
SearchResult = ServerSearchResult


@dataclass(frozen=True, slots=True)
class RecordReference:
    """Address of a record in a server result set."""

    session_id: UUID
    server: ServerConfig
    position: int

    @property
    def cache_key(self) -> tuple[str, int]:
        return self.server.key, self.position


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
    """UI-facing state and record cache for the active session."""

    session: SearchSession | None = None
    selected_result: ServerSearchResult | None = None
    current_position: int = 0
    records: dict[tuple[str, int], Record] = field(default_factory=dict)
    fetch_in_progress: bool = False

    @property
    def total_records(self) -> int:
        return self.selected_result.number_of_hits if self.selected_result else 0

    @property
    def current_record(self) -> Record | None:
        if not self.selected_result or self.current_position < 1:
            return None
        return self.records.get((self.selected_result.server.key, self.current_position))

    def reset(self, session: SearchSession | None = None) -> None:
        self.session = session
        self.selected_result = None
        self.current_position = 0
        self.records.clear()
        self.fetch_in_progress = False

    def select(self, result: ServerSearchResult, record: Record | None) -> None:
        self.selected_result = result
        self.current_position = 1
        if record is not None:
            self.records[(result.server.key, 1)] = record

    # Compatibility for the previous application state API.
    def reset_results(self) -> None:
        self.reset(self.session)
