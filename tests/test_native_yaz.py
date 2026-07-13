from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from z3950_search_for_marc.domain.models import (
    LocationGroup,
    MarcRecord,
    QueryType,
    SearchRequest,
    ServerDefinition,
    ServerStatus,
)
from z3950_search_for_marc.infrastructure.yaz_engine import CancellationToken, ZoomSessionEngine


@pytest.mark.native
def test_compiled_yaz_adapter_reports_pinned_version() -> None:
    engine = ZoomSessionEngine()

    assert engine.available
    assert engine.version == "5.37.3"

    engine.close()


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _server(port: int, identifier: str) -> ServerDefinition:
    return ServerDefinition(
        identifier,
        "YAZ test server",
        "127.0.0.1",
        port,
        "Default",
        "US",
        LocationGroup.USA,
    )


@pytest.mark.native
def test_zoom_search_present_navigation_and_target_isolation() -> None:
    executable = Path("native/yaz/bin/yaz-ztest.exe").resolve()
    if not executable.is_file():
        pytest.skip("The pinned YAZ test server has not been built.")
    port = _unused_port()
    process = subprocess.Popen(  # noqa: S603
        [str(executable), f"tcp:@:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("The pinned YAZ test server did not start.")

        engine = ZoomSessionEngine()
        session_id = uuid4()
        good = _server(port, "00000000-0000-4000-8000-000000000010")
        failed = _server(_unused_port(), "00000000-0000-4000-8000-000000000011")
        request = SearchRequest(
            QueryType.ISBN,
            "9780306406157",
            frozenset({"USA"}),
            timeout_seconds=2,
        )

        results = list(
            engine.search_many(
                session_id,
                request,
                (good, failed),
                concurrency=2,
                cancellation=CancellationToken(),
            )
        )

        by_id = {result.server.id: result for result in results}
        assert by_id[good.id].status == ServerStatus.SUCCESS
        first = by_id[good.id].record
        assert first is not None
        assert first.raw_bytes.endswith(b"\x1d")
        assert by_id[failed.id].status in {ServerStatus.FAILED, ServerStatus.TIMED_OUT}
        second = engine.fetch_record(session_id, good.id, 2, CancellationToken())
        assert isinstance(second, MarcRecord)
        assert second.raw_bytes.endswith(b"\x1d")
        engine.close()
    finally:
        process.terminate()
        process.wait(timeout=5)
