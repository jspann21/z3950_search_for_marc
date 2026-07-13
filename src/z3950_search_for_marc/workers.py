"""Compatibility exports for the former worker module.

Search work is now coordinated by :mod:`z3950_search_for_marc.search` using one
bounded thread pool and session-aware cancellation.
"""

from .search import RecordTask, SearchCoordinator, SearchTask

__all__ = ["RecordTask", "SearchCoordinator", "SearchTask"]
