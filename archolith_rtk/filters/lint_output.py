"""Lint-output filter — compresses verbose lint output on success."""

from __future__ import annotations

from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter, GenericFilterOptions


@dataclass(frozen=True)
class LintFilterOptions:
    head_lines: int = 15
    tail_lines: int = 30


DEFAULT_OPTS = LintFilterOptions()


def lint_filter(formatted: str, opts: LintFilterOptions | None = None) -> FilterResult:
    """Filter lint output: on success, lint output is typically short and actionable."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    return generic_filter(
        formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines)
    )
