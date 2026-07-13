from __future__ import annotations

import pytest

from z3950_search_for_marc.domain.models import QueryType
from z3950_search_for_marc.infrastructure.yaz_engine import build_pqf, sanitize_query_term


def test_title_author_query_escapes_quotes_and_backslashes() -> None:
    query = build_pqf(QueryType.TITLE_AUTHOR, ('A "title"', "A\\uthor"))

    assert '\\"title\\"' in query
    assert "A\\\\uthor" in query
    assert "@attr 1=4" in query
    assert "@attr 1=1003" in query


def test_query_terms_reject_command_injection_newlines() -> None:
    with pytest.raises(ValueError, match="newline"):
        sanitize_query_term("safe\nshow 99")


def test_isbn_query_uses_bib1_isbn_attribute() -> None:
    assert build_pqf(QueryType.ISBN, "9780306406157").startswith("@attr 1=7")
