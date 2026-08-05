"""Immutable domain types shared by the application and infrastructure layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pymarc import Record


class QueryType(StrEnum):
    ISBN = "isbn"
    TITLE_AUTHOR = "title_author"


class LocationGroup(StrEnum):
    USA = "USA"
    WORLDWIDE = "Worldwide"


class CatalogStatus(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class ServerStatus(StrEnum):
    PENDING = "Pending"
    SEARCHING = "Searching"
    SUCCESS = "Available"
    EMPTY = "No results"
    FAILED = "Failed"
    TIMED_OUT = "Timed out"
    CANCELED = "Canceled"


class FailureKind(StrEnum):
    ENGINE_UNAVAILABLE = "engine_unavailable"
    DNS = "dns"
    CONNECTION = "connection"
    INITIALIZATION = "initialization"
    TIMEOUT = "timeout"
    DIAGNOSTIC = "diagnostic"
    MALFORMED_RESPONSE = "malformed_response"
    CANCELED = "canceled"
    INTERNAL = "internal"


class Theme(StrEnum):
    """The supported application appearance modes."""

    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True, slots=True)
class ServerDefinition:
    id: str
    name: str
    host: str
    port: int
    database: str
    country_code: str = "ZZ"
    location_group: LocationGroup = LocationGroup.WORLDWIDE
    record_syntax: str = "USMARC"
    query_charset: str = "utf-8"
    marc_charset: str = "auto"
    priority: int = 500
    status: CatalogStatus = CatalogStatus.ACTIVE
    last_verified_at: datetime | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"

    @property
    def key(self) -> str:
        return self.id

    @property
    def location(self) -> str:
        return self.location_group.value

    @property
    def summary(self) -> str:
        return f"{self.name} ({self.endpoint})"


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    schema_version: int
    catalog_version: str
    published_at: datetime
    servers: tuple[ServerDefinition, ...]

    @property
    def active_servers(self) -> tuple[ServerDefinition, ...]:
        return tuple(server for server in self.servers if server.status == CatalogStatus.ACTIVE)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query_type: QueryType
    query: str | tuple[str, str]
    locations: frozenset[str]
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class SearchSession:
    request: SearchRequest
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class MarcRecord:
    parsed: Record
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class BackendFailure:
    kind: FailureKind
    message: str


@dataclass(frozen=True, slots=True)
class ServerResult:
    session_id: UUID
    server: ServerDefinition
    status: ServerStatus
    number_of_hits: int = 0
    record: MarcRecord | None = None
    failure: BackendFailure | None = None

    @property
    def summary(self) -> str:
        return self.server.summary

    @property
    def raw_data(self) -> str:
        """Compatibility display for integrations that previously consumed YAZ text."""
        return str(self.record.parsed) if self.record else ""

    @property
    def message(self) -> str:
        return self.failure.message if self.failure else ""


@dataclass(frozen=True, slots=True)
class SearchProgress:
    session_id: UUID
    completed: int
    total: int

    @property
    def percentage(self) -> int:
        return int(self.completed * 100 / self.total) if self.total else 100


def _downloads_directory() -> str:
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())


@dataclass(frozen=True, slots=True)
class AppSettings:
    max_concurrent_queries: int = 12
    server_timeout_seconds: int = 5
    default_save_directory: str = field(default_factory=_downloads_directory)
    trim_records: bool = True
    theme: Theme = Theme.LIGHT
    automatic_catalog_updates: bool = True
    check_for_app_updates_at_startup: bool = True
    disabled_server_ids: tuple[str, ...] = ()
    last_catalog_check_at: datetime | None = None

    def normalized(self) -> AppSettings:
        return AppSettings(
            max_concurrent_queries=max(1, min(32, int(self.max_concurrent_queries))),
            server_timeout_seconds=max(1, min(60, int(self.server_timeout_seconds))),
            default_save_directory=self.default_save_directory.strip() or _downloads_directory(),
            trim_records=bool(self.trim_records),
            theme=Theme(self.theme),
            automatic_catalog_updates=bool(self.automatic_catalog_updates),
            check_for_app_updates_at_startup=bool(self.check_for_app_updates_at_startup),
            disabled_server_ids=tuple(sorted(set(self.disabled_server_ids))),
            last_catalog_check_at=(
                self.last_catalog_check_at.astimezone(UTC)
                if self.last_catalog_check_at is not None
                else None
            ),
        )
