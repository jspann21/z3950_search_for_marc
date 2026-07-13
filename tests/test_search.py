from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from z3950_search_for_marc.domain.models import (
    BackendFailure,
    MarcRecord,
    QueryType,
    SearchRequest,
    SearchSession,
    ServerResult,
    ServerStatus,
)
from z3950_search_for_marc.infrastructure.yaz_engine import CancellationToken
from z3950_search_for_marc.marc import parse_marc
from z3950_search_for_marc.models import RecordReference
from z3950_search_for_marc.search import SearchCoordinator

from .helpers import marc_bytes, server


class FakeEngine:
    available = True
    version = "test"

    def __init__(self) -> None:
        self.closed = False
        self.canceled: UUID | None = None

    def search_many(
        self, session_id, request, servers, concurrency, cancellation
    ) -> Iterator[ServerResult]:
        for item in servers:
            if cancellation.is_canceled:
                return
            yield ServerResult(
                session_id,
                item,
                ServerStatus.SUCCESS,
                2,
                parse_marc(marc_bytes()),
            )

    def fetch_record(
        self,
        session_id: UUID,
        server_id: str,
        position: int,
        cancellation: CancellationToken,
    ) -> MarcRecord | BackendFailure:
        return parse_marc(marc_bytes(f"Record {position}"))

    def close(self) -> None:
        self.closed = True

    def cancel(self, session_id: UUID) -> None:
        self.canceled = session_id


def _session() -> SearchSession:
    return SearchSession(SearchRequest(QueryType.ISBN, "9780306406157", frozenset({"USA"}), 5))


def test_coordinator_streams_results_and_fetches_retained_record(qtbot) -> None:
    engine = FakeEngine()
    coordinator = SearchCoordinator(engine)
    results: list[ServerResult] = []
    records: list[object] = []
    finished: list[UUID] = []
    coordinator.server_changed.connect(results.append)
    coordinator.record_fetched.connect(lambda _reference, record: records.append(record))
    coordinator.search_finished.connect(finished.append)
    session = _session()

    coordinator.start(session, [server()], 12)
    qtbot.waitUntil(lambda: bool(finished), timeout=2000)
    coordinator.fetch_record(RecordReference(session.id, server(), 2))
    qtbot.waitUntil(lambda: bool(records), timeout=2000)

    assert any(result.status == ServerStatus.SUCCESS for result in results)
    assert isinstance(records[0], MarcRecord)
    coordinator.shutdown()
    assert engine.closed
