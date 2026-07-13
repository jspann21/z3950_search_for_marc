"""Search backend abstraction and the cancellable YAZ implementation."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from .marc import clean_yaz_output, decode_yaz_output
from .models import (
    BackendFailure,
    BackendResponse,
    BackendResult,
    FailureKind,
    SearchRequest,
    ServerConfig,
)
from .yaz import build_search_command, extract_hits


class CancellationToken:
    """Thread-safe cancellation state shared by all work in a session."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_canceled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()


class SearchBackend(Protocol):
    """Backend used by the application search service."""

    def search_server(
        self,
        request: SearchRequest,
        server: ServerConfig,
        position: int,
        cancellation: CancellationToken,
    ) -> BackendResult: ...

    def cancel(self, cancellation: CancellationToken) -> None: ...


def _standard_windows_yaz_candidates() -> Iterable[Path]:
    if os.name != "nt":
        return ()
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    candidates: list[Path] = []
    for root in roots:
        if not root:
            continue
        base = Path(root)
        candidates.extend(
            [
                base / "YAZ" / "bin" / "yaz-client.exe",
                base / "Index Data" / "YAZ" / "bin" / "yaz-client.exe",
            ]
        )
    return candidates


def resolve_yaz_executable(configured: str) -> str | None:
    """Resolve a configured executable, PATH command, or standard Windows install."""
    value = configured.strip() or "yaz-client"
    expanded = Path(value).expanduser()
    if expanded.is_file():
        return str(expanded.resolve())
    discovered = shutil.which(value)
    if discovered:
        return discovered
    for candidate in _standard_windows_yaz_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


class YAZBackend:
    """Execute yaz-client commands while tracking processes by cancellation token."""

    def __init__(self, executable: str):
        self.executable = executable
        self._active: dict[CancellationToken, set[subprocess.Popen[bytes]]] = {}
        self._lock = threading.Lock()

    def search_server(
        self,
        request: SearchRequest,
        server: ServerConfig,
        position: int,
        cancellation: CancellationToken,
    ) -> BackendResult:
        if cancellation.is_canceled:
            return BackendFailure(FailureKind.CANCELED, "Search canceled.")

        executable = resolve_yaz_executable(self.executable)
        if executable is None:
            return BackendFailure(
                FailureKind.MISSING_EXECUTABLE,
                f"Configured yaz-client executable was not found: {self.executable}",
            )

        payload = build_search_command(request.query_type, request.query) + f"show {position}\n"
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [executable, server.endpoint],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._register(cancellation, process)
            if cancellation.is_canceled:
                self._stop_process(process)
                return BackendFailure(FailureKind.CANCELED, "Search canceled.")
            stdout_bytes, stderr_bytes = process.communicate(
                input=payload.encode("utf-8"), timeout=request.timeout_seconds
            )
            if cancellation.is_canceled:
                return BackendFailure(FailureKind.CANCELED, "Search canceled.")

            stdout = decode_yaz_output(stdout_bytes)
            stderr = decode_yaz_output(stderr_bytes)
            if process.returncode not in (0, None):
                detail = stderr.strip() or stdout.strip() or "Unknown yaz-client error."
                return BackendFailure(FailureKind.PROCESS, f"{server.name}: {detail}")
            if "Present request out of range" in stdout:
                return BackendFailure(
                    FailureKind.MALFORMED_RESPONSE,
                    "Requested more records than are available.",
                )
            return BackendResponse(stdout, clean_yaz_output(stdout), extract_hits(stdout))
        except subprocess.TimeoutExpired:
            if process is not None:
                self._stop_process(process)
            return BackendFailure(FailureKind.TIMEOUT, f"Timeout querying {server.name}.")
        except FileNotFoundError:
            return BackendFailure(
                FailureKind.MISSING_EXECUTABLE,
                f"Configured yaz-client executable was not found: {self.executable}",
            )
        except OSError as exc:
            if cancellation.is_canceled:
                return BackendFailure(FailureKind.CANCELED, "Search canceled.")
            return BackendFailure(FailureKind.PROCESS, f"Failed to query {server.name}: {exc}")
        finally:
            if process is not None:
                self._unregister(cancellation, process)

    def cancel(self, cancellation: CancellationToken) -> None:
        cancellation.cancel()
        with self._lock:
            processes = list(self._active.get(cancellation, ()))
        for process in processes:
            self._stop_process(process)

    def close(self) -> None:
        with self._lock:
            active = [(token, list(processes)) for token, processes in self._active.items()]
        for token, processes in active:
            token.cancel()
            for process in processes:
                self._stop_process(process)

    def _register(self, token: CancellationToken, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._active.setdefault(token, set()).add(process)

    def _unregister(self, token: CancellationToken, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            processes = self._active.get(token)
            if processes is None:
                return
            processes.discard(process)
            if not processes:
                self._active.pop(token, None)

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        try:
            if process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        except (OSError, subprocess.SubprocessError):
            return
