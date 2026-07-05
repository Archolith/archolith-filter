from __future__ import annotations

import pytest

pytest.importorskip("pytest_benchmark")

from archolith_filter import (
    shrink_messages,
    shrink_oversized_tool_call_args_by_tokens,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
)


def test_benchmark_shrink_messages_token_mode(benchmark, large_dict_history_factory: callable) -> None:
    result = benchmark(lambda: shrink_messages(large_dict_history_factory(14), max_tokens=500))
    assert isinstance(result, list)
    assert result


def test_benchmark_shrink_tool_results_char_mode(benchmark, large_tool_history_factory: callable) -> None:
    result = benchmark(lambda: shrink_oversized_tool_results(large_tool_history_factory(14), max_chars=2500))
    assert result.healed_count > 0


def test_benchmark_shrink_tool_results_token_mode(benchmark, large_tool_history_factory: callable) -> None:
    result = benchmark(lambda: shrink_oversized_tool_results_by_tokens(large_tool_history_factory(14), max_tokens=400))
    assert result.healed_count > 0
    assert result.tokens_saved >= 0


def test_benchmark_shrink_tool_call_args(benchmark, large_tool_call_messages_factory: callable) -> None:
    result = benchmark(lambda: shrink_oversized_tool_call_args_by_tokens(large_tool_call_messages_factory(), 350))
    assert result.healed_count > 0
