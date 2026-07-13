from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from z3950_search_for_marc.catalog_health import aggregate_health


def _catalog(status: str = "active") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "catalog_version": "test",
        "published_at": "2026-01-01T00:00:00Z",
        "servers": [{"id": "one", "status": status, "last_verified_at": None}],
    }


def _runner(healthy: bool) -> dict[str, Any]:
    return {"results": [{"server_id": "one", "healthy": healthy, "status": "status", "detail": ""}]}


def test_seven_dual_failures_quarantine_server() -> None:
    state = {"servers": {"one": {"consecutive_dual_failures": 6, "consecutive_successes": 0}}}

    catalog, new_state, transitions = aggregate_health(
        _catalog(), state, [_runner(False), _runner(False)], now=datetime.now(UTC)
    )

    assert catalog["servers"][0]["status"] == "quarantined"
    assert new_state["servers"]["one"]["consecutive_dual_failures"] == 7
    assert transitions


def test_two_successful_days_restore_quarantined_server() -> None:
    state = {"servers": {"one": {"consecutive_dual_failures": 0, "consecutive_successes": 1}}}

    catalog, _, _ = aggregate_health(
        _catalog("quarantined"), state, [_runner(True), _runner(False)], now=datetime.now(UTC)
    )

    assert catalog["servers"][0]["status"] == "active"


def test_thirty_failures_only_create_retirement_candidate() -> None:
    state = {"servers": {"one": {"consecutive_dual_failures": 29, "consecutive_successes": 0}}}

    catalog, new_state, _ = aggregate_health(
        _catalog("quarantined"), state, [_runner(False), _runner(False)], now=datetime.now(UTC)
    )

    assert catalog["servers"][0]["status"] == "quarantined"
    assert new_state["retirement_candidates"] == ["one"]
