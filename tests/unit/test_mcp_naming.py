from __future__ import annotations

import re

import pytest

from reportify.modules.tools.naming import (
    is_mcp_model_name,
    mcp_database_name,
    mcp_model_name,
    mcp_prefix,
    parse_database_name,
    sanitize_segment,
)

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def test_database_name_is_namespaced() -> None:
    assert mcp_database_name("github", "search_issues") == "mcp.github.search_issues"


def test_parse_database_name_round_trip() -> None:
    name = mcp_database_name("github", "search.issues")
    assert parse_database_name(name) == ("github", "search.issues")


def test_parse_rejects_non_mcp_names() -> None:
    assert parse_database_name("builtin.query_dataset") is None
    assert parse_database_name("mcp.only-one-part") is None


def test_model_name_is_a_valid_identifier() -> None:
    for slug, tool in [
        ("github", "search_issues"),
        ("my-server", "list-issues"),
        ("9lives", "fetch.all"),
        ("UPPER", "MixedCase"),
    ]:
        name = mcp_model_name(slug, tool)
        assert IDENTIFIER.match(name), name
        assert is_mcp_model_name(name)


def test_prefix_has_no_trailing_separator() -> None:
    # ``prefixed()`` adds the underscore itself; a trailing one would double it.
    assert mcp_prefix("github") == "mcp_github"
    assert mcp_model_name("github", "echo") == "mcp_github_echo"


def test_model_names_are_distinct_for_distinct_tools() -> None:
    a = mcp_model_name("github", "search-issues")
    b = mcp_model_name("github", "search_issues")
    assert a == b  # documented collision: separators are normalised

    c = mcp_model_name("github", "searchissues")
    assert c != a


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("search_issues", "search_issues"),
        ("search-issues", "search_issues"),
        ("Search.Issues", "search_issues"),
        ("", "tool"),
        ("___", "tool"),
        ("1st", "t_1st"),
    ],
)
def test_sanitize_segment(raw: str, expected: str) -> None:
    assert sanitize_segment(raw) == expected
