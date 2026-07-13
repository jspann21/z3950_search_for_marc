"""Scheduled multi-runner catalog probing and conservative status transitions."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .domain.models import CatalogStatus, QueryType, SearchRequest, ServerStatus
from .infrastructure.atomic import atomic_write_json
from .infrastructure.catalog import CatalogRepository
from .infrastructure.yaz_engine import CancellationToken, ZoomSessionEngine

PROBE_ISBN = "9780306406157"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    server_id: str
    healthy: bool
    status: str
    detail: str


def run_probe(catalog_path: Path, schema_path: Path, runner: str) -> dict[str, Any]:
    repository = CatalogRepository(bundled_path=catalog_path, schema_path=schema_path)
    document = repository.load_upstream()
    servers = tuple(server for server in document.servers if server.status != CatalogStatus.RETIRED)
    engine = ZoomSessionEngine()
    if not engine.available:
        raise RuntimeError("Embedded YAZ is required for catalog probing.")
    request = SearchRequest(
        QueryType.ISBN,
        PROBE_ISBN,
        frozenset({"USA", "Worldwide"}),
        timeout_seconds=8,
    )
    results: list[dict[str, Any]] = []
    try:
        for outcome in engine.search_many(
            uuid4(), request, servers, concurrency=16, cancellation=CancellationToken()
        ):
            healthy = outcome.status in {ServerStatus.SUCCESS, ServerStatus.EMPTY}
            results.append(
                {
                    "server_id": outcome.server.id,
                    "healthy": healthy,
                    "status": (
                        outcome.failure.kind.value if outcome.failure else outcome.status.value
                    ),
                    "detail": outcome.message,
                }
            )
    finally:
        engine.close()
    return {
        "schema_version": 1,
        "runner": runner,
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "results": results,
    }


def aggregate_health(
    catalog: dict[str, Any],
    previous_state: dict[str, Any],
    runner_documents: list[dict[str, Any]],
    *,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    runner_results = [
        {item["server_id"]: item for item in document["results"]} for document in runner_documents
    ]
    old_servers = previous_state.get("servers", {})
    new_state: dict[str, Any] = {"schema_version": 1, "servers": {}}
    transitions: list[str] = []
    retirement_candidates: list[str] = []
    checked_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")

    for server in catalog["servers"]:
        server_id = server["id"]
        old = old_servers.get(server_id, {})
        observations = [results.get(server_id) for results in runner_results]
        all_failed = bool(observations) and all(
            observation is not None and not observation["healthy"] for observation in observations
        )
        any_healthy = any(
            observation is not None and observation["healthy"] for observation in observations
        )
        failures = int(old.get("consecutive_dual_failures", 0))
        successes = int(old.get("consecutive_successes", 0))
        if all_failed:
            failures += 1
            successes = 0
        elif any_healthy:
            failures = 0
            successes += 1

        old_status = str(server["status"])
        new_status = old_status
        if old_status == CatalogStatus.ACTIVE and failures >= 7:
            new_status = CatalogStatus.QUARANTINED
        elif old_status == CatalogStatus.QUARANTINED and successes >= 2:
            new_status = CatalogStatus.ACTIVE
        if failures >= 30 and new_status == CatalogStatus.QUARANTINED:
            retirement_candidates.append(server_id)
        if str(new_status) != old_status:
            transitions.append(f"{server_id}: {old_status} -> {new_status}")
        server["status"] = str(new_status)
        if any_healthy:
            server["last_verified_at"] = checked_at
        new_state["servers"][server_id] = {
            "consecutive_dual_failures": failures,
            "consecutive_successes": successes,
            "last_checked_at": checked_at,
            "observations": observations,
        }
    new_state["retirement_candidates"] = retirement_candidates
    return catalog, new_state, transitions


def _probe_command(args: argparse.Namespace) -> int:
    atomic_write_json(args.output, run_probe(args.catalog, args.schema, args.runner))
    return 0


def _aggregate_command(args: argparse.Namespace) -> int:
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    state = (
        json.loads(args.state.read_text(encoding="utf-8"))
        if args.state.is_file()
        else {"schema_version": 1, "servers": {}}
    )
    runners = [json.loads(path.read_text(encoding="utf-8")) for path in args.runner_result]
    updated, new_state, transitions = aggregate_health(
        catalog, state, runners, now=datetime.now(UTC)
    )
    if transitions:
        updated["published_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    atomic_write_json(args.output_catalog, updated)
    atomic_write_json(args.output_state, new_state)
    atomic_write_json(args.transition_report, {"transitions": transitions})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--catalog", type=Path, required=True)
    probe.add_argument("--schema", type=Path, required=True)
    probe.add_argument("--runner", required=True)
    probe.add_argument("--output", type=Path, required=True)
    probe.set_defaults(handler=_probe_command)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--catalog", type=Path, required=True)
    aggregate.add_argument("--state", type=Path, required=True)
    aggregate.add_argument("--runner-result", type=Path, action="append", required=True)
    aggregate.add_argument("--output-catalog", type=Path, required=True)
    aggregate.add_argument("--output-state", type=Path, required=True)
    aggregate.add_argument("--transition-report", type=Path, required=True)
    aggregate.set_defaults(handler=_aggregate_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
