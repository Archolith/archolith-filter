"""Test-output filter — keeps summary tail and compresses verbose test runs."""

from __future__ import annotations

from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter, GenericFilterOptions


@dataclass(frozen=True)
class TestFilterOptions:
    head_lines: int = 10
    tail_lines: int = 40


DEFAULT_OPTS = TestFilterOptions()


def filter_test_output(formatted: str, opts: TestFilterOptions | None = None) -> FilterResult:
    """Filter test output: prioritize the tail summary over verbose per-test output."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    return generic_filter(formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines))
