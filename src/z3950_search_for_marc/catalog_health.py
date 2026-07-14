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
from .infrastructure.atomic import atomic_write_bytes, atomic_write_json
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
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    runner_results = [
        {item["server_id"]: item for item in document["results"]} for document in runner_documents
    ]
    old_servers = previous_state.get("servers", {})
    new_state: dict[str, Any] = {"schema_version": 1, "servers": {}}
    transitions: list[dict[str, Any]] = []
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
            transitions.append(
                {
                    "server_id": server_id,
                    "name": str(server.get("name", server_id)),
                    "endpoint": (
                        f"{server.get('host', 'unknown')}:{server.get('port', 'unknown')}"
                        f"/{server.get('database', 'unknown')}"
                    ),
                    "from_status": old_status,
                    "to_status": str(new_status),
                    "reason": (
                        f"Both runners failed {failures} consecutive checks."
                        if str(new_status) == str(CatalogStatus.QUARANTINED)
                        else f"At least one runner succeeded {successes} consecutive checks."
                    ),
                    "observations": [
                        {
                            "runner": str(document.get("runner", "unknown")),
                            "healthy": observation.get("healthy") if observation else None,
                            "status": observation.get("status") if observation else "missing",
                            "detail": observation.get("detail") if observation else "No result",
                        }
                        for document, observation in zip(
                            runner_documents, observations, strict=True
                        )
                    ],
                }
            )
        server["status"] = str(new_status)
        if str(new_status) != old_status and any_healthy:
            server["last_verified_at"] = checked_at
        new_state["servers"][server_id] = {
            "consecutive_dual_failures": failures,
            "consecutive_successes": successes,
            "last_checked_at": checked_at,
            "observations": observations,
        }
    new_state["retirement_candidates"] = retirement_candidates
    return catalog, new_state, transitions


def build_health_report(
    runner_documents: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    retirement_candidates: list[str],
    new_retirement_candidates: list[str],
    *,
    checked_at: str,
) -> dict[str, Any]:
    runner_summaries = []
    for document in runner_documents:
        results = document["results"]
        healthy = sum(1 for result in results if result["healthy"])
        runner_summaries.append(
            {
                "runner": str(document.get("runner", "unknown")),
                "checked_at": str(document.get("checked_at", checked_at)),
                "total": len(results),
                "healthy": healthy,
                "failed": len(results) - healthy,
            }
        )
    return {
        "schema_version": 1,
        "checked_at": checked_at,
        "runner_summaries": runner_summaries,
        "transitions": transitions,
        "retirement_candidates": retirement_candidates,
        "new_retirement_candidates": new_retirement_candidates,
    }


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def format_health_report(report: dict[str, Any]) -> str:
    transitions = report["transitions"]
    new_candidates = report["new_retirement_candidates"]
    lines = [
        "# Weekly server catalog health",
        "",
        f"Checked at `{report['checked_at']}`.",
        "",
        "## Result",
        "",
        f"- Status transitions requiring review: **{len(transitions)}**",
        f"- New retirement candidates: **{len(new_candidates)}**",
        "",
        "## Runner summary",
        "",
        "| Runner | Healthy | Failed | Total | Checked at |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for summary in report["runner_summaries"]:
        lines.append(
            f"| {_markdown_cell(summary['runner'])} | {summary['healthy']} | "
            f"{summary['failed']} | {summary['total']} | "
            f"`{_markdown_cell(summary['checked_at'])}` |"
        )
    if transitions:
        lines.extend(
            [
                "",
                "## Proposed status transitions",
                "",
                "| Server | Endpoint | Change | Reason | Latest observations |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for transition in transitions:
            observation_parts = []
            for item in transition["observations"]:
                detail = str(item.get("detail", "")).strip()
                observation = f"{item['runner']}: {item['status']}"
                if detail:
                    observation += f" - {detail[:200]}"
                observation_parts.append(observation)
            observations = "; ".join(observation_parts)
            lines.append(
                f"| {_markdown_cell(transition['name'])} | "
                f"`{_markdown_cell(transition['endpoint'])}` | "
                f"`{_markdown_cell(transition['from_status'])}` -> "
                f"`{_markdown_cell(transition['to_status'])}` | "
                f"{_markdown_cell(transition['reason'])} | "
                f"{_markdown_cell(observations)} |"
            )
        lines.extend(
            [
                "",
                "Merging the pull request applies only these catalog status transitions. "
                "Raw probe output and rolling health counters are deliberately excluded.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "No catalog status changed, so no pull request is needed.",
            ]
        )
    if new_candidates:
        lines.extend(
            [
                "",
                "## New retirement candidates",
                "",
                "These server IDs have failed on both runners for 30 consecutive checks. "
                "They are not retired automatically:",
                "",
                *[f"- `{server_id}`" for server_id in new_candidates],
            ]
        )
    lines.extend(
        [
            "",
            "Policy: quarantine after seven consecutive dual-runner failures; recover after "
            "two consecutive checks where at least one runner succeeds. Retirement always "
            "requires maintainer review.",
            "",
        ]
    )
    return "\n".join(lines)


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
    now = datetime.now(UTC)
    checked_at = now.isoformat().replace("+00:00", "Z")
    updated, new_state, transitions = aggregate_health(catalog, state, runners, now=now)
    if transitions:
        updated["published_at"] = checked_at
    previous_candidate_values = state.get("retirement_candidates", [])
    previous_candidates = (
        {str(item) for item in previous_candidate_values}
        if isinstance(previous_candidate_values, list)
        else set()
    )
    candidates = [str(item) for item in new_state["retirement_candidates"]]
    report = build_health_report(
        runners,
        transitions,
        candidates,
        [item for item in candidates if item not in previous_candidates],
        checked_at=checked_at,
    )
    atomic_write_json(args.output_catalog, updated, sort_keys=False)
    atomic_write_json(args.output_state, new_state)
    atomic_write_json(args.transition_report, report)
    if args.markdown_report:
        atomic_write_bytes(args.markdown_report, format_health_report(report).encode("utf-8"))
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
    aggregate.add_argument("--markdown-report", type=Path)
    aggregate.set_defaults(handler=_aggregate_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
