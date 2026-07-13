"""Qt-based search orchestration over a single bounded thread pool."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

from .backend import CancellationToken, SearchBackend
from .models import (
    BackendFailure,
    BackendResponse,
    FailureKind,
    RecordReference,
    SearchProgress,
    SearchSession,
    ServerConfig,
    ServerSearchResult,
    ServerStatus,
)


def _status_for_failure(kind: FailureKind) -> ServerStatus:
    if kind == FailureKind.TIMEOUT:
        return ServerStatus.TIMED_OUT
    if kind == FailureKind.CANCELED:
        return ServerStatus.CANCELED
    return ServerStatus.FAILED


@dataclass(slots=True)
class _SessionWork:
    session: SearchSession
    cancellation: CancellationToken
    total: int
    completed: int = 0


class SearchTaskSignals(QObject):
    status_changed = pyqtSignal(object)
    completed = pyqtSignal(object)


class SearchTask(QRunnable):
    """Query one server for the initial record."""

    def __init__(
        self,
        backend: SearchBackend,
        work: _SessionWork,
        server: ServerConfig,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.work = work
        self.server = server
        self.signals = SearchTaskSignals()

    @pyqtSlot()
    def run(self) -> None:
        session = self.work.session
        token = self.work.cancellation
        if token.is_canceled:
            result = ServerSearchResult(session.id, self.server, ServerStatus.CANCELED)
            self.signals.status_changed.emit(result)
            self.signals.completed.emit(session.id)
            return

        self.signals.status_changed.emit(
            ServerSearchResult(session.id, self.server, ServerStatus.SEARCHING)
        )
        backend_result = self.backend.search_server(session.request, self.server, 1, token)
        if isinstance(backend_result, BackendResponse):
            status = (
                ServerStatus.SUCCESS if backend_result.number_of_hits > 0 else ServerStatus.EMPTY
            )
            result = ServerSearchResult(
                session.id,
                self.server,
                status,
                backend_result.number_of_hits,
                backend_result.cleaned_data,
            )
        else:
            result = ServerSearchResult(
                session.id,
                self.server,
                _status_for_failure(backend_result.kind),
                message=backend_result.message,
            )
        self.signals.status_changed.emit(result)
        self.signals.completed.emit(session.id)


class RecordTaskSignals(QObject):
    completed = pyqtSignal(object, object)


class RecordTask(QRunnable):
    """Fetch one record position for an existing search session."""

    def __init__(
        self,
        backend: SearchBackend,
        work: _SessionWork,
        reference: RecordReference,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.work = work
        self.reference = reference
        self.signals = RecordTaskSignals()

    @pyqtSlot()
    def run(self) -> None:
        result = self.backend.search_server(
            self.work.session.request,
            self.reference.server,
            self.reference.position,
            self.work.cancellation,
        )
        self.signals.completed.emit(self.reference, result)


class SearchCoordinator(QObject):
    """Coordinate search tasks, cancellation, progress, and stale-session isolation."""

    server_changed = pyqtSignal(object)
    progress_changed = pyqtSignal(object)
    search_finished = pyqtSignal(object)
    record_fetched = pyqtSignal(object, object)

    def __init__(self, backend: SearchBackend, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.pool = QThreadPool(self)
        self._work: _SessionWork | None = None
        self._mutex = QMutex()

    @property
    def active_session_id(self) -> UUID | None:
        return self._work.session.id if self._work else None

    def start(
        self,
        session: SearchSession,
        servers: list[ServerConfig],
        max_concurrent: int,
    ) -> None:
        self.cancel()
        self.pool.setMaxThreadCount(max_concurrent)
        work = _SessionWork(session, CancellationToken(), len(servers))
        self._work = work
        for server in servers:
            self.server_changed.emit(ServerSearchResult(session.id, server, ServerStatus.PENDING))
        if not servers:
            self.progress_changed.emit(SearchProgress(session.id, 0, 0))
            self.search_finished.emit(session.id)
            return
        for server in servers:
            task = SearchTask(self.backend, work, server)
            task.signals.status_changed.connect(self._forward_status)
            task.signals.completed.connect(self._on_task_completed)
            self.pool.start(task)

    def fetch_record(self, reference: RecordReference) -> None:
        work = self._work
        if work is None or work.session.id != reference.session_id:
            return
        task = RecordTask(self.backend, work, reference)
        task.signals.completed.connect(self._on_record_completed)
        self.pool.start(task)

    def cancel(self) -> None:
        work = self._work
        if work is not None:
            self.backend.cancel(work.cancellation)
        self.pool.clear()

    def shutdown(self, timeout_ms: int = 2500) -> None:
        self.cancel()
        self.pool.waitForDone(timeout_ms)
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()

    @pyqtSlot(object)
    def _forward_status(self, result: ServerSearchResult) -> None:
        if self._work is None or result.session_id != self._work.session.id:
            return
        self.server_changed.emit(result)

    @pyqtSlot(object)
    def _on_task_completed(self, session_id: UUID) -> None:
        work = self._work
        if work is None or work.session.id != session_id:
            return
        with QMutexLocker(self._mutex):
            work.completed += 1
            progress = SearchProgress(session_id, work.completed, work.total)
        self.progress_changed.emit(progress)
        if progress.completed == progress.total:
            self.search_finished.emit(session_id)

    @pyqtSlot(object, object)
    def _on_record_completed(self, reference: RecordReference, result: object) -> None:
        if self._work is None or reference.session_id != self._work.session.id:
            return
        if isinstance(result, (BackendResponse, BackendFailure)):
            self.record_fetched.emit(reference, result)
