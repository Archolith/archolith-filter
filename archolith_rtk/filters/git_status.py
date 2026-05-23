"""Git-status filter — keeps short-status intact, compresses long format."""

from __future__ import annotations

import re

from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter, GenericFilterOptions, _extract_header


@dataclass(frozen=True)
class GitStatusFilterOptions:
    head_lines: int = 50
    tail_lines: int = 30


DEFAULT_OPTS = GitStatusFilterOptions()

_SHORT_STATUS_RE = re.compile(r"^[A-Z? !]{2}\s")


def git_status_filter(formatted: str, opts: GitStatusFilterOptions | None = None) -> FilterResult:
    """Filter git status output. Short-format (-s) passes through; long-format falls to generic."""
    if opts is None:
        opts = DEFAULT_OPTS

    lines = formatted.split("\n")
    _, body = _extract_header(lines)

    if not body:
        return FilterResult(
            output=formatted, raw_chars=len(formatted), filtered_chars=len(formatted), truncated=False
        )

    non_blank = next((ln for ln in body if ln.strip() != ""), None)
    if non_blank and _SHORT_STATUS_RE.match(non_blank):
        return generic_filter(
            formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines)
        )

    return generic_filter(formatted)
