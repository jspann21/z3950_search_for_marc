"""Compatibility exports for the embedded native YAZ engine."""

from .infrastructure.yaz_engine import (
    CancellationToken,
)
from .infrastructure.yaz_engine import (
    SessionEngine as SearchBackend,
)
from .infrastructure.yaz_engine import (
    ZoomSessionEngine as YAZBackend,
)


def resolve_yaz_executable(_configured: str = "") -> None:
    """The v2 application never resolves an external yaz-client executable."""
    return None


__all__ = ["CancellationToken", "SearchBackend", "YAZBackend", "resolve_yaz_executable"]
