from __future__ import annotations

import io

from pymarc import MARCReader

from z3950_search_for_marc.marc import (
    format_record_for_display,
    parse_marc,
    record_bytes_for_export,
    sanitize_filename,
)

from .helpers import marc_bytes


def test_raw_marc_round_trip_is_exact_when_trimming_is_disabled() -> None:
    raw = marc_bytes()
    record = parse_marc(raw)

    assert record_bytes_for_export(record, trim_records=False) == raw


def test_trimmed_export_removes_control_and_local_fields_but_is_valid_iso2709() -> None:
    wrapped = parse_marc(marc_bytes())

    exported = record_bytes_for_export(wrapped, trim_records=True)
    parsed = next(MARCReader(io.BytesIO(exported), to_unicode=True))

    assert parsed is not None
    assert parsed.get_fields("001", "900") == []
    assert parsed["245"]["a"] == "Test title"


def test_swedish_text_is_preserved_without_console_decoding() -> None:
    wrapped = parse_marc(marc_bytes())

    displayed = format_record_for_display(wrapped)

    assert "Ändra kod för fullständighetsnivå" in displayed


def test_explicit_charset_override_repairs_a_misdeclared_record() -> None:
    malformed = marc_bytes("CafX").replace(b"CafX", b"Caf\xe9")

    record = parse_marc(malformed, charset_override="cp1252")

    assert "Café" in format_record_for_display(record)
    assert record.raw_bytes == malformed


def test_display_trimming_matches_export_policy() -> None:
    wrapped = parse_marc(marc_bytes())

    displayed = format_record_for_display(wrapped, trim_records=True)

    assert "001" not in displayed
    assert "900" not in displayed
    assert "245" in displayed


def test_sanitize_filename_handles_windows_characters() -> None:
    assert sanitize_filename("A title: with / invalid * chars?") == "A_title_with_invalid_chars"
