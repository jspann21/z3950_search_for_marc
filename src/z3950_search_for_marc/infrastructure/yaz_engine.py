"""Direct, session-aware adapter for the YAZ ZOOM C API."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, cast
from uuid import UUID

from ..domain.models import (
    BackendFailure,
    FailureKind,
    MarcRecord,
    QueryType,
    SearchRequest,
    ServerDefinition,
    ServerResult,
    ServerStatus,
)
from ..marc import MarcParseError, parse_marc
from ..resources import package_root

ZOOM_EVENT_TIMEOUT = 4
ZOOM_EVENT_RECV_RECORD = 8
ZOOM_EVENT_RECV_SEARCH = 9
ZOOM_EVENT_END = 10
_DLL_DIRECTORY: object | None = None


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_canceled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()


class SessionEngine(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def version(self) -> str: ...

    def search_many(
        self,
        session_id: UUID,
        request: SearchRequest,
        servers: tuple[ServerDefinition, ...],
        concurrency: int,
        cancellation: CancellationToken,
    ) -> Iterator[ServerResult]: ...

    def fetch_record(
        self,
        session_id: UUID,
        server_id: str,
        position: int,
        cancellation: CancellationToken,
    ) -> MarcRecord | BackendFailure: ...

    def cancel(self, session_id: UUID) -> None: ...

    def close(self) -> None: ...


class EngineUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class _Context:
    server: ServerDefinition
    options: Any
    connection: Any
    query: Any
    resultset: Any
    state: str = "searching"


class ZoomSessionEngine:
    """Own all native ZOOM objects on one worker thread."""

    def __init__(self, native_module: Any | None = None) -> None:
        self._native = native_module
        self._load_error: Exception | None = None
        if self._native is None:
            try:
                global _DLL_DIRECTORY
                native_directory = package_root() / "native"
                add_dll_directory = getattr(os, "add_dll_directory", None)
                if (
                    os.name == "nt"
                    and native_directory.is_dir()
                    and _DLL_DIRECTORY is None
                    and add_dll_directory is not None
                ):
                    _DLL_DIRECTORY = add_dll_directory(str(native_directory))
                self._native = import_module("z3950_search_for_marc._yaz_native")
            except (ImportError, OSError) as exc:
                self._load_error = exc
        self._session_id: UUID | None = None
        self._retained: dict[str, _Context] = {}

    @property
    def available(self) -> bool:
        return self._native is not None

    @property
    def version(self) -> str:
        if self._native is None:
            return "unavailable"
        value = self._native.ffi.new("char[20]")
        sha1 = self._native.ffi.new("char[41]")
        self._native.lib.yaz_version(value, sha1)
        return self._native.ffi.string(value).decode("ascii", errors="replace") or "unknown"

    def search_many(
        self,
        session_id: UUID,
        request: SearchRequest,
        servers: tuple[ServerDefinition, ...],
        concurrency: int,
        cancellation: CancellationToken,
    ) -> Iterator[ServerResult]:
        if self._native is None:
            detail = f": {self._load_error}" if self._load_error else ""
            failure = BackendFailure(
                FailureKind.ENGINE_UNAVAILABLE,
                f"Embedded YAZ engine is unavailable{detail}",
            )
            for server in servers:
                yield ServerResult(session_id, server, ServerStatus.FAILED, failure=failure)
            return

        self._close_retained()
        self._session_id = session_id
        pending = iter(servers)
        active: list[_Context] = []
        limit = max(1, min(32, concurrency))
        for _ in range(limit):
            next_server = next(pending, None)
            if next_server is None:
                break
            try:
                active.append(self._open_context(request, next_server))
            except (EngineUnavailableError, ValueError) as exc:
                yield self._failure_result(session_id, next_server, str(exc))

        while active:
            if cancellation.is_canceled or self._session_id != session_id:
                for context in active:
                    self._close_context(context)
                    yield ServerResult(
                        session_id,
                        context.server,
                        ServerStatus.CANCELED,
                        failure=BackendFailure(FailureKind.CANCELED, "Search canceled."),
                    )
                return

            array = self._native.ffi.new(
                "ZOOM_connection[]", [context.connection for context in active]
            )
            event_index = int(self._native.lib.ZOOM_event(len(active), array))
            if event_index <= 0:
                for context in active:
                    yield self._complete_idle(session_id, context)
                    self._close_context(context)
                active.clear()
                break

            context = active[event_index - 1]
            event = int(self._native.lib.ZOOM_connection_last_event(context.connection))
            error = self._connection_failure(context)
            completed: ServerResult | None = None
            retain = False
            if error is not None:
                completed = ServerResult(
                    session_id,
                    context.server,
                    self._status_for_failure(error.kind),
                    failure=error,
                )
            elif event == ZOOM_EVENT_TIMEOUT:
                completed = ServerResult(
                    session_id,
                    context.server,
                    ServerStatus.TIMED_OUT,
                    failure=BackendFailure(
                        FailureKind.TIMEOUT, f"Timeout querying {context.server.name}."
                    ),
                )
            elif event == ZOOM_EVENT_RECV_SEARCH and context.state == "searching":
                hits = int(self._native.lib.ZOOM_resultset_size(context.resultset))
                if hits == 0:
                    completed = ServerResult(
                        session_id, context.server, ServerStatus.EMPTY, number_of_hits=0
                    )
                else:
                    context.state = "presenting"
                    self._native.lib.ZOOM_resultset_records(
                        context.resultset, self._native.ffi.NULL, 0, 1
                    )
            elif event == ZOOM_EVENT_RECV_RECORD and context.state == "presenting":
                hits = int(self._native.lib.ZOOM_resultset_size(context.resultset))
                record = self._read_record(context, 0)
                if isinstance(record, BackendFailure):
                    completed = ServerResult(
                        session_id,
                        context.server,
                        ServerStatus.FAILED,
                        number_of_hits=hits,
                        failure=record,
                    )
                else:
                    completed = ServerResult(
                        session_id,
                        context.server,
                        ServerStatus.SUCCESS,
                        number_of_hits=hits,
                        record=record,
                    )
                    retain = True
            elif event == ZOOM_EVENT_END:
                completed = self._complete_idle(session_id, context)

            if completed is None:
                continue
            active.pop(event_index - 1)
            if retain:
                self._retained[context.server.id] = context
            else:
                self._close_context(context)
            yield completed

            next_server = next(pending, None)
            if next_server is not None:
                try:
                    active.append(self._open_context(request, next_server))
                except (EngineUnavailableError, ValueError) as exc:
                    yield self._failure_result(session_id, next_server, str(exc))

    def fetch_record(
        self,
        session_id: UUID,
        server_id: str,
        position: int,
        cancellation: CancellationToken,
    ) -> MarcRecord | BackendFailure:
        if self._native is None:
            return BackendFailure(FailureKind.ENGINE_UNAVAILABLE, "Embedded YAZ is unavailable.")
        if session_id != self._session_id or server_id not in self._retained:
            return BackendFailure(FailureKind.CANCELED, "The search session is no longer active.")
        context = self._retained[server_id]
        zero_based = position - 1
        if zero_based < 0 or zero_based >= int(
            self._native.lib.ZOOM_resultset_size(context.resultset)
        ):
            return BackendFailure(
                FailureKind.MALFORMED_RESPONSE, "Record position is out of range."
            )
        self._native.lib.ZOOM_resultset_records(
            context.resultset, self._native.ffi.NULL, zero_based, 1
        )
        connections = self._native.ffi.new("ZOOM_connection[]", [context.connection])
        while not cancellation.is_canceled and self._native.lib.ZOOM_event(1, connections):
            failure = self._connection_failure(context)
            if failure is not None:
                return failure
            event = int(self._native.lib.ZOOM_connection_last_event(context.connection))
            if event == ZOOM_EVENT_RECV_RECORD:
                return self._read_record(context, zero_based)
            if event == ZOOM_EVENT_TIMEOUT:
                return BackendFailure(
                    FailureKind.TIMEOUT, f"Timeout retrieving record from {context.server.name}."
                )
        if cancellation.is_canceled:
            return BackendFailure(FailureKind.CANCELED, "Record retrieval canceled.")
        return BackendFailure(FailureKind.MALFORMED_RESPONSE, "The server returned no record.")

    def cancel(self, session_id: UUID) -> None:
        """Supersede a session without touching its native handles from the caller's thread."""
        if self._session_id == session_id:
            self._session_id = None

    def close(self) -> None:
        self._session_id = None
        self._close_retained()

    def _open_context(self, request: SearchRequest, server: ServerDefinition) -> _Context:
        assert self._native is not None
        ffi = self._native.ffi
        lib = self._native.lib
        options = lib.ZOOM_options_create()
        if options == ffi.NULL:
            raise EngineUnavailableError("YAZ could not allocate connection options.")
        for name, value in {
            "async": "1",
            "timeout": str(request.timeout_seconds),
            "databaseName": server.database,
            "preferredRecordSyntax": server.record_syntax,
            "elementSetName": "F",
            "rpnCharset": server.query_charset,
            "charset": "utf-8",
        }.items():
            lib.ZOOM_options_set(options, name.encode(), value.encode())
        connection = lib.ZOOM_connection_create(options)
        query = lib.ZOOM_query_create()
        if connection == ffi.NULL or query == ffi.NULL:
            if query != ffi.NULL:
                lib.ZOOM_query_destroy(query)
            if connection != ffi.NULL:
                lib.ZOOM_connection_destroy(connection)
            lib.ZOOM_options_destroy(options)
            raise EngineUnavailableError("YAZ could not allocate a connection or query.")
        pqf = build_pqf(request.query_type, request.query)
        if lib.ZOOM_query_prefix(query, pqf.encode("utf-8")) != 0:
            lib.ZOOM_query_destroy(query)
            lib.ZOOM_connection_destroy(connection)
            lib.ZOOM_options_destroy(options)
            raise ValueError("YAZ rejected the generated Prefix Query Format expression.")
        lib.ZOOM_connection_connect(connection, server.host.encode("idna"), server.port)
        resultset = lib.ZOOM_connection_search(connection, query)
        if resultset == ffi.NULL:
            lib.ZOOM_query_destroy(query)
            lib.ZOOM_connection_destroy(connection)
            lib.ZOOM_options_destroy(options)
            raise EngineUnavailableError("YAZ could not allocate a result set.")
        return _Context(server, options, connection, query, resultset)

    def _read_record(self, context: _Context, zero_based: int) -> MarcRecord | BackendFailure:
        assert self._native is not None
        ffi = self._native.ffi
        record = self._native.lib.ZOOM_resultset_record_immediate(context.resultset, zero_based)
        if record == ffi.NULL:
            return BackendFailure(FailureKind.MALFORMED_RESPONSE, "The record was unavailable.")
        message = ffi.new("const char **")
        addinfo = ffi.new("const char **")
        diagset = ffi.new("const char **")
        code = int(self._native.lib.ZOOM_record_error(record, message, addinfo, diagset))
        if code:
            detail = " ".join(
                part for part in (self._decode(message[0]), self._decode(addinfo[0])) if part
            )
            return BackendFailure(FailureKind.DIAGNOSTIC, detail or f"Record diagnostic {code}.")
        length = ffi.new("int *")
        buffer = self._native.lib.ZOOM_record_get(record, b"raw", length)
        if buffer == ffi.NULL or int(length[0]) == 0:
            return BackendFailure(FailureKind.MALFORMED_RESPONSE, "The server returned empty MARC.")
        raw = bytes(ffi.buffer(buffer, int(length[0])))
        try:
            return parse_marc(raw, charset_override=context.server.marc_charset)
        except MarcParseError as exc:
            return BackendFailure(FailureKind.MALFORMED_RESPONSE, str(exc))

    def _connection_failure(self, context: _Context) -> BackendFailure | None:
        assert self._native is not None
        ffi = self._native.ffi
        message = ffi.new("const char **")
        addinfo = ffi.new("const char **")
        code = int(self._native.lib.ZOOM_connection_error(context.connection, message, addinfo))
        if not code:
            return None
        detail = (
            " ".join(part for part in (self._decode(message[0]), self._decode(addinfo[0])) if part)
            or f"YAZ diagnostic {code}"
        )
        lowered = detail.casefold()
        if "timed out" in lowered or "timeout" in lowered:
            kind = FailureKind.TIMEOUT
        elif "resolve" in lowered or "name or service" in lowered:
            kind = FailureKind.DNS
        elif "connect" in lowered or "refused" in lowered:
            kind = FailureKind.CONNECTION
        elif code < 10000:
            kind = FailureKind.DIAGNOSTIC
        else:
            kind = FailureKind.INITIALIZATION
        return BackendFailure(kind, f"{context.server.name}: {detail}")

    def _complete_idle(self, session_id: UUID, context: _Context) -> ServerResult:
        error = self._connection_failure(context)
        if error is not None:
            return ServerResult(
                session_id,
                context.server,
                self._status_for_failure(error.kind),
                failure=error,
            )
        hits = int(self._native.lib.ZOOM_resultset_size(context.resultset)) if self._native else 0
        status = ServerStatus.EMPTY if hits == 0 else ServerStatus.FAILED
        failure = (
            None
            if hits == 0
            else BackendFailure(
                FailureKind.MALFORMED_RESPONSE, "Search ended before a MARC record was received."
            )
        )
        return ServerResult(session_id, context.server, status, hits, failure=failure)

    def _failure_result(
        self, session_id: UUID, server: ServerDefinition, message: str
    ) -> ServerResult:
        return ServerResult(
            session_id,
            server,
            ServerStatus.FAILED,
            failure=BackendFailure(FailureKind.INTERNAL, message),
        )

    @staticmethod
    def _status_for_failure(kind: FailureKind) -> ServerStatus:
        if kind == FailureKind.TIMEOUT:
            return ServerStatus.TIMED_OUT
        if kind == FailureKind.CANCELED:
            return ServerStatus.CANCELED
        return ServerStatus.FAILED

    def _close_retained(self) -> None:
        for context in self._retained.values():
            self._close_context(context)
        self._retained.clear()

    def _close_context(self, context: _Context) -> None:
        if self._native is None:
            return
        lib = self._native.lib
        lib.ZOOM_resultset_destroy(context.resultset)
        lib.ZOOM_query_destroy(context.query)
        lib.ZOOM_connection_destroy(context.connection)
        lib.ZOOM_options_destroy(context.options)

    def _decode(self, pointer: Any) -> str:
        if self._native is None or pointer == self._native.ffi.NULL:
            return ""
        return cast(str, self._native.ffi.string(pointer).decode("utf-8", errors="replace"))


def sanitize_query_term(value: str) -> str:
    stripped = value.strip()
    if "\r" in stripped or "\n" in stripped:
        raise ValueError("Query terms cannot contain newline characters.")
    return stripped.replace("\\", "\\\\").replace('"', '\\"')


def build_pqf(query_type: QueryType, query: str | tuple[str, str]) -> str:
    if query_type == QueryType.ISBN:
        return f'@attr 1=7 @attr 4=1 "{sanitize_query_term(str(query))}"'
    if not isinstance(query, tuple) or len(query) != 2:
        raise ValueError("Title/author searches require a title and an author.")
    title, author = query
    return (
        f'@and @attr 1=4 @attr 4=1 "{sanitize_query_term(title)}" '
        f'@attr 1=1003 @attr 4=1 "{sanitize_query_term(author)}"'
    )
