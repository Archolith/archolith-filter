from __future__ import annotations

import pytest

from benchmarks.corpora import (
    build_large_dict_history,
    build_large_tool_call_messages,
    build_large_tool_history,
    get_bracketed_logs_large_text,
    get_git_diff_large_text,
    get_nested_json_large_text,
    get_search_heading_large_text,
)


@pytest.fixture(scope="session")
def git_diff_large_text() -> str:
    return get_git_diff_large_text()


@pytest.fixture(scope="session")
def search_heading_large_text() -> str:
    return get_search_heading_large_text()


@pytest.fixture(scope="session")
def bracketed_logs_large_text() -> str:
    return get_bracketed_logs_large_text()


@pytest.fixture(scope="session")
def nested_json_large_text() -> str:
    return get_nested_json_large_text()


@pytest.fixture(scope="session")
def large_tool_history_factory(
    git_diff_large_text: str,
    search_heading_large_text: str,
    bracketed_logs_large_text: str,
) -> callable:
    def _build(turns: int = 12) -> list:
        return build_large_tool_history(turns)

    return _build


@pytest.fixture(scope="session")
def large_dict_history_factory(large_tool_history_factory: callable) -> callable:
    def _build(turns: int = 12) -> list[dict]:
        return build_large_dict_history(turns)

    return _build


@pytest.fixture(scope="session")
def large_tool_call_messages_factory() -> callable:
    def _build(calls: int = 6, repeated_lines: int = 180) -> list:
        return build_large_tool_call_messages(calls, repeated_lines)

    return _build
