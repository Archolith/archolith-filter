"""Build-output filter — compresses verbose compilation output."""

from __future__ import annotations

from dataclasses import dataclass

from . import FilterResult
from .generic import GenericFilterOptions, generic_filter


@dataclass(frozen=True)
class BuildFilterOptions:
    head_lines: int = 15
    tail_lines: int = 25


DEFAULT_OPTS = BuildFilterOptions()


def build_filter(formatted: str, opts: BuildFilterOptions | None = None) -> FilterResult:
    """Filter build output: successful builds are mostly noise, so use a smaller window."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    return generic_filter(formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines))
