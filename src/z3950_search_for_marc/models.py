"""Compatibility exports for the v2 domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from pymarc import Record

from .domain.models import *  # noqa: F403
from .domain.models import (
    BackendFailure,
    MarcRecord,
    SearchSession,
    ServerDefinition,
    ServerResult,
)

ServerConfig = ServerDefinition
ServerSearchResult = ServerResult
SearchResult = ServerResult
BackendResult = ServerResult | BackendFailure


@dataclass(frozen=True, slots=True)
class BackendResponse:
    """Compatibility response used by injected test backends."""

    stdout_text: str
    cleaned_data: str
    number_of_hits: int
    raw_bytes: bytes = b""


@dataclass(frozen=True, slots=True)
class RecordReference:
    session_id: UUID
    server: ServerDefinition
    position: int

    @property
    def cache_key(self) -> tuple[str, int]:
        return self.server.id, self.position


@dataclass(slots=True)
class SearchState:
    """UI state retained here while the view-model layer owns transitions."""

    session: SearchSession | None = None
    selected_result: ServerResult | None = None
    current_position: int = 0
    records: dict[tuple[str, int], MarcRecord] = field(default_factory=dict)
    fetch_in_progress: bool = False

    @property
    def total_records(self) -> int:
        return self.selected_result.number_of_hits if self.selected_result else 0

    @property
    def current_record(self) -> Record | None:
        wrapped = self.current_marc_record
        return wrapped.parsed if wrapped else None

    @property
    def current_marc_record(self) -> MarcRecord | None:
        if not self.selected_result or self.current_position < 1:
            return None
        return self.records.get((self.selected_result.server.id, self.current_position))

    def reset(self, session: SearchSession | None = None) -> None:
        self.session = session
        self.selected_result = None
        self.current_position = 0
        self.records.clear()
        self.fetch_in_progress = False

    def select(self, result: ServerResult, record: MarcRecord | None) -> None:
        self.selected_result = result
        self.current_position = 1
        if record is not None:
            self.records[(result.server.id, 1)] = record

    def reset_results(self) -> None:
        self.reset(self.session)
