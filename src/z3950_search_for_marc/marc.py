"""MARC parsing and formatting helpers."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable

from pymarc import Field, Record, Subfield
from pymarc.field import Indicators

LogCallback = Callable[[str], None]

_ENCODINGS_TO_TRY = ("utf-8", "cp850", "cp1252", "latin-1")


def log(log_callback: LogCallback | None, message: str) -> None:
    """Emit a log message if a callback is available."""
    if log_callback:
        log_callback(message)


def is_yaz_client_installed(executable: str) -> bool:
    """Check if the configured yaz executable is available."""
    from subprocess import DEVNULL, CalledProcessError, run

    try:
        run([executable, "-V"], stdout=DEVNULL, stderr=DEVNULL, check=True)
        return True
    except (CalledProcessError, FileNotFoundError, OSError):
        return False


def decode_yaz_output(raw_output: bytes) -> str:
    """Decode yaz-client output, preferring decodings with fewer replacement artifacts."""
    try:
        return raw_output.decode("utf-8")
    except UnicodeDecodeError:
        pass

    best_text = raw_output.decode("utf-8", errors="replace")
    best_score = _score_decoded_text(best_text)
    for encoding in _ENCODINGS_TO_TRY:
        text = raw_output.decode(encoding, errors="replace")
        score = _score_decoded_text(text)
        if score > best_score:
            best_text = text
            best_score = score
    return best_text


def _score_decoded_text(text: str) -> int:
    printable = sum(char.isprintable() or char in "\r\n\t" for char in text)
    control_characters = sum(
        unicodedata.category(char) == "Cc" and char not in "\r\n\t" for char in text
    )
    mojibake_ranges = sum(
        "\u0370" <= char <= "\u03ff" or "\u2500" <= char <= "\u259f" for char in text
    )
    suspicious_capitals = len(re.findall(r"[a-z][À-ÖØ-Þ]", text))
    common_accented_letters = len(re.findall(r"[à-öø-ÿ]", text))
    penalty = (
        text.count("\ufffd") * 10
        + control_characters * 6
        + mojibake_ranges * 3
        + suspicious_capitals * 3
        + text.count("÷") * 2
        + text.count("Σ") * 2
    )
    return printable + common_accented_letters - penalty


def clean_yaz_output(raw_data: str) -> str:
    """Return only MARC-like output lines."""
    marc_lines = [
        line
        for line in raw_data.splitlines()
        if len(line) >= 4 and line[:3].isdigit() and line[3] == " "
    ]
    return "\n".join(marc_lines)


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Return a filesystem-safe filename."""
    forbidden_chars = r'<>:"/\|?*' if os.name == "nt" else r"/"
    sanitized = re.sub(f"[{re.escape(forbidden_chars)}]", "_", filename)
    sanitized = re.sub(r"[^\w\s\-_.]", "", sanitized)
    sanitized = re.sub(r"\s+", "_", sanitized).strip("._")
    sanitized = re.sub(r"_+", "_", sanitized)
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip("_")
    return sanitized or "MARC_Record"


def get_record_info(record: Record) -> tuple[str, str]:
    """Return sanitized author and title metadata for the current record."""
    author = "MARC_Record"
    title = "MARC_Record"

    for field in record.get_fields("100", "110", "111"):
        subfield_a = field.get_subfields("a")
        if subfield_a:
            author = sanitize_filename(" ".join(re.sub(r"[^\w\s]", "", subfield_a[0]).split()[:3]))
            break

    title_fields = record.get_fields("245")
    if title_fields:
        subfield_a = title_fields[0].get_subfields("a")
        if subfield_a:
            title = sanitize_filename(" ".join(re.sub(r"[^\w\s]", "", subfield_a[0]).split()[:4]))

    return author, title


def format_record_for_display(record: Record) -> str:
    """Format a MARC record for the UI details panel."""
    formatted_record: list[str] = []
    for field in record.fields:
        if field.is_control_field():
            formatted_record.append(f"{field.tag}    {field.data}")
            continue

        indicators = "".join(field.indicators or (" ", " "))
        subfields = " ".join(f"${subfield.code} {subfield.value}" for subfield in field.subfields)
        formatted_record.append(f"{field.tag} {indicators} {subfields}".rstrip())
    return "\n".join(formatted_record)


def _is_valid_marc_line(line: str) -> bool:
    return len(line) >= 4 and line[:3].isdigit() and line[3] == " "


def _extract_and_validate_tag(line: str) -> tuple[str, int] | None:
    tag = line[:3]
    try:
        tag_int = int(tag)
    except ValueError:
        return None
    return tag, tag_int


def _parse_indicators(indicators_str: str) -> list[str]:
    if len(indicators_str) == 2:
        return [indicators_str[0], indicators_str[1]]
    return [" ", " "]


def _remove_malformed_dollars(line_content: str, log_callback: LogCallback | None) -> str:
    while "$$" in line_content:
        start_pos = line_content.index("$$")
        end_pos = line_content.find("$", start_pos + 2)
        removed_content = (
            line_content[start_pos:] if end_pos == -1 else line_content[start_pos:end_pos]
        )
        line_content = (
            line_content[:start_pos]
            if end_pos == -1
            else line_content[:start_pos] + line_content[end_pos:]
        )
        log(log_callback, f"Malformed '$$' detected and corrected: '{removed_content}'")
    return line_content


def _parse_subfields(
    line_content: str,
    original_line: str,
    log_callback: LogCallback | None,
) -> list[Subfield]:
    subfields_parts = line_content.split("$")[1:]
    subfields: list[Subfield] = []
    valid_codes = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

    for part in subfields_parts:
        part = part.strip()
        if len(part) < 2:
            log(
                log_callback,
                f"Incomplete subfield detected and skipped in line: '{original_line}'",
            )
            continue
        code = part[0]
        value = part[1:].strip()
        if code not in valid_codes:
            log(log_callback, f"Invalid subfield code '{code}' skipped in line: '{original_line}'")
            continue
        if not value:
            log(log_callback, f"Empty subfield '{code}' skipped in line: '{original_line}'")
            continue
        subfields.append(Subfield(code=code, value=value))

    return subfields


def _should_trim_tag(tag_int: int, trim_records: bool) -> bool:
    return trim_records and (tag_int < 10 or tag_int >= 900)


def _process_line(
    line: str,
    record: Record,
    trim_records: bool,
    log_callback: LogCallback | None,
) -> None:
    if not _is_valid_marc_line(line):
        log(log_callback, f"Skipping invalid MARC line: '{line}'")
        return

    tag_info = _extract_and_validate_tag(line)
    if not tag_info:
        log(log_callback, f"Invalid tag in line: '{line}'")
        return

    tag, tag_int = tag_info
    if _should_trim_tag(tag_int, trim_records):
        return

    line_content = line[7:].strip()

    if tag_int < 10:
        record.add_field(Field(tag=tag, data=line_content))  # type: ignore[no-untyped-call]
        return

    indicators = Indicators(*_parse_indicators(line[4:6]))
    sanitized_line = _remove_malformed_dollars(line_content, log_callback)
    subfields = _parse_subfields(sanitized_line, line, log_callback)
    if subfields:
        record.add_field(  # type: ignore[no-untyped-call]
            Field(tag=tag, indicators=indicators, subfields=subfields)
        )
    else:
        log(log_callback, f"No valid subfields found for tag {tag}. Field not added.")


def extract_marc_record(
    raw_data: str,
    *,
    trim_records: bool,
    log_callback: LogCallback | None = None,
) -> Record | None:
    """Parse a MARC record from cleaned YAZ output."""
    record = Record()
    for line in raw_data.splitlines():
        _process_line(line, record, trim_records, log_callback)

    if not record.fields:
        log(log_callback, "No valid fields found in the record.")
        return None
    return record
