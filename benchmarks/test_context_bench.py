from __future__ import annotations

import pytest

pytest.importorskip("pytest_benchmark")

from archolith_rtk import ContextManager


def test_benchmark_context_fold(benchmark, large_tool_history_factory: callable) -> None:
    manager = ContextManager(ctx_max=128000)

    def run_fold():
        history = large_tool_history_factory(18)
        return manager.fold(history, keep_recent_tokens=4000)

    result = benchmark(run_fold)
    assert result.folded


def test_benchmark_context_preflight(benchmark, large_tool_history_factory: callable) -> None:
    manager = ContextManager(ctx_max=64000)
    tool_specs = [{"name": f"tool_{index}", "description": "benchmark tool surface" * 10} for index in range(24)]
    result = benchmark(lambda: manager.decide_preflight(large_tool_history_factory(18), tool_specs))
    assert result.estimate_tokens > 0


def test_benchmark_context_emergency_compact(benchmark, large_tool_history_factory: callable) -> None:
    manager = ContextManager(ctx_max=64000)
    result = benchmark(lambda: manager.emergency_compact(large_tool_history_factory(18), max_result_chars=1200))
    assert len(result) > 0
