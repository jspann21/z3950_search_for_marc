"""Single-threaded Qt adapter around the asynchronous native ZOOM engine."""

from __future__ import annotations

from queue import Empty, SimpleQueue
from uuid import UUID

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot

from .domain.models import (
    SearchProgress,
    SearchSession,
    ServerDefinition,
    ServerResult,
    ServerStatus,
)
from .infrastructure.yaz_engine import CancellationToken, SessionEngine, ZoomSessionEngine
from .models import RecordReference


class _EngineWorker(QObject):
    server_changed = Signal(object)
    progress_changed = Signal(object)
    search_finished = Signal(object)
    record_fetched = Signal(object, object)

    def __init__(self, engine: SessionEngine) -> None:
        super().__init__()
        self.engine = engine
        self._cancellation = CancellationToken()
        self._active_session_id: UUID | None = None
        self._fetch_queue: SimpleQueue[RecordReference] = SimpleQueue()

    @Slot(object, object, int)
    def search(
        self, session: SearchSession, servers: tuple[ServerDefinition, ...], concurrency: int
    ) -> None:
        self.cancel_now()
        self._cancellation = CancellationToken()
        self._active_session_id = session.id
        completed = 0
        for result in self.engine.search_many(
            session.id, session.request, servers, concurrency, self._cancellation
        ):
            if self._active_session_id != session.id:
                continue
            self.server_changed.emit(result)
            completed += 1
            self.progress_changed.emit(SearchProgress(session.id, completed, len(servers)))
            # Search owns the native handles for its whole run. Service navigation between
            # completed targets so a 200-server search does not block Next/Previous for minutes.
            self.drain_fetches()
        if self._active_session_id == session.id:
            self.drain_fetches()
            self.search_finished.emit(session.id)

    def enqueue_fetch(self, reference: RecordReference) -> None:
        """Accept a navigation request safely from the UI thread."""
        self._fetch_queue.put(reference)

    @Slot()
    def drain_fetches(self) -> None:
        while True:
            try:
                reference = self._fetch_queue.get_nowait()
            except Empty:
                return
            if reference.session_id != self._active_session_id:
                continue
            result = self.engine.fetch_record(
                reference.session_id,
                reference.server.id,
                reference.position,
                self._cancellation,
            )
            self.record_fetched.emit(reference, result)

    def cancel_now(self) -> None:
        self._cancellation.cancel()
        if self._active_session_id is not None:
            self.engine.cancel(self._active_session_id)
        self._active_session_id = None

    @Slot()
    def close(self) -> None:
        self.cancel_now()
        self.engine.close()


class SearchCoordinator(QObject):
    server_changed = Signal(object)
    progress_changed = Signal(object)
    search_finished = Signal(object)
    record_fetched = Signal(object, object)
    _search_requested = Signal(object, object, int)
    _fetch_requested = Signal()

    def __init__(self, engine: SessionEngine | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine or ZoomSessionEngine()
        self.worker_thread = QThread(self)
        self.worker = _EngineWorker(self.engine)
        self.worker.moveToThread(self.worker_thread)
        self._search_requested.connect(self.worker.search)
        self._fetch_requested.connect(self.worker.drain_fetches)
        self.worker.server_changed.connect(self.server_changed)
        self.worker.progress_changed.connect(self.progress_changed)
        self.worker.search_finished.connect(self.search_finished)
        self.worker.record_fetched.connect(self.record_fetched)
        self.worker_thread.start()
        self._active_session_id: UUID | None = None

    @property
    def active_session_id(self) -> UUID | None:
        return self._active_session_id

    def start(
        self,
        session: SearchSession,
        servers: list[ServerDefinition],
        max_concurrent: int,
    ) -> None:
        self.cancel()
        self._active_session_id = session.id
        for server in servers:
            self.server_changed.emit(ServerResult(session.id, server, ServerStatus.PENDING))
        if not servers:
            self.progress_changed.emit(SearchProgress(session.id, 0, 0))
            self.search_finished.emit(session.id)
            return
        self._search_requested.emit(session, tuple(servers), max_concurrent)

    def fetch_record(self, reference: RecordReference) -> None:
        if reference.session_id == self._active_session_id:
            self.worker.enqueue_fetch(reference)
            self._fetch_requested.emit()

    def cancel(self) -> None:
        self.worker.cancel_now()
        self._active_session_id = None

    def shutdown(self, timeout_ms: int = 7000) -> None:
        self.cancel()
        if self.worker_thread.isRunning():
            QMetaObject.invokeMethod(
                self.worker,
                "close",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
        self.worker_thread.quit()
        self.worker_thread.wait(timeout_ms)


# Compatibility aliases retained for imports from the 1.0 development branch.
SearchTask = _EngineWorker
RecordTask = _EngineWorker
