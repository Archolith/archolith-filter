"""Git-log filter — keeps oneline format compact with head/tail windowing."""

from __future__ import annotations

import re

from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter, GenericFilterOptions, _extract_header


@dataclass(frozen=True)
class GitLogFilterOptions:
    head_commits: int = 25
    tail_commits: int = 15


DEFAULT_OPTS = GitLogFilterOptions()

_ONELINE_RE = re.compile(r"^[0-9a-f]{6,40}\s")


def git_log_filter(formatted: str, opts: GitLogFilterOptions | None = None) -> FilterResult:
    """Filter git log output: for oneline format, compress with head/tail windowing."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    header, body = _extract_header(lines)

    if not body:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    # Detect oneline format: each non-blank body line starts with a hex hash.
    is_oneline = all(ln.strip() == "" or _ONELINE_RE.match(ln) for ln in body)

    if not is_oneline:
        return generic_filter(formatted)

    commit_lines = [ln for ln in body if ln.strip() != ""]

    if len(commit_lines) <= opts.head_commits + opts.tail_commits:
        result = "\n".join(header + body)
        return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=False)

    non_blank_head = commit_lines[: opts.head_commits]
    non_blank_tail = commit_lines[-opts.tail_commits :]
    omitted = len(commit_lines) - opts.head_commits - opts.tail_commits
    marker = f"[... {omitted} commits omitted ...]"

    result = "\n".join(header + non_blank_head + ["", marker, ""] + non_blank_tail)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
