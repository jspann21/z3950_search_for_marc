from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pymarc import Field, Indicators, Record, Subfield

from z3950_search_for_marc.domain.models import LocationGroup, ServerDefinition


def server(
    identifier: str = "00000000-0000-4000-8000-000000000001",
    name: str = "Test Library",
) -> ServerDefinition:
    return ServerDefinition(
        id=identifier,
        name=name,
        host="127.0.0.1",
        port=9999,
        database="Default",
        country_code="US",
        location_group=LocationGroup.USA,
    )


def marc_bytes(title: str = "Test title", include_trimmed_fields: bool = True) -> bytes:
    record = Record(force_utf8=True)
    if include_trimmed_fields:
        record.add_field(Field(tag="001", data="control-number"))
    record.add_field(
        Field(
            tag="100",
            indicators=Indicators("1", " "),
            subfields=[Subfield("a", "Test Author")],
        )
    )
    record.add_field(
        Field(
            tag="245",
            indicators=Indicators("1", "0"),
            subfields=[Subfield("a", title)],
        )
    )
    record.add_field(
        Field(
            tag="599",
            indicators=Indicators(" ", " "),
            subfields=[
                Subfield(
                    "a",
                    "Maskinellt genererad post. Ändra kod för fullständighetsnivå.",
                )
            ],
        )
    )
    if include_trimmed_fields:
        record.add_field(
            Field(
                tag="900",
                indicators=Indicators(" ", " "),
                subfields=[Subfield("a", "local data")],
            )
        )
    return record.as_marc()


def write_catalog(path: Path, servers: list[ServerDefinition]) -> None:
    from z3950_search_for_marc.infrastructure.catalog import server_to_mapping

    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "catalog_version": "test-1",
                "published_at": datetime.now(UTC).isoformat(),
                "servers": [server_to_mapping(value) for value in servers],
            }
        ),
        encoding="utf-8",
    )
