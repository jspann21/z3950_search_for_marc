"""Public query helpers and compatibility names for the embedded ZOOM adapter."""

from __future__ import annotations

from .domain.models import QueryType
from .infrastructure.yaz_engine import build_pqf, sanitize_query_term


class YAZQueryError(RuntimeError):
    pass


def build_search_command(query_type: QueryType, query: str | tuple[str, str]) -> str:
    return build_pqf(query_type, query)


def extract_hits(_stdout: str) -> int:
    """Console hit parsing was removed with yaz-client subprocesses."""
    return 0


class YAZClient:
    def __init__(self, _executable_path: str = "embedded") -> None:
        raise YAZQueryError("YAZClient was replaced by ZoomSessionEngine in version 2.0.")


__all__ = ["YAZClient", "YAZQueryError", "build_search_command", "sanitize_query_term"]
