"""Lossless MARC parsing, display formatting, and explicit export trimming."""

from __future__ import annotations

import copy
import io
import os
import re
from collections.abc import Callable

from pymarc import MARCReader, Record

from .domain.models import MarcRecord

LogCallback = Callable[[str], None]


class MarcParseError(ValueError):
    pass


def parse_marc(
    raw_bytes: bytes,
    *,
    charset_override: str = "auto",
    log_callback: LogCallback | None = None,
) -> MarcRecord:
    if not raw_bytes:
        raise MarcParseError("The server returned an empty MARC record.")
    attempts: list[tuple[bytes, str, str]] = [(raw_bytes, "strict", "iso8859-1")]
    if charset_override.casefold() not in {"", "auto", "marc-8", "marc8", "utf-8"}:
        override_bytes = bytearray(raw_bytes)
        # A known-bad target may claim UTF-8 in leader/09 while returning a legacy code page.
        # The parse copy lets PyMARC apply the override while raw_bytes remains exact.
        if len(override_bytes) > 9:
            override_bytes[9] = ord(" ")
        attempts.append((bytes(override_bytes), "strict", charset_override))
    attempts.append((raw_bytes, "replace", "iso8859-1"))
    last_error: Exception | None = None
    for index, (parse_bytes, utf8_handling, file_encoding) in enumerate(attempts):
        try:
            reader = MARCReader(
                io.BytesIO(parse_bytes),
                to_unicode=True,
                force_utf8=False,
                utf8_handling=utf8_handling,
                file_encoding=file_encoding,
            )
            record = next(reader)
            if record is None:
                raise MarcParseError("PyMARC rejected the server record as malformed.")
            if index and log_callback:
                mode = (
                    f"the {charset_override} catalog override"
                    if file_encoding != "iso8859-1"
                    else "replacement decoding"
                )
                log_callback(f"Record used {mode} after standard MARC decoding failed.")
            return MarcRecord(record, bytes(raw_bytes))
        except (StopIteration, UnicodeDecodeError, ValueError) as exc:
            last_error = exc
    raise MarcParseError(f"Could not parse the ISO2709 record: {last_error}")


def should_trim_tag(tag: str) -> bool:
    return tag.isdigit() and (int(tag) < 10 or int(tag) >= 900)


def trimmed_copy(record: Record) -> Record:
    clone = copy.deepcopy(record)
    tags = sorted({field.tag for field in clone.fields if should_trim_tag(field.tag)})
    if tags:
        clone.remove_fields(*tags)
    return clone


def record_bytes_for_export(record: MarcRecord, *, trim_records: bool) -> bytes:
    if not trim_records:
        return record.raw_bytes
    return trimmed_copy(record.parsed).as_marc()


def format_record_for_display(record: Record | MarcRecord, *, trim_records: bool = False) -> str:
    parsed = record.parsed if isinstance(record, MarcRecord) else record
    visible = trimmed_copy(parsed) if trim_records else parsed
    lines = [f"LDR    {visible.leader}"]
    for field in visible.fields:
        if field.is_control_field():
            lines.append(f"{field.tag}    {field.data}")
            continue
        indicators = "".join(field.indicators or (" ", " "))
        subfields = " ".join(f"${subfield.code} {subfield.value}" for subfield in field.subfields)
        lines.append(f"{field.tag} {indicators} {subfields}".rstrip())
    return "\n".join(lines)


def sanitize_filename(filename: str, max_length: int = 180) -> str:
    forbidden_chars = r'<>:"/\|?*' if os.name == "nt" else r"/"
    sanitized = re.sub(f"[{re.escape(forbidden_chars)}]", "_", filename)
    sanitized = re.sub(r"[^\w\s\-_.]", "", sanitized, flags=re.UNICODE)
    sanitized = re.sub(r"\s+", "_", sanitized).strip("._")
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized[:max_length].rstrip("_") or "MARC_Record"


def get_record_info(record: Record | MarcRecord) -> tuple[str, str]:
    parsed = record.parsed if isinstance(record, MarcRecord) else record
    author = "MARC_Record"
    title = "MARC_Record"
    for field in parsed.get_fields("100", "110", "111"):
        values = field.get_subfields("a")
        if values:
            author = sanitize_filename(" ".join(values[0].split()[:3]))
            break
    title_fields = parsed.get_fields("245")
    if title_fields:
        values = title_fields[0].get_subfields("a")
        if values:
            title = sanitize_filename(" ".join(values[0].split()[:4]))
    return author, title


# Compatibility helpers for v1 tests and third-party imports. Text line parsing is intentionally
# no longer used by the application; it exists only to import old fixtures.
def extract_marc_record(
    raw_data: str,
    *,
    trim_records: bool,
    log_callback: LogCallback | None = None,
) -> Record | None:
    from pymarc import Field, Indicators, Subfield

    record = Record()
    for line in raw_data.splitlines():
        if len(line) < 4 or not line[:3].isdigit() or line[3] != " ":
            continue
        tag = line[:3]
        if trim_records and should_trim_tag(tag):
            continue
        if int(tag) < 10:
            record.add_field(Field(tag=tag, data=line[4:].strip()))  # type: ignore[no-untyped-call]
            continue
        content = line[7:].strip()
        parts = content.split("$")[1:]
        subfields = [
            Subfield(code=part[0], value=part[1:].strip())
            for part in parts
            if len(part.strip()) >= 2
        ]
        if subfields:
            record.add_field(  # type: ignore[no-untyped-call]
                Field(tag=tag, indicators=Indicators(*(line[4:6] or "  ")), subfields=subfields)
            )
    return record if record.fields else None


def decode_yaz_output(raw_output: bytes) -> str:
    return raw_output.decode("utf-8", errors="replace")


def clean_yaz_output(raw_data: str) -> str:
    return "\n".join(
        line
        for line in raw_data.splitlines()
        if len(line) >= 4 and line[:3].isdigit() and line[3] == " "
    )


def is_yaz_client_installed(_executable: str) -> bool:
    """Deprecated: v2 embeds YAZ and never searches PATH for yaz-client."""
    return False
