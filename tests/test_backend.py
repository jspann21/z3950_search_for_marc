from __future__ import annotations

import subprocess
import threading
from typing import Any

from z3950_search_for_marc import backend as backend_module
from z3950_search_for_marc.backend import CancellationToken, YAZBackend
from z3950_search_for_marc.models import (
    BackendFailure,
    BackendResponse,
    FailureKind,
    QueryType,
    SearchRequest,
    ServerConfig,
)

SERVER = ServerConfig("Test Library", "example.org", 210, "books", "Worldwide")
REQUEST = SearchRequest(QueryType.ISBN, "9780306406157", frozenset({"Worldwide"}), 5)


class FakeProcess:
    def __init__(
        self,
        stdout: bytes = b"Number of hits: 1\n245 10 $a Test title\n",
        *,
        timeout: bool = False,
        wait_for_stop: bool = False,
    ) -> None:
        self.stdout = stdout
        self.returncode: int | None = 0
        self.timeout = timeout
        self.wait_for_stop = wait_for_stop
        self.terminated = False
        self.killed = False
        self._stopped = threading.Event()

    def communicate(self, input: bytes, timeout: int) -> tuple[bytes, bytes]:
        if self.timeout:
            raise subprocess.TimeoutExpired("yaz-client", timeout)
        if self.wait_for_stop:
            self._stopped.wait(2)
            self.returncode = -15
        return self.stdout, b""

    def poll(self) -> int | None:
        return self.returncode if self.terminated or self.killed else None

    def terminate(self) -> None:
        self.terminated = True
        self._stopped.set()

    def kill(self) -> None:
        self.killed = True
        self._stopped.set()

    def wait(self, timeout: float) -> int:
        return -15 if self.terminated or self.killed else 0


def _install_fake_process(monkeypatch, process: FakeProcess) -> None:
    monkeypatch.setattr(backend_module, "resolve_yaz_executable", lambda _: "yaz-client")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)


def test_backend_returns_typed_success(monkeypatch) -> None:
    process = FakeProcess()
    _install_fake_process(monkeypatch, process)

    result = YAZBackend("yaz-client").search_server(REQUEST, SERVER, 1, CancellationToken())

    assert isinstance(result, BackendResponse)
    assert result.number_of_hits == 1
    assert "245 10" in result.cleaned_data


def test_backend_classifies_missing_executable(monkeypatch) -> None:
    monkeypatch.setattr(backend_module, "resolve_yaz_executable", lambda _: None)

    result = YAZBackend("missing").search_server(REQUEST, SERVER, 1, CancellationToken())

    assert result == BackendFailure(
        FailureKind.MISSING_EXECUTABLE,
        "Configured yaz-client executable was not found: missing",
    )


def test_backend_times_out_and_terminates_process(monkeypatch) -> None:
    process = FakeProcess(timeout=True)
    _install_fake_process(monkeypatch, process)

    result = YAZBackend("yaz-client").search_server(REQUEST, SERVER, 1, CancellationToken())

    assert isinstance(result, BackendFailure)
    assert result.kind == FailureKind.TIMEOUT
    assert process.terminated


def test_backend_cancel_stops_active_process(monkeypatch) -> None:
    process = FakeProcess(wait_for_stop=True)
    _install_fake_process(monkeypatch, process)
    backend = YAZBackend("yaz-client")
    token = CancellationToken()
    output: list[Any] = []
    thread = threading.Thread(
        target=lambda: output.append(backend.search_server(REQUEST, SERVER, 1, token))
    )
    thread.start()
    for _ in range(1000):
        if backend._active:  # noqa: SLF001 - verifies the process registry contract
            break
    backend.cancel(token)
    thread.join(timeout=2)

    assert process.terminated
    assert output
    assert isinstance(output[0], BackendFailure)
    assert output[0].kind == FailureKind.CANCELED
