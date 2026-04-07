"""Subprocess interaction with yaz-client."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .marc import clean_yaz_output, decode_yaz_output
from .models import QueryType, ServerConfig


class YAZQueryError(RuntimeError):
    """Raised when a YAZ query cannot be completed."""


@dataclass(frozen=True, slots=True)
class YAZResponse:
    """Decoded response details from yaz-client."""

    stdout_text: str
    cleaned_data: str
    number_of_hits: int


def sanitize_query_term(value: str) -> str:
    """Normalize a query term before writing it to yaz-client stdin."""
    sanitized = value.strip()
    if "\r" in sanitized or "\n" in sanitized:
        raise ValueError("Query terms cannot contain newline characters.")
    return sanitized.replace('"', '\\"')


def build_search_command(query_type: QueryType, query: str | tuple[str, str]) -> str:
    """Build the YAZ search command for the supplied query."""
    if query_type == QueryType.ISBN:
        return f'find @attr 1=7 @attr 4=1 "{sanitize_query_term(str(query))}"\n'
    if not isinstance(query, tuple):
        raise ValueError("Title/author searches require a (title, author) tuple.")
    title, author = query
    safe_title = sanitize_query_term(title)
    safe_author = sanitize_query_term(author)
    return (
        f'find @and @attr 1=4 @attr 4=1 "{safe_title}" '
        f'@attr 1=1003 @attr 4=1 "{safe_author}"\n'
    )


def creation_flags() -> int:
    """Return Windows-specific subprocess flags when available."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class YAZClient:
    """Run yaz-client queries safely."""

    def __init__(self, executable_path: str):
        self.executable_path = executable_path

    def query(
        self,
        server: ServerConfig,
        *,
        query_type: QueryType,
        query: str | tuple[str, str],
        start: int,
        timeout_seconds: int,
    ) -> YAZResponse:
        """Execute a search and return the decoded response."""
        command = [self.executable_path, server.endpoint]
        stdin_payload = build_search_command(query_type, query) + f"show {start}\n"
        try:
            with subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                creationflags=creation_flags(),
            ) as process:
                try:
                    stdout_bytes, stderr_bytes = process.communicate(
                        input=stdin_payload.encode("utf-8"),
                        timeout=timeout_seconds,
                    )
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.wait(timeout=5)
                    raise YAZQueryError(f"Timeout querying {server.name}.") from exc

                stdout_text = decode_yaz_output(stdout_bytes)
                stderr_text = decode_yaz_output(stderr_bytes)

                if process.returncode not in (0, None):
                    detail = (
                        stderr_text.strip()
                        or stdout_text.strip()
                        or "Unknown yaz-client error."
                    )
                    raise YAZQueryError(f"Error querying {server.name}: {detail}")

                if "Present request out of range" in stdout_text:
                    raise YAZQueryError("Requested more records than available. No more records.")

                return YAZResponse(
                    stdout_text=stdout_text,
                    cleaned_data=clean_yaz_output(stdout_text),
                    number_of_hits=extract_hits(stdout_text),
                )
        except FileNotFoundError as exc:
            raise YAZQueryError(
                f"Configured yaz-client executable was not found: {self.executable_path}"
            ) from exc
        except OSError as exc:
            raise YAZQueryError(f"Failed to launch yaz-client: {exc}") from exc


def extract_hits(stdout: str) -> int:
    """Parse the hit count from YAZ output."""
    hits_line = next((line for line in stdout.splitlines() if "Number of hits:" in line), None)
    if not hits_line:
        return 0
    try:
        return int(hits_line.split(":")[1].split(",")[0].strip())
    except (IndexError, ValueError):
        return 0
