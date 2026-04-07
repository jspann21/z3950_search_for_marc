from __future__ import annotations

import subprocess
from typing import Any

import pytest

from z3950_search_for_marc.models import QueryType, ServerConfig
from z3950_search_for_marc.yaz import (
    YAZClient,
    YAZQueryError,
    build_search_command,
    sanitize_query_term,
)


class FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    def __enter__(self) -> FakeProcess:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def communicate(self, input: bytes, timeout: int) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None

    def wait(self, timeout: int) -> None:
        return None


def test_sanitize_query_term_rejects_newlines() -> None:
    with pytest.raises(ValueError, match="newline"):
        sanitize_query_term("bad\nvalue")


def test_build_search_command_escapes_quotes() -> None:
    command = build_search_command(QueryType.TITLE_AUTHOR, ('He said "Hi"', 'Author'))

    assert '\\"Hi\\"' in command


def test_yaz_client_query_parses_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = (
        b"Number of hits: 2, setno 1\n"
        b"245 10 $a Test title\n"
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess(stdout))
    client = YAZClient("yaz-client")
    server = ServerConfig("Test", "example.org", 210, "books", "Worldwide")

    response = client.query(
        server,
        query_type=QueryType.ISBN,
        query="9780306406157",
        start=1,
        timeout_seconds=5,
    )

    assert response.number_of_hits == 2
    assert "245 10 $a Test title" in response.cleaned_data


def test_yaz_client_query_raises_for_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = b"Present request out of range\n"
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess(stdout))
    client = YAZClient("yaz-client")
    server = ServerConfig("Test", "example.org", 210, "books", "Worldwide")

    with pytest.raises(YAZQueryError, match="No more records"):
        client.query(
            server,
            query_type=QueryType.ISBN,
            query="9780306406157",
            start=99,
            timeout_seconds=5,
        )
