"""
Utility Functions for MARC Record Processing.

This module provides helper functions for cleaning, extracting, and retrieving information
from raw MARC (Machine-Readable Cataloging) data. It ensures that MARC records are properly
parsed, handles malformed subfield delimiters, and facilitates the extraction of key record
information such as authors and titles.

Key Functions:
    - extract_marc_record(raw_data: str, log_callback: Optional[Callable[[str], None]] = None) ->
    Optional[Record]:
        Parses raw MARC data to extract a single MARC record, handling and correcting malformed
        subfield delimiters as necessary. Returns a `pymarc.Record` object if successful,
        else `None`.

    - get_record_info(record: Record) -> Tuple[str, str]:
        Retrieves the author and title information from a given MARC record. Returns a tuple
        containing
        the author's name and the record's title.

    - clean_yaz_output(raw_output: str) -> str:
        Cleans the output from YAZ client commands by removing unnecessary whitespace and
        correcting any known formatting issues.

Usage:
    Import the desired functions and utilize them within your application to process MARC records.

Example:
    ```python
    from pymarc import Record
    from utils import extract_marc_record, get_record_info

    raw_data = "..."  # Raw MARC data as a string
    record = extract_marc_record(raw_data, log_callback=print)
    if record:
        author, title = get_record_info(record)
        print(f"Author: {author}, Title: {title}")
    ```

Dependencies:
    - pymarc
    - typing
    - re
    - List, Tuple, Optional, Callable from typing
"""

import os
import re
import subprocess
from typing import Optional, Callable, List, Tuple
from pymarc import Field, Subfield, Record


def is_yaz_client_installed() -> bool:
    """
    Check if yaz-client is installed and accessible.

    Returns:
        bool: True if yaz-client is found in PATH, False otherwise.
    """
    try:
        # Attempt to get the version of yaz-client
        subprocess.run(
            ["yaz-client", "-V"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
            )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def clean_yaz_output(raw_data: str, min_tag: int = 10, max_tag: int = 899) -> str:
    """
    Clean YAZ client log output and return only the MARC record data.

    Args:
        raw_data (str): The raw output from YAZ client.
        min_tag (int, optional): Minimum tag value to include. Defaults to 10.
        max_tag (int, optional): Maximum tag value to include. Defaults to 899.

    Returns:
        str: Cleaned MARC record data.
    """
    marc_lines = [line for line in raw_data.splitlines() if
                  len(line) >= 4 and line[:3].isdigit() and line[3] == " " and min_tag <= int(
                      line[:3]
                      ) <= max_tag]
    return "\n".join(marc_lines)


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize the filename by removing or replacing forbidden characters based on the OS.

    Args:
        filename (str): The original filename.
        max_length (int, optional): Maximum allowed length for the filename. Defaults to 255.

    Returns:
        str: The sanitized filename.
    """
    # Define forbidden characters for different operating systems
    if os.name == 'nt':  # Windows
        forbidden_chars = r'<>:"/\|?*'
    else:  # POSIX (Linux, macOS, etc.)
        forbidden_chars = r'/'

    # Replace forbidden characters with an underscore
    sanitized = re.sub(f'[{re.escape(forbidden_chars)}]', '_', filename)

    # Optionally, remove any remaining non-printable or problematic characters
    sanitized = re.sub(r'[^\w\s\-_.]', '', sanitized)

    # Replace spaces with underscores for consistency
    sanitized = re.sub(r'\s+', '_', sanitized)

    # Truncate the filename if it exceeds the maximum length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('_')

    return sanitized


def get_record_info(record: Record) -> tuple:
    """
    Extract author and title from the MARC record, limit them to a specified number of words,
    and sanitize them for safe filenames.

    Args:
        record (pymarc.Record): The MARC record.

    Returns:
        tuple: A tuple containing (author, title), each sanitized and limited in length.
    """
    author = "MARC_Record"
    title = "MARC_Record"

    # Extract author from fields 100, 110, 111
    author_fields = record.get_fields("100", "110", "111")
    for field in author_fields:
        subfield_a = field.get_subfields('a')
        if subfield_a:
            # Remove non-word characters and strip whitespace
            clean_author = re.sub(r"[^\w\s]", "", subfield_a[0]).strip()
            # Split into words and limit to first 3
            author_words = clean_author.split()
            limited_author = ' '.join(author_words[:3])
            # Sanitize the limited author string
            author = sanitize_filename(limited_author)
            break  # Use the first available author field

    # Extract title from field 245
    title_fields = record.get_fields("245")
    if title_fields:
        subfield_a = title_fields[0].get_subfields('a')
        if subfield_a:
            # Remove non-word characters and strip whitespace
            clean_title = re.sub(r"[^\w\s]", "", subfield_a[0]).strip()
            # Split into words and limit to first 4
            title_words = clean_title.split()
            limited_title = ' '.join(title_words[:4])
            # Sanitize the limited title string
            title = sanitize_filename(limited_title)

    return author, title


def _is_valid_marc_line(line: str) -> bool:
    """Check if the line is a valid MARC line."""
    return len(line) >= 4 and line[:3].isdigit() and line[3] == " "


def _extract_and_validate_tag(line: str) -> Optional[Tuple[str, int]]:
    """
    Extract the tag from the line and validate its range.

    Args:
        line (str): A single line of MARC data.

    Returns:
        Optional[Tuple[str, int]]: Tuple of tag and its integer value if valid, else None.
    """
    tag = line[:3]
    try:
        tag_int = int(tag)
        if 10 <= tag_int < 900:
            return tag, tag_int
    except ValueError:
        pass
    return None


def _parse_indicators(indicators_str: str) -> List[str]:
    """Parse indicators from the string, defaulting to spaces if invalid."""
    if len(indicators_str) == 2:
        return [indicators_str[0], indicators_str[1]]
    return [' ', ' ']  # Default indicators


def _remove_malformed_dollars(
        line_content: str, log_callback: Optional[Callable[[str], None]] = None
        ) -> str:
    """Remove malformed '$$' sequences from the line content."""
    while "$$" in line_content:
        start_pos = line_content.index("$$")
        end_pos = line_content.find("$", start_pos + 2)

        if end_pos == -1:
            removed_content = line_content[start_pos:]
            line_content = line_content[:start_pos]
            if log_callback:
                log_callback(f"Malformed '$$' detected and corrected: '{removed_content}'")
        else:
            removed_content = line_content[start_pos:end_pos]
            line_content = line_content[:start_pos] + line_content[end_pos:]
            if log_callback:
                log_callback(f"Malformed '$$' detected and corrected: '{removed_content}'")
    return line_content


def _parse_subfields(
        line_content: str, original_line: str, log_callback: Optional[Callable[[str], None]] = None
        ) -> List[Subfield]:
    """Parse subfields from the sanitized line content."""
    subfields_parts = line_content.split("$")[1:]  # Skip the first split part
    subfields = []
    incomplete_subfields: List[str] = []
    invalid_subfields: List[Tuple[str, str]] = []
    valid_codes = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')

    for part in subfields_parts:
        part = part.strip()
        if len(part) < 2:
            incomplete_subfields.append(part)
            continue
        code = part[0]
        value = part[1:].strip()

        if code not in valid_codes:
            invalid_subfields.append((code, value))
            continue

        if not value:
            incomplete_subfields.append(code)
            continue

        subfields.append(Subfield(code=code, value=value))

    # Aggregate and log warnings
    if incomplete_subfields and log_callback:
        formatted_incomplete = ', '.join(
            f"'{code}'" if len(code) == 1 else f"'{part}'" for code, part in
            zip(incomplete_subfields, incomplete_subfields)
            )
        log_callback(
            f"Incomplete subfields detected and adjusted: {formatted_incomplete} in line: '"
            f"{original_line}'"
            )

    if invalid_subfields and log_callback:
        for code, value in invalid_subfields:
            log_callback(
                f"Invalid subfield code '{code}' with value '{value}' detected and skipped in "
                f"line: '{original_line}'"
                )

    return subfields


def _add_field_to_record(
        tag: str, indicators: Optional[List[str]], subfields: List[Subfield], record: Record
        ):
    """Add a field to the MARC record if subfields are valid."""
    field = Field(tag=tag, indicators=indicators, subfields=subfields)
    record.add_field(field)


def _log_no_valid_subfields(tag: str, log_callback: Optional[Callable[[str], None]] = None):
    """Log a message if no valid subfields are found for a tag."""
    if log_callback:
        log_callback(f"No valid subfields found for tag {tag}. Field not added.")


def _process_line(line: str, record: Record, log_callback: Optional[Callable[[str], None]] = None):
    """
    Process a single line of MARC data.

    Args:
        line (str): A single line of MARC data.
        record (pymarc.Record): The MARC record to populate.
        log_callback (callable, optional): Function to call for logging messages.
    """

    if not _is_valid_marc_line(line):
        log_callback(f"Skipping invalid MARC line: '{line}'")
        return  # Not a valid MARC line

    tag_info = _extract_and_validate_tag(line)
    if not tag_info:
        log_callback(f"Invalid tag in line: '{line}'")
        return  # Tag out of desired range or invalid

    tag, _ = tag_info
    indicators = _parse_indicators(line[4:6])
    line_content = line[7:].strip()
    line_content = _remove_malformed_dollars(line_content, log_callback)
    subfields = _parse_subfields(line_content, line, log_callback)

    if subfields:
        _add_field_to_record(tag, indicators, subfields, record)
    else:
        _log_no_valid_subfields(tag, log_callback)



def extract_marc_record(raw_data: str, log_callback: Optional[Callable[[str], None]] = None) -> Optional[Record]:
    """
    Extract a single MARC record from raw data.

    Args:
        raw_data (str): The raw MARC data as a string.
        log_callback (callable, optional): Function to call for logging messages.

    Returns:
        pymarc.Record or None: The extracted MARC Record object or None if extraction failed.
    """
    # Initialize a new MARC record
    record = Record()

    # Track lines processed for debugging
    processed_lines = 0
    for line in raw_data.splitlines():
        _process_line(line, record, log_callback)
        processed_lines += 1

    # Validate if the record has at least one field
    if len(record.fields) == 0:
        log_callback("No valid fields found in the record.")
        return None

    # If everything seems okay, return the record
    log_callback("MARC record extraction successful.")
    return record

