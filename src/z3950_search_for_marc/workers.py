"""Qt worker objects for querying Z39.50 servers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

from .marc import extract_marc_record
from .models import QueryType, SearchResult, ServerConfig
from .yaz import YAZClient, YAZQueryError, build_search_command


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    servers: list[ServerConfig]
    query_type: QueryType
    query: str | tuple[str, str]
    start: int = 1
    timeout_seconds: int = 5
    max_threads: int = 12


@dataclass(frozen=True, slots=True)
class NextRecordWorkerConfig:
    server_info: ServerConfig
    query_type: QueryType
    query: str | tuple[str, str]
    start: int
    timeout_seconds: int
    trim_records: bool


class BaseWorker(QObject):
    finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(
        self,
        *,
        query_type: QueryType,
        query: str | tuple[str, str],
        start: int,
        timeout_seconds: int,
    ):
        super().__init__()
        self.query_type = query_type
        self.query = query
        self.start = start
        self.timeout_seconds = timeout_seconds
        self._cancel_requested = False

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def cancel(self) -> None:
        self._cancel_requested = True

    def command_preview(self) -> str:
        """Return a human-readable command preview for logs."""
        return (build_search_command(self.query_type, self.query) + f"show {self.start}").replace(
            "\n", " "
        )


class ServerQueryRunnable(QRunnable):
    """Execute one server query inside the pool."""

    def __init__(self, worker: Worker, server: ServerConfig):
        super().__init__()
        self.worker = worker
        self.server = server

    @pyqtSlot()
    def run(self) -> None:
        if self.worker.cancel_requested:
            self.worker.mark_completed()
            return

        preview = self.worker.command_preview()
        self.worker.log_message.emit(
            f"Connecting to {self.server.name}: {self.server.endpoint} with {preview}"
        )

        try:
            response = self.worker.yaz_client.query(
                self.server,
                query_type=self.worker.query_type,
                query=self.worker.query,
                start=self.worker.start,
                timeout_seconds=self.worker.timeout_seconds,
            )
            if self.worker.cancel_requested:
                return
            if response.number_of_hits > 0:
                self.worker.result_found.emit(
                    SearchResult(
                        server=self.server,
                        number_of_hits=response.number_of_hits,
                        raw_data=response.cleaned_data,
                    )
                )
            else:
                self.worker.log_message.emit(f"No records found in {self.server.name}.")
        except YAZQueryError as exc:
            if not self.worker.cancel_requested:
                self.worker.log_message.emit(str(exc))
        finally:
            self.worker.mark_completed()


class Worker(BaseWorker):
    """Search multiple servers concurrently."""

    progress = pyqtSignal(int)
    result_found = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, config: WorkerConfig, yaz_client_factory: Callable[[], YAZClient]):
        super().__init__(
            query_type=config.query_type,
            query=config.query,
            start=config.start,
            timeout_seconds=config.timeout_seconds,
        )
        self.servers = config.servers
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(config.max_threads)
        self.completed_servers = 0
        self.mutex = QMutex()
        self.yaz_client = yaz_client_factory()

    def run(self) -> None:
        try:
            if not self.servers:
                self.finished.emit()
                return

            self.log_message.emit(f"Total servers to query: {len(self.servers)}")
            for server in self.servers:
                if self.cancel_requested:
                    break
                self.threadpool.start(ServerQueryRunnable(self, server))
            self.threadpool.waitForDone()
            if not self.cancel_requested:
                self.progress.emit(100)
        except Exception as exc:  # pragma: no cover - defensive Qt worker guard
            self.error.emit(f"Worker encountered an exception: {exc}")
        finally:
            self.finished.emit()

    def mark_completed(self) -> None:
        with QMutexLocker(self.mutex):
            self.completed_servers += 1
            progress = (
                int((self.completed_servers / len(self.servers)) * 100)
                if self.servers
                else 100
            )
        self.progress.emit(progress)


class NextRecordWorker(QObject):
    """Fetch the next MARC record for the selected server."""

    record_fetched = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, config: NextRecordWorkerConfig, yaz_client_factory: Callable[[], YAZClient]):
        super().__init__()
        self.server_info = config.server_info
        self.query_type = config.query_type
        self.query = config.query
        self.start = config.start
        self.timeout_seconds = config.timeout_seconds
        self.trim_records = config.trim_records
        self._cancel_requested = False
        self._yaz_client_factory = yaz_client_factory

    def cancel(self) -> None:
        self._cancel_requested = True

    @pyqtSlot()
    def run(self) -> None:
        if self._cancel_requested:
            self.finished.emit()
            return

        preview = (
            build_search_command(self.query_type, self.query) + f"show {self.start}"
        ).replace("\n", " ")
        self.log_message.emit(
            f"Connecting to {self.server_info.name}: {self.server_info.endpoint} with {preview}"
        )

        try:
            response = self._yaz_client_factory().query(
                self.server_info,
                query_type=self.query_type,
                query=self.query,
                start=self.start,
                timeout_seconds=self.timeout_seconds,
            )
            if self._cancel_requested:
                self.finished.emit()
                return

            record = extract_marc_record(
                response.cleaned_data,
                trim_records=self.trim_records,
                log_callback=self.log_message.emit,
            )
            if record is None:
                self.error.emit("Failed to extract MARC record.")
            else:
                self.record_fetched.emit(record)
        except YAZQueryError as exc:
            if not self._cancel_requested:
                self.error.emit(str(exc))
        finally:
            self.finished.emit()
