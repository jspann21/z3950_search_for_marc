from __future__ import annotations

import threading
import time
from uuid import UUID

from z3950_search_for_marc.backend import CancellationToken
from z3950_search_for_marc.models import (
    BackendFailure,
    BackendResponse,
    FailureKind,
    QueryType,
    SearchProgress,
    SearchRequest,
    SearchSession,
    ServerConfig,
    ServerSearchResult,
    ServerStatus,
)
from z3950_search_for_marc.search import SearchCoordinator


class FakeBackend:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def search_server(self, request, server, position, cancellation):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self.lock:
            self.active -= 1
        if cancellation.is_canceled:
            return BackendFailure(FailureKind.CANCELED, "Search canceled.")
        if server.name == "Empty":
            return BackendResponse("Number of hits: 0", "", 0)
        if server.name == "Broken":
            return BackendFailure(FailureKind.PROCESS, "Connection failed")
        return BackendResponse("Number of hits: 2", f"245 10 $a Record {position}", 2)

    def cancel(self, cancellation: CancellationToken) -> None:
        cancellation.cancel()


def _session() -> SearchSession:
    return SearchSession(SearchRequest(QueryType.ISBN, "9780306406157", frozenset({"USA"}), 5))


def test_coordinator_reports_mixed_results_and_bounded_progress(qtbot) -> None:
    backend = FakeBackend()
    coordinator = SearchCoordinator(backend)
    results: list[ServerSearchResult] = []
    progress: list[SearchProgress] = []
    finished: list[UUID] = []
    coordinator.server_changed.connect(results.append)
    coordinator.progress_changed.connect(progress.append)
    coordinator.search_finished.connect(finished.append)
    servers = [
        ServerConfig("Good", "one.example", 210, "db", "USA"),
        ServerConfig("Empty", "two.example", 210, "db", "USA"),
        ServerConfig("Broken", "three.example", 210, "db", "USA"),
    ]

    session = _session()
    coordinator.start(session, servers, max_concurrent=2)
    qtbot.waitUntil(lambda: bool(finished), timeout=3000)

    final_statuses = {result.server.name: result.status for result in results}
    assert final_statuses == {
        "Good": ServerStatus.SUCCESS,
        "Empty": ServerStatus.EMPTY,
        "Broken": ServerStatus.FAILED,
    }
    assert progress[-1].percentage == 100
    assert backend.max_active <= 2
    coordinator.shutdown()


class SlowBackend(FakeBackend):
    def search_server(self, request, server, position, cancellation):
        time.sleep(0.08 if server.name == "Slow" else 0.005)
        return BackendResponse("Number of hits: 1", "245 10 $a Result", 1)


def test_coordinator_suppresses_late_results_from_replaced_session(qtbot) -> None:
    coordinator = SearchCoordinator(SlowBackend())
    received: list[ServerSearchResult] = []
    coordinator.server_changed.connect(received.append)
    first = _session()
    second = _session()

    coordinator.start(first, [ServerConfig("Slow", "slow.example", 210, "db", "USA")], 1)
    qtbot.waitUntil(
        lambda: any(result.status == ServerStatus.SEARCHING for result in received),
        timeout=1000,
    )
    coordinator.start(second, [ServerConfig("Fast", "fast.example", 210, "db", "USA")], 2)
    received.clear()
    qtbot.waitUntil(
        lambda: any(result.status == ServerStatus.SUCCESS for result in received),
        timeout=2000,
    )
    qtbot.wait(100)

    assert received
    assert all(result.session_id == second.id for result in received)
    coordinator.shutdown()
