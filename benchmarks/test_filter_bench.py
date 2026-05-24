from __future__ import annotations

import pytest

pytest.importorskip("pytest_benchmark")

from archolith_rtk import filter_output


def test_benchmark_filter_output_git_diff(benchmark, git_diff_large_text: str) -> None:
    result = benchmark(lambda: filter_output(git_diff_large_text, command="git diff --staged"))
    assert result.truncated
    assert result.raw_chars > result.filtered_chars


def test_benchmark_filter_output_search_heading(benchmark, search_heading_large_text: str) -> None:
    result = benchmark(lambda: filter_output(search_heading_large_text, command="rg --heading prompt_tokens src"))
    assert result.truncated
    assert "(unsorted)" not in result.output
    assert "src/v4/search/generated_4.py" in result.output
    assert result.raw_chars > result.filtered_chars


def test_benchmark_filter_output_bracketed_logs(benchmark, bracketed_logs_large_text: str) -> None:
    result = benchmark(lambda: filter_output(bracketed_logs_large_text, tool="wait_for_job"))
    assert result.truncated
    assert "ready in 1488ms" in result.output
    assert result.raw_chars > result.filtered_chars


def test_benchmark_filter_output_json(benchmark, nested_json_large_text: str) -> None:
    result = benchmark(lambda: filter_output(nested_json_large_text, command="jq . response.json"))
    assert result.truncated
    assert '"metadata"' in result.output
    assert result.raw_chars > result.filtered_chars
